from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

import pytest

from gameshelf.db.connection import ConnectionFactory
from gameshelf.db.migrator import Migrator
from gameshelf.db.writer import DbWriter
from gameshelf.library.repository import LibraryRepository
from gameshelf.library.service import LibraryService
from gameshelf.platform.windows.known_folders import KnownFolders
from gameshelf.saves.custom_manifest_provider import (
    CustomManifestLoadResult,
    LoadedCustomManifest,
)
from gameshelf.saves.engine_hints import EngineSaveHintProvider
from gameshelf.saves.ludusavi_models import LudusaviManifest
from gameshelf.saves.ludusavi_parser import parse_manifest
from gameshelf.saves.repository import SaveLocationRepository
from gameshelf.saves.service import SaveLocationService
from gameshelf.saves.static_discovery import StaticSaveDiscovery
from gameshelf.saves.templates import PathTemplateResolver


@dataclass
class FakeLudusaviProvider:
    manifest: LudusaviManifest

    def load(self) -> LudusaviManifest:
        return self.manifest


@dataclass
class FakeCustomProvider:
    result: CustomManifestLoadResult

    def load_all(self) -> CustomManifestLoadResult:
        return self.result


class NoopShell:
    def open_directory(self, _path: Path) -> None: ...

    def reveal_file(self, _path: Path) -> None: ...


class NoopRegistry:
    def key_exists(self, _key: str) -> bool:
        return False

    def open_key(self, _key: str) -> None: ...


@dataclass
class StaticHarness:
    discovery: StaticSaveDiscovery
    save_service: SaveLocationService
    game_id: str


@pytest.fixture
def static_harness(tmp_path: Path) -> Iterator[StaticHarness]:
    factory = ConnectionFactory(tmp_path / "data" / "library.db")
    Migrator(factory, tmp_path / "backups").migrate()
    writer = DbWriter(factory)
    writer.start()
    repository = LibraryRepository(factory)
    library = LibraryService(repository, writer)
    game_root = tmp_path / "Games"
    install_dir = game_root / "Alice"
    (install_dir / "game").mkdir(parents=True)
    (install_dir / "game" / "options.rpy").write_text(
        'define config.save_directory = "Alice"', encoding="utf-8"
    )
    root = library.add_root(str(game_root), "children", 1, [])
    game = library.create_game_for_test(root.id, "Alice", "Alice")
    game = library.set_game_engine(game.id, "renpy")
    home = tmp_path / "Profile"
    folders = KnownFolders(
        home=home,
        app_data=home / "AppData" / "Roaming",
        local_app_data=home / "AppData" / "Local",
        local_app_data_low=home / "AppData" / "LocalLow",
        documents=home / "Documents",
        saved_games=home / "Saved Games",
        program_data=tmp_path / "ProgramData",
        public=tmp_path / "Public",
        windows=tmp_path / "Windows",
    )
    resolver = PathTemplateResolver(folders)
    document = "Alice:\n  files:\n    <winAppData>/RenPy/Alice: {tags: [save]}\n"
    official = parse_manifest(StringIO(document))
    custom = parse_manifest(StringIO(document))
    custom_result = CustomManifestLoadResult(
        (LoadedCustomManifest("local.yaml", custom),), ()
    )
    save_repository = SaveLocationRepository(factory)
    save_service = SaveLocationService(
        save_repository,
        writer,
        resolver,
        library,
        NoopShell(),
        NoopRegistry(),
    )
    discovery = StaticSaveDiscovery(
        library=library,
        save_repository=save_repository,
        resolver=resolver,
        ludusavi_provider=FakeLudusaviProvider(official),
        custom_provider=FakeCustomProvider(custom_result),
        engine_hints=EngineSaveHintProvider(resolver),
    )
    try:
        yield StaticHarness(discovery, save_service, game.id)
    finally:
        writer.close()


def test_static_discovery_merges_same_path_and_keeps_all_source_evidence(
    static_harness: StaticHarness,
) -> None:
    suggestions = static_harness.discovery.suggest_for_game(static_harness.game_id)

    assert len(suggestions) == 1
    assert suggestions[0].confidence == 1.0
    assert {item.source for item in suggestions[0].source_evidence} == {
        "custom",
        "ludusavi",
        "engine",
    }
    assert suggestions[0].preselected is True
    assert static_harness.save_service.list_for_game(static_harness.game_id) == ()


def test_confirmed_location_is_never_suggested_again(
    static_harness: StaticHarness,
) -> None:
    suggestion = static_harness.discovery.suggest_for_game(static_harness.game_id)[0]
    static_harness.save_service.accept_suggestion(static_harness.game_id, suggestion)

    assert static_harness.discovery.suggest_for_game(static_harness.game_id) == ()
