from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from io import StringIO
from pathlib import Path

import pytest
import yaml

from gameshelf.db.connection import ConnectionFactory
from gameshelf.db.migrator import Migrator
from gameshelf.db.writer import DbWriter
from gameshelf.engines.service import EngineDetectionService
from gameshelf.library.models import Game
from gameshelf.library.repository import LibraryRepository
from gameshelf.library.service import LibraryService
from gameshelf.platform.windows.known_folders import KnownFolders
from gameshelf.saves.builtin_rules import SaveRuleProvider
from gameshelf.saves.engine_hints import EngineSaveHintProvider, load_engine_metadata
from gameshelf.saves.ludusavi_index import LudusaviIndex
from gameshelf.saves.ludusavi_index_builder import build_ludusavi_index
from gameshelf.saves.ludusavi_parser import parse_manifest
from gameshelf.saves.ludusavi_provider import SnapshotUpdateError
from gameshelf.saves.models import SaveLocationSuggestion, SuggestionEvidence
from gameshelf.saves.repository import SaveLocationRepository
from gameshelf.saves.rule_probe import BoundedRuleProbe
from gameshelf.saves.rule_schema import parse_save_rule_document
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


class NoopShell:
    def open_directory(self, _path: Path) -> None: ...

    def reveal_file(self, _path: Path) -> None: ...


class NoopRegistry:
    def key_exists(self, _key: str) -> bool:
        return False

    def open_key(self, _key: str) -> None: ...


@dataclass
class RecordingBuiltinRules:
    events: list[str]
    fail: bool = False
    game_suggestions: tuple[SaveLocationSuggestion, ...] = ()
    engine_suggestions: tuple[SaveLocationSuggestion, ...] = ()

    def suggest_game_specific(
        self, _game: Game, _install_dir: Path, _metadata: object
    ) -> tuple[SaveLocationSuggestion, ...]:
        self.events.append("builtin_game")
        if self.fail:
            raise RuntimeError("broken builtin game rule")
        return self.game_suggestions

    def suggest_engine(
        self, _game: Game, _install_dir: Path, _metadata: object
    ) -> tuple[SaveLocationSuggestion, ...]:
        self.events.append("builtin_engine")
        if self.fail:
            raise RuntimeError("broken builtin engine rule")
        return self.engine_suggestions


@dataclass
class RecordingEngineHints:
    events: list[str]

    def suggest(
        self, _game: Game, _install_dir: Path, _metadata: object
    ) -> tuple[SaveLocationSuggestion, ...]:
        self.events.append("engine_code")
        return ()


class RecordingLudusaviProvider:
    def __init__(self, events: list[str], provider: FakeLudusaviProvider) -> None:
        self._events = events
        self._provider = provider

    @contextmanager
    def index_session(self) -> Iterator[LudusaviIndex]:
        self._events.append("ludusavi")
        with self._provider.index_session() as index:
            yield index


class FailingRegistry:
    def key_exists(self, _key: str) -> bool:
        raise OSError("registry unavailable")


@dataclass
class StaticHarness:
    discovery: StaticSaveDiscovery
    save_service: SaveLocationService
    game_id: str
    official_provider: FakeLudusaviProvider
    snapshot: MutableSnapshot


@dataclass
class MutableSnapshot:
    engine_detection: EngineDetectionService
    save_rules: object


@dataclass
class MutableSnapshotProvider:
    current: MutableSnapshot
    calls: int = 0

    def __call__(self) -> MutableSnapshot:
        self.calls += 1
        return self.current


@dataclass
class PublishingRules:
    provider: MutableSnapshotProvider
    replacement: MutableSnapshot
    suggestion: SaveLocationSuggestion

    def suggest_game_specific(
        self, _game: Game, _install_dir: Path, _metadata: object
    ) -> tuple[SaveLocationSuggestion, ...]:
        self.provider.current = self.replacement
        return (self.suggestion,)

    def suggest_engine(
        self, _game: Game, _install_dir: Path, _metadata: object
    ) -> tuple[SaveLocationSuggestion, ...]:
        return ()


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
    (folders.app_data / "RenPy" / "Alice").mkdir(parents=True)
    save_repository = SaveLocationRepository(factory)
    save_service = SaveLocationService(
        save_repository,
        writer,
        resolver,
        library,
        NoopShell(),
        NoopRegistry(),
    )
    snapshot = MutableSnapshot(
        EngineDetectionService.builtins_only(),
        _declarative_rules(resolver),
    )
    discovery = StaticSaveDiscovery(
        library=library,
        save_repository=save_repository,
        resolver=resolver,
        ludusavi_provider=official_provider,
        engine_hints=EngineSaveHintProvider(resolver),
        rule_snapshot_provider=lambda: snapshot,  # type: ignore[arg-type]
    )
    try:
        yield StaticHarness(discovery, save_service, game.id, official_provider, snapshot)
    finally:
        writer.close()


def test_static_discovery_merges_same_path_and_keeps_all_source_evidence(
    static_harness: StaticHarness,
) -> None:
    suggestions = static_harness.discovery.suggest_for_game(static_harness.game_id)

    assert len(suggestions) == 1
    assert suggestions[0].confidence == 1.0
    assert {item.source for item in suggestions[0].source_evidence} == {
        "user",
        "builtin",
        "ludusavi",
        "engine",
    }
    assert suggestions[0].preselected is True
    assert suggestions[0].availability == "found"
    assert static_harness.save_service.list_for_game(static_harness.game_id) == ()


def test_static_discovery_keeps_captured_snapshot_until_next_click(
    static_harness: StaticHarness,
) -> None:
    resolver = static_harness.discovery._resolver
    old_path = resolver.expand(r"<winDocuments>\Snapshot\Old", None)
    new_path = resolver.expand(r"<winDocuments>\Snapshot\New", None)
    old_path.mkdir(parents=True)
    new_path.mkdir(parents=True)

    def suggestion(path: Path, detail: str) -> SaveLocationSuggestion:
        template = resolver.collapse(path, None)
        return SaveLocationSuggestion(
            kind="directory",
            path_template=template,
            display_path=str(path),
            source="engine",
            confidence=0.95,
            evidence=(detail,),
            source_evidence=(SuggestionEvidence("user", detail),),
            suggestion_id=f"user:{detail}:0",
            group="exact",
        )

    replacement = MutableSnapshot(
        EngineDetectionService.builtins_only(),
        RecordingBuiltinRules([], game_suggestions=(suggestion(new_path, "new"),)),
    )
    provider = MutableSnapshotProvider(replacement)
    provider.current = MutableSnapshot(
        EngineDetectionService.builtins_only(),
        PublishingRules(provider, replacement, suggestion(old_path, "old")),
    )
    static_harness.discovery._rule_snapshot_provider = provider  # type: ignore[assignment]

    first = static_harness.discovery.suggest_for_game(static_harness.game_id)
    second = static_harness.discovery.suggest_for_game(static_harness.game_id)

    assert provider.calls == 2
    assert any(item.display_path == str(old_path) for item in first)
    assert not any(item.display_path == str(new_path) for item in first)
    assert any(item.display_path == str(new_path) for item in second)


def test_static_discovery_runs_all_sources_only_after_explicit_call(
    static_harness: StaticHarness,
) -> None:
    events: list[str] = []
    discovery = static_harness.discovery
    static_harness.snapshot.save_rules = RecordingBuiltinRules(events)
    discovery._ludusavi_provider = RecordingLudusaviProvider(
        events, static_harness.official_provider
    )
    discovery._engine_hints = RecordingEngineHints(events)

    assert events == []
    discovery.suggest_for_game(static_harness.game_id)

    assert events == [
        "builtin_game",
        "ludusavi",
        "builtin_engine",
        "engine_code",
    ]


def test_broken_builtin_rules_do_not_block_ludusavi_or_code_hints(
    static_harness: StaticHarness,
) -> None:
    events: list[str] = []
    discovery = static_harness.discovery
    static_harness.snapshot.save_rules = RecordingBuiltinRules(events, fail=True)
    discovery._ludusavi_provider = RecordingLudusaviProvider(
        events, static_harness.official_provider
    )
    discovery._engine_hints = RecordingEngineHints(events)

    suggestions = discovery.suggest_for_game(static_harness.game_id)

    assert suggestions
    assert "ludusavi" in events
    assert "engine_code" in events


def test_existing_path_becomes_predicted_and_unselected_after_removal(
    static_harness: StaticHarness,
) -> None:
    first = static_harness.discovery.suggest_for_game(static_harness.game_id)[0]
    Path(first.display_path).rmdir()

    predicted = static_harness.discovery.suggest_for_game(static_harness.game_id)[0]

    assert predicted.availability == "predicted"
    assert predicted.preselected is False


def test_declarative_existing_policy_filters_only_missing_strict_location(
    static_harness: StaticHarness,
) -> None:
    resolver = static_harness.discovery._resolver
    rules = parse_save_rule_document(
        yaml.safe_load(
            """\
version: test
rules:
  - id: location_policy
    label: 位置存在性策略
    type: save_game
    status: experimental
    titles: [Alice]
    locations:
      - kind: directory
        path: <winDocuments>\\Policy\\Predicted
        category: save
        confidence: 0.8
      - kind: directory
        path: <winDocuments>\\Policy\\Existing
        category: save
        confidence: 0.9
        require_existing: true
"""
        ),
        source="user",
        require_single=True,
    )
    static_harness.snapshot.save_rules = SaveRuleProvider(rules, resolver)
    relaxed_path = resolver.expand(r"<winDocuments>\Policy\Predicted", None)
    strict_path = resolver.expand(r"<winDocuments>\Policy\Existing", None)

    missing = static_harness.discovery.suggest_for_game(static_harness.game_id)

    assert any(item.display_path == str(relaxed_path) for item in missing)
    assert not any(item.display_path == str(strict_path) for item in missing)

    strict_path.mkdir(parents=True)
    found = static_harness.discovery.suggest_for_game(static_harness.game_id)
    strict = next(item for item in found if item.display_path == str(strict_path))

    assert strict.availability == "found"


def test_availability_probe_failure_keeps_candidate_with_diagnostic(
    static_harness: StaticHarness,
) -> None:
    events: list[str] = []
    registry_suggestion = SaveLocationSuggestion(
        kind="registry",
        path_template=r"HKEY_CURRENT_USER\Software\Studio\Alice",
        display_path=r"HKEY_CURRENT_USER\Software\Studio\Alice",
        source="engine",
        confidence=0.95,
        evidence=("内置游戏规则",),
        source_evidence=(
            SuggestionEvidence("builtin", "内置游戏规则"),
        ),
        group="exact",
        preselected=True,
    )
    static_harness.snapshot.save_rules = RecordingBuiltinRules(
        events,
        game_suggestions=(registry_suggestion,),
    )
    static_harness.discovery._rule_probe = BoundedRuleProbe(
        static_harness.discovery._resolver,
        FailingRegistry(),
    )

    suggestions = static_harness.discovery.suggest_for_game(static_harness.game_id)
    registry = next(item for item in suggestions if item.kind == "registry")

    assert registry.availability == "predicted"
    assert registry.preselected is False
    assert "存在性检查失败，已按可能路径保留" in registry.evidence


def test_game_specific_display_wins_while_formal_engine_evidence_is_retained(
    static_harness: StaticHarness,
) -> None:
    events: list[str] = []
    game_specific = SaveLocationSuggestion(
        kind="directory",
        path_template=r"<winDocuments>\Exact Game\Save",
        display_path=r"C:\Profile\Documents\Exact Game\Save",
        source="engine",
        confidence=0.6,
        evidence=("游戏专属实验规则",),
        source_evidence=(SuggestionEvidence("builtin", "游戏专属实验规则"),),
        group="experimental",
    )
    engine_generic = replace(
        game_specific,
        path_template=r"<winDocuments>\exact game\save",
        display_path=r"C:\Profile\Documents\exact game\save",
        confidence=0.99,
        evidence=("引擎正式规则",),
        source_evidence=(SuggestionEvidence("builtin", "引擎正式规则"),),
        group="exact",
    )
    static_harness.snapshot.save_rules = RecordingBuiltinRules(
        events,
        game_suggestions=(game_specific,),
        engine_suggestions=(engine_generic,),
    )

    suggestions = static_harness.discovery.suggest_for_game(static_harness.game_id)
    merged = next(item for item in suggestions if "Exact Game" in item.path_template)

    assert merged.path_template == game_specific.path_template
    assert merged.confidence == 0.99
    assert merged.group == "exact"
    assert {item.detail for item in merged.source_evidence} == {
        "游戏专属实验规则",
        "引擎正式规则",
    }


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
        "user",
        "builtin",
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


def _declarative_rules(resolver: PathTemplateResolver) -> SaveRuleProvider:
    builtin = parse_save_rule_document(
        yaml.safe_load(
            """\
version: test
rules:
  - id: alice_builtin
    label: Alice 内置存档
    type: save_game
    references: [https://example.com/alice]
    titles: [Alice]
    locations:
      - kind: directory
        path: <winAppData>/RenPy/Alice
        category: save
        confidence: 1.0
"""
        ),
        source="builtin",
        require_single=True,
    )
    user = parse_save_rule_document(
        yaml.safe_load(
            """\
version: test
rules:
  - id: alice_user
    label: Alice 用户存档
    type: save_game
    status: formal
    titles: [Alice]
    locations:
      - kind: directory
        path: <winAppData>/RenPy/Alice
        category: save
        confidence: 1.0
"""
        ),
        source="user",
        require_single=True,
    )
    return SaveRuleProvider((*builtin, *user), resolver)
