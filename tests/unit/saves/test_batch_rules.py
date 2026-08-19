from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

import pytest

from gameshelf.library.models import Game
from gameshelf.platform.windows.known_folders import KnownFolders
from gameshelf.saves.batch_rules import (
    BatchRuleContext,
    BatchRuleProvider,
)
from gameshelf.saves.custom_manifest_provider import (
    CustomManifestError,
    CustomManifestLoadResult,
    LoadedCustomManifest,
)
from gameshelf.saves.engine_hints import EngineSaveHintProvider
from gameshelf.saves.ludusavi_index import LudusaviIndex
from gameshelf.saves.ludusavi_index_builder import build_ludusavi_index
from gameshelf.saves.ludusavi_parser import parse_manifest
from gameshelf.saves.models import SaveLocation
from gameshelf.saves.templates import PathTemplateResolver
from gameshelf.scanning.path_keys import windows_path_key


@dataclass
class _Library:
    games: tuple[Game, ...]
    install_dirs: dict[str, Path]
    list_calls: int = 0

    def list_games(self) -> tuple[Game, ...]:
        self.list_calls += 1
        return self.games

    def install_directory(self, game_id: str) -> Path:
        return self.install_dirs[game_id]


@dataclass
class _SaveLocations:
    locations: tuple[SaveLocation, ...]
    list_calls: int = 0

    def list_all(self) -> tuple[SaveLocation, ...]:
        self.list_calls += 1
        return self.locations


@dataclass
class _Ludusavi:
    index: LudusaviIndex
    session_calls: int = 0

    @contextmanager
    def index_session(self) -> Iterator[LudusaviIndex]:
        self.session_calls += 1
        yield self.index


@dataclass
class _Custom:
    result: CustomManifestLoadResult
    load_calls: int = 0

    def load_all(self) -> CustomManifestLoadResult:
        self.load_calls += 1
        return self.result


class _BrokenLudusavi:
    @contextmanager
    def index_session(self) -> Iterator[LudusaviIndex]:
        raise OSError("索引损坏")
        yield  # pragma: no cover


class _BrokenCustom:
    def load_all(self) -> CustomManifestLoadResult:
        raise ValueError("清单损坏")


@dataclass
class _Registry:
    existing: set[str]
    calls: list[str]

    def key_exists(self, key: str) -> bool:
        self.calls.append(key)
        return key.casefold() in {item.casefold() for item in self.existing}


def test_batch_rule_provider_collects_all_sources_once_without_reading_saves(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folders = _folders(tmp_path)
    resolver = PathTemplateResolver(folders)
    alice_dir = tmp_path / "Games" / "Alice"
    missing_dir = tmp_path / "Games" / "Missing"
    app_info = alice_dir / "Alice_Data" / "app.info"
    app_info.parent.mkdir(parents=True)
    app_info.write_text("Studio\nProduct\n", encoding="utf-8")
    local_save = alice_dir / "local-save.dat"
    local_save.write_bytes(b"private local body")
    custom_local_save = alice_dir / "custom-save.dat"
    custom_local_save.write_bytes(b"private custom body")
    shared = folders.documents / "Shared"
    shared.mkdir(parents=True)
    save_file = shared / "slot.sav"
    save_file.write_bytes(b"private save body")
    external = folders.app_data / "External" / "save.dat"
    external.parent.mkdir(parents=True)
    external.write_bytes(b"private external body")
    unity_directory = folders.local_app_data_low / "Studio" / "Product"
    unity_directory.mkdir(parents=True)

    alice = _game("game-alice", "Alice", "installed", "unity")
    missing = _game("game-missing", "Missing", "missing", None)
    library = _Library(
        (alice, missing),
        {alice.id: alice_dir, missing.id: missing_dir},
    )
    recorded = SaveLocation(
        id="location-1",
        game_id=alice.id,
        kind="directory",
        path_template=r"<winDocuments>\Shared",
        display_path=str(shared),
        path_key=windows_path_key(shared),
        source="manual",
        confidence=1.0,
        evidence=("用户已确认",),
        confirmed=True,
        enabled=True,
        last_verified_at=None,
    )
    saves = _SaveLocations((recorded,))
    official = _index(
        tmp_path,
        r"""
Alice:
  files:
    <winDocuments>/Shared: {tags: [save]}
    <base>/local-save.dat: {tags: [save]}
External Work:
  files:
    <winAppData>/External/save.dat: {tags: [save]}
    <winAppData>/External/*.sav: {tags: [save]}
""",
    )
    ludusavi = _Ludusavi(official)
    custom_manifest = parse_manifest(
        StringIO(
            r"""
Alice:
  files:
    <winDocuments>/Shared: {tags: [save]}
    <game>/custom-save.dat: {tags: [save]}
  registry:
    HKEY_CURRENT_USER/Software/Custom/Alice: {tags: [save]}
"""
        )
    )
    custom = _Custom(
        CustomManifestLoadResult(
            (LoadedCustomManifest("local.yaml", custom_manifest),),
            (CustomManifestError("broken.yaml", "YAML 无效"),),
        )
    )
    registry = _Registry(
        {
            r"HKEY_CURRENT_USER\Software\Custom\Alice",
            r"HKEY_CURRENT_USER\Software\Studio\Product",
        },
        [],
    )
    real_open = Path.open

    def guarded_open(path: Path, *args: object, **kwargs: object) -> object:
        if path in {save_file, external, local_save, custom_local_save}:
            raise AssertionError("不得读取存档正文")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    provider = BatchRuleProvider(
        library=library,
        save_repository=saves,
        resolver=resolver,
        ludusavi_provider=ludusavi,
        custom_provider=custom,
        engine_hints=EngineSaveHintProvider(resolver),
        registry=registry,
    )

    catalog = provider.collect(
        BatchRuleContext(
            root_tokens=(
                "<winDocuments>",
                "<winAppData>",
                "<winLocalAppDataLow>",
            )
        )
    )

    assert library.list_calls == 1
    assert saves.list_calls == 1
    assert ludusavi.session_calls == 1
    assert custom.load_calls == 1
    assert any("broken.yaml" in warning for warning in catalog.warnings)
    shared_candidate = next(
        item for item in catalog.candidates if item.path_key == windows_path_key(shared)
    )
    assert shared_candidate.sources == ("recorded", "custom", "ludusavi")
    assert {
        item.game_id for item in catalog.identities_by_path[("directory", windows_path_key(shared))]
    } == {alice.id}
    assert any(item.display_path == str(external) for item in catalog.candidates)
    assert any(item.display_path == str(local_save) for item in catalog.candidates)
    assert any(item.display_path == str(custom_local_save) for item in catalog.candidates)
    assert any(item.display_path == str(unity_directory) for item in catalog.candidates)
    assert any(item.kind == "registry" for item in catalog.candidates)
    assert any(item.relative_pattern == r"External\*.sav" for item in catalog.reverse_path_rules)
    assert catalog.rules_version


def test_batch_rule_provider_degrades_when_official_and_custom_rules_are_broken(
    tmp_path: Path,
) -> None:
    resolver = PathTemplateResolver(_folders(tmp_path))
    provider = BatchRuleProvider(
        library=_Library((), {}),
        save_repository=_SaveLocations(()),
        resolver=resolver,
        ludusavi_provider=_BrokenLudusavi(),
        custom_provider=_BrokenCustom(),
        engine_hints=EngineSaveHintProvider(resolver),
        registry=_Registry(set(), []),
    )

    catalog = provider.collect(BatchRuleContext(("<winDocuments>",)))

    assert catalog.candidates == ()
    assert any("自定义存档清单" in warning for warning in catalog.warnings)
    assert any("Ludusavi" in warning for warning in catalog.warnings)
    assert catalog.rules_version


def _folders(tmp_path: Path) -> KnownFolders:
    home = tmp_path / "Profile"
    return KnownFolders(
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


def _index(tmp_path: Path, document: str) -> LudusaviIndex:
    path = tmp_path / "manifest-index.sqlite"
    build_ludusavi_index(
        path,
        parse_manifest(StringIO(document)),
        manifest_sha256="e" * 64,
    )
    return LudusaviIndex.open(path, manifest_sha256="e" * 64)


def _game(
    game_id: str,
    title: str,
    status: str,
    engine_id: str | None,
) -> Game:
    return Game(
        id=game_id,
        scan_root_id="root-1",
        relative_dir=title,
        install_path_key=windows_path_key(rf"D:\Games\{title}"),
        title=title,
        detected_title=title,
        status=status,  # type: ignore[arg-type]
        detected_engine_id=engine_id,
        detected_engine_variant=None,
        engine_id=engine_id,
        engine_variant=None,
        engine_is_manual=False,
        engine_confidence=0.96 if engine_id else None,
        engine_evidence=(),
        engine_rules_version="test",
        main_exe_relpath=f"{title}.exe",
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
