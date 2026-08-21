from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

import pytest

from gameshelf.db.connection import ConnectionFactory
from gameshelf.db.migrator import Migrator
from gameshelf.db.writer import DbWriter
from gameshelf.library.models import Game
from gameshelf.library.repository import LibraryRepository
from gameshelf.library.service import LibraryService
from gameshelf.platform.windows.known_folders import KnownFolders
from gameshelf.saves.custom_manifest_provider import (
    CustomManifestLoadResult,
    LoadedCustomManifest,
)
from gameshelf.saves.engine_hints import EngineSaveHintProvider, load_engine_metadata
from gameshelf.saves.ludusavi_index import LudusaviIndex
from gameshelf.saves.ludusavi_index_builder import build_ludusavi_index
from gameshelf.saves.ludusavi_parser import parse_manifest
from gameshelf.saves.ludusavi_provider import SnapshotUpdateError
from gameshelf.saves.models import SaveLocationSuggestion
from gameshelf.saves.repository import SaveLocationRepository
from gameshelf.saves.service import SaveLocationService
from gameshelf.saves.static_discovery import StaticSaveDiscovery
from gameshelf.saves.templates import PathTemplateResolver


@dataclass
class FakeLudusaviProvider:
    index: LudusaviIndex
    session_calls: int = 0

    @contextmanager
    def index_session(self) -> Iterator[LudusaviIndex]:
        self.session_calls += 1
        yield self.index


class UnavailableLudusaviProvider:
    @contextmanager
    def index_session(self) -> Iterator[LudusaviIndex]:
        raise SnapshotUpdateError("内置清单损坏")
        yield


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
    official_provider: FakeLudusaviProvider


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
    index_path = tmp_path / "manifest-index.sqlite"
    build_ludusavi_index(index_path, official, manifest_sha256="d" * 64)
    official_provider = FakeLudusaviProvider(
        LudusaviIndex.open(index_path, manifest_sha256="d" * 64)
    )
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
        ludusavi_provider=official_provider,
        custom_provider=FakeCustomProvider(custom_result),
        engine_hints=EngineSaveHintProvider(resolver),
    )
    try:
        yield StaticHarness(discovery, save_service, game.id, official_provider)
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


def test_static_discovery_skips_unavailable_official_manifest(
    static_harness: StaticHarness,
) -> None:
    static_harness.discovery._ludusavi_provider = UnavailableLudusaviProvider()
    static_harness.discovery.invalidate_ludusavi()

    suggestions = static_harness.discovery.suggest_for_game(static_harness.game_id)

    assert suggestions
    assert {evidence.source for item in suggestions for evidence in item.source_evidence} == {
        "custom",
        "engine",
    }


def test_official_index_is_loaded_only_on_explicit_suggestion_call(
    static_harness: StaticHarness,
) -> None:
    provider = static_harness.official_provider
    assert provider.session_calls == 0

    static_harness.discovery.suggest_for_game(static_harness.game_id)
    first_matcher = static_harness.discovery._official_matcher
    static_harness.discovery.suggest_for_game(static_harness.game_id)

    assert provider.session_calls == 2
    assert static_harness.discovery._official_matcher is first_matcher


def test_registry_targets_for_game_returns_only_registry_suggestions(
    static_harness: StaticHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    suggestions = (
        SaveLocationSuggestion(
            kind="directory",
            path_template=r"<winAppData>\Alice",
            display_path=r"C:\Users\Alice\AppData\Roaming\Alice",
            source="ludusavi",
            confidence=1.0,
            evidence=("文件规则",),
        ),
        SaveLocationSuggestion(
            kind="registry",
            path_template=r"HKEY_CURRENT_USER\Software\Studio\Alice",
            display_path=r"HKEY_CURRENT_USER\Software\Studio\Alice",
            source="ludusavi",
            confidence=1.0,
            evidence=("注册表规则",),
        ),
    )
    monkeypatch.setattr(
        StaticSaveDiscovery, "suggest_for_game", lambda _self, _game_id: suggestions
    )

    targets = static_harness.discovery.registry_targets_for_game(static_harness.game_id)

    assert targets == (
        (
            r"HKEY_CURRENT_USER\Software\Studio\Alice",
            ("注册表规则",),
        ),
    )


def test_invalidate_ludusavi_reloads_index_on_next_explicit_search(
    static_harness: StaticHarness,
) -> None:
    provider = static_harness.official_provider
    static_harness.discovery.suggest_for_game(static_harness.game_id)
    first_matcher = static_harness.discovery._official_matcher

    static_harness.discovery.invalidate_ludusavi()
    static_harness.discovery.suggest_for_game(static_harness.game_id)

    assert provider.session_calls == 2
    assert static_harness.discovery._official_matcher is not first_matcher


def test_public_engine_metadata_loader_reads_unity_app_info(tmp_path: Path) -> None:
    game = _unity_game()
    install_dir = tmp_path / "UnityGame"
    metadata = install_dir / "UnityGame_Data" / "app.info"
    metadata.parent.mkdir(parents=True)
    metadata.write_text("Studio\nProduct\n", encoding="utf-8")

    assert load_engine_metadata(game, install_dir) == {
        "company_name": "Studio",
        "product_name": "Product",
    }


@pytest.mark.parametrize(
    ("engine_id", "relative_path", "content", "expected"),
    [
        (
            "godot",
            "project.godot",
            '[application]\nconfig/name="Godot Project"\n',
            {"project_name": "Godot Project"},
        ),
        (
            "unreal",
            "Nested/ReliableProject.uproject",
            '{"FileVersion": 3}',
            {"project_name": "ReliableProject"},
        ),
    ],
)
def test_public_engine_metadata_loader_reads_only_bounded_project_files(
    tmp_path: Path,
    engine_id: str,
    relative_path: str,
    content: str,
    expected: dict[str, str],
) -> None:
    game = _unity_game(engine_id)
    install_dir = tmp_path / "Game"
    metadata_path = install_dir.joinpath(*relative_path.split("/"))
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text(content, encoding="utf-8")

    assert load_engine_metadata(game, install_dir) == expected


def _unity_game(engine_id: str = "unity") -> Game:
    return Game(
        id="unity-game",
        scan_root_id="root-1",
        relative_dir="UnityGame",
        install_path_key=r"d:\games\unitygame",
        title="UnityGame",
        detected_title="UnityGame",
        status="installed",
        detected_engine_id=engine_id,
        detected_engine_variant=None,
        engine_id=engine_id,
        engine_variant=None,
        engine_is_manual=False,
        engine_confidence=1.0,
        engine_evidence=(),
        engine_rules_version="test",
        main_exe_relpath="UnityGame.exe",
        main_exe_is_manual=False,
        working_dir_relpath=None,
        launch_args=(),
        environment={},
        exe_arch="unknown",
        cover_original_relpath=None,
        cover_thumb_relpath=None,
        cover_revision=0,
        last_launched_at=None,
        missing_since=None,
    )
