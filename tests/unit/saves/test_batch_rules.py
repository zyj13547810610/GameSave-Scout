from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

import pytest
import yaml

from gamesave_scout.library.models import Game
from gamesave_scout.platform.windows.known_folders import KnownFolders
from gamesave_scout.saves.batch_rules import BatchRuleContext, BatchRuleProvider
from gamesave_scout.saves.builtin_rules import SaveRuleProvider
from gamesave_scout.saves.engine_hints import EngineSaveHintProvider
from gamesave_scout.saves.ludusavi_index import LudusaviIndex
from gamesave_scout.saves.ludusavi_index_builder import build_ludusavi_index
from gamesave_scout.saves.ludusavi_parser import parse_manifest
from gamesave_scout.saves.models import SaveLocation
from gamesave_scout.saves.rule_schema import load_save_rules, parse_save_rule_document
from gamesave_scout.saves.templates import PathTemplateResolver
from gamesave_scout.scanning.path_keys import windows_path_key


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


class _BrokenLudusavi:
    @contextmanager
    def index_session(self) -> Iterator[LudusaviIndex]:
        raise OSError("索引损坏")
        yield  # pragma: no cover


@dataclass
class _Registry:
    existing: set[str]
    calls: list[str]

    def key_exists(self, key: str) -> bool:
        self.calls.append(key)
        return key.casefold() in {item.casefold() for item in self.existing}


@dataclass
class _Snapshot:
    catalog_version: str
    save_rules: SaveRuleProvider


@dataclass
class _SnapshotProvider:
    snapshot: _Snapshot
    calls: int = 0

    def __call__(self) -> _Snapshot:
        self.calls += 1
        return self.snapshot


def test_batch_rule_provider_collects_all_sources_once_without_reading_saves(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folders = _folders(tmp_path)
    resolver = PathTemplateResolver(folders)
    alice_dir = tmp_path / "Games" / "Alice"
    app_info = alice_dir / "Alice_Data" / "app.info"
    app_info.parent.mkdir(parents=True)
    app_info.write_text("Studio\nProduct\n", encoding="utf-8")
    local_save = alice_dir / "local-save.dat"
    local_save.write_bytes(b"private local body")
    user_local_save = alice_dir / "user-save.dat"
    user_local_save.write_bytes(b"private user body")
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
    library = _Library((alice, missing), {alice.id: alice_dir})
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
    ludusavi = _Ludusavi(
        _index(
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
    )
    save_rules = _rule_provider(
        resolver,
        r"""
version: batch-user-v1
rules:
  - id: alice_user
    label: Alice 用户规则
    type: save_game
    status: experimental
    priority: 20
    enabled: true
    references: []
    titles: [Alice]
    locations:
      - {kind: directory, path: '<winDocuments>\Shared', category: save, confidence: 0.95}
      - {kind: file, path: '<game>\user-save.dat', category: save, confidence: 0.95}
      - kind: registry
        path: 'HKEY_CURRENT_USER\Software\User\Alice'
        category: config
        confidence: 0.9
""",
        source="user",
    )
    snapshots = _SnapshotProvider(_Snapshot("catalog-v1", save_rules))
    registry = _Registry(
        {
            r"HKEY_CURRENT_USER\Software\User\Alice",
            r"HKEY_CURRENT_USER\Software\Studio\Product",
        },
        [],
    )
    real_open = Path.open

    def guarded_open(path: Path, *args: object, **kwargs: object) -> object:
        if path in {save_file, external, local_save, user_local_save}:
            raise AssertionError("不得读取存档正文")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    provider = BatchRuleProvider(
        library=library,
        save_repository=saves,
        resolver=resolver,
        ludusavi_provider=ludusavi,
        engine_hints=EngineSaveHintProvider(resolver),
        rule_snapshot_provider=snapshots,  # type: ignore[arg-type]
        registry=registry,
    )

    catalog = provider.collect(
        BatchRuleContext(
            ("<winDocuments>", "<winAppData>", "<winLocalAppDataLow>")
        )
    )

    assert snapshots.calls == 1
    assert library.list_calls == 1
    assert saves.list_calls == 1
    assert ludusavi.session_calls == 1
    shared_candidate = next(
        item for item in catalog.candidates if item.path_key == windows_path_key(shared)
    )
    assert shared_candidate.sources == ("recorded", "user", "ludusavi")
    assert {
        item.game_id
        for item in catalog.identities_by_path[
            ("directory", windows_path_key(shared))
        ]
    } == {alice.id}
    assert any(item.display_path == str(external) for item in catalog.candidates)
    assert any(item.display_path == str(local_save) for item in catalog.candidates)
    assert any(item.display_path == str(user_local_save) for item in catalog.candidates)
    assert any(item.display_path == str(unity_directory) for item in catalog.candidates)
    assert any(item.kind == "registry" for item in catalog.candidates)
    assert any(
        item.relative_pattern == r"External\*.sav"
        for item in catalog.reverse_path_rules
    )
    user_identity = next(
        identity
        for values in catalog.identities_by_path.values()
        for identity in values
        if identity.source == "user"
    )
    assert user_identity.confidence == "low"
    assert catalog.rules_version


def test_batch_rule_provider_degrades_when_ludusavi_rules_are_broken(
    tmp_path: Path,
) -> None:
    resolver = PathTemplateResolver(_folders(tmp_path))
    provider = BatchRuleProvider(
        library=_Library((), {}),
        save_repository=_SaveLocations(()),
        resolver=resolver,
        ludusavi_provider=_BrokenLudusavi(),
        engine_hints=EngineSaveHintProvider(resolver),
        rule_snapshot_provider=lambda: _Snapshot(
            "empty",
            SaveRuleProvider.empty(resolver),
        ),  # type: ignore[arg-type]
        registry=_Registry(set(), []),
    )

    catalog = provider.collect(BatchRuleContext(("<winDocuments>",)))

    assert catalog.candidates == ()
    assert any("Ludusavi" in warning for warning in catalog.warnings)
    assert catalog.rules_version


def test_batch_rule_provider_uses_latest_snapshot_on_next_collect(
    tmp_path: Path,
) -> None:
    folders = _folders(tmp_path)
    resolver = PathTemplateResolver(folders)
    game_dir = tmp_path / "Games" / "Alice"
    game_dir.mkdir(parents=True)
    first = folders.documents / "Alice" / "First"
    second = folders.documents / "Alice" / "Second"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    game = _game("game-alice", "Alice", "installed", None)
    initial = _Snapshot(
        "catalog-v1",
        _one_path_provider(resolver, "first", r"<winDocuments>\Alice\First"),
    )
    changed = _Snapshot(
        "catalog-v2",
        _one_path_provider(resolver, "second", r"<winDocuments>\Alice\Second"),
    )
    snapshots = _SnapshotProvider(initial)
    provider = BatchRuleProvider(
        library=_Library((game,), {game.id: game_dir}),
        save_repository=_SaveLocations(()),
        resolver=resolver,
        ludusavi_provider=_Ludusavi(_index(tmp_path, "{}")),
        engine_hints=EngineSaveHintProvider(resolver),
        rule_snapshot_provider=snapshots,  # type: ignore[arg-type]
        registry=_Registry(set(), []),
    )

    first_catalog = provider.collect(BatchRuleContext(("<winDocuments>",)))
    snapshots.snapshot = changed
    second_catalog = provider.collect(BatchRuleContext(("<winDocuments>",)))

    assert snapshots.calls == 2
    assert {item.display_path for item in first_catalog.candidates} == {str(first)}
    assert {item.display_path for item in second_catalog.candidates} == {str(second)}
    assert first_catalog.rules_version != second_catalog.rules_version


def test_batch_rule_provider_only_collects_existing_bundled_engine_save(
    tmp_path: Path,
) -> None:
    resolver = PathTemplateResolver(_folders(tmp_path))
    game_dir = tmp_path / "Games" / "RpgMakerVx"
    game_dir.mkdir(parents=True)
    game = _game("game-rpg-vx", "RpgMakerVx", "installed", "rpg_maker_vx")
    snapshots = _SnapshotProvider(
        _Snapshot(
            "catalog-builtin",
            SaveRuleProvider(
                load_save_rules(Path("resources/rules/builtin/saves.yaml")),
                resolver,
            ),
        )
    )
    provider = BatchRuleProvider(
        library=_Library((game,), {game.id: game_dir}),
        save_repository=_SaveLocations(()),
        resolver=resolver,
        ludusavi_provider=_Ludusavi(_index(tmp_path, "{}")),
        engine_hints=EngineSaveHintProvider(resolver),
        rule_snapshot_provider=snapshots,  # type: ignore[arg-type]
        registry=_Registry(set(), []),
    )

    missing = provider.collect(BatchRuleContext(()))
    assert not any(
        item.path_template == r"<game>\Save*.rvdata"
        for item in missing.candidates
    )

    (game_dir / "Save1.rvdata").write_bytes(b"save")
    found = provider.collect(BatchRuleContext(()))
    matching = [
        item
        for item in found.candidates
        if item.path_template == r"<game>\Save*.rvdata"
    ]

    assert len(matching) == 1
    assert matching[0].sources == ("builtin",)


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
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "manifest-index.sqlite"
    build_ludusavi_index(
        path,
        parse_manifest(StringIO(document)),
        manifest_sha256="e" * 64,
    )
    return LudusaviIndex.open(path, manifest_sha256="e" * 64)


def _rule_provider(
    resolver: PathTemplateResolver,
    document: str,
    *,
    source: str,
) -> SaveRuleProvider:
    rules = parse_save_rule_document(
        yaml.safe_load(document),
        source=source,  # type: ignore[arg-type]
        require_single=False,
    )
    return SaveRuleProvider(rules, resolver)


def _one_path_provider(
    resolver: PathTemplateResolver,
    rule_id: str,
    path: str,
) -> SaveRuleProvider:
    document = {
        "version": "1",
        "rules": [
            {
                "id": rule_id,
                "label": rule_id,
                "type": "save_game",
                "status": "experimental",
                "titles": ["Alice"],
                "locations": [
                    {
                        "kind": "directory",
                        "path": path,
                        "category": "save",
                        "confidence": 0.8,
                    }
                ],
            }
        ],
    }
    return SaveRuleProvider(
        parse_save_rule_document(document, source="user", require_single=False),
        resolver,
    )


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
