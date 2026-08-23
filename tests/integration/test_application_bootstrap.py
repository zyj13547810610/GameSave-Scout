from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Event
from threading import enumerate as enumerate_threads
from types import MappingProxyType
from urllib.request import urlopen

import pytest

from gameshelf.bootstrap.application import build_application
from gameshelf.bootstrap.paths import AppPaths
from gameshelf.bootstrap.resources import ResourcePaths
from gameshelf.bridge.tasks import TaskContext
from gameshelf.engines.rule_schema import RuleSchemaError
from gameshelf.saves.batch_rules import BatchRuleCatalog
from gameshelf.saves.builtin_rules import SaveRuleProvider
from gameshelf.saves.ludusavi_provider import LudusaviProvider
from gameshelf.saves.rule_schema import SaveRuleSchemaError


def test_application_bootstrap_creates_only_portable_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = AppPaths.from_root(tmp_path / "便携应用")

    def unexpected_rule_execution(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("应用启动不应执行存档规则或初始化 Ludusavi 快照")

    monkeypatch.setattr(
        LudusaviProvider,
        "ensure_initial_snapshot",
        unexpected_rule_execution,
    )
    monkeypatch.setattr(
        SaveRuleProvider,
        "suggest_game_specific",
        unexpected_rule_execution,
    )
    monkeypatch.setattr(
        SaveRuleProvider,
        "suggest_engine",
        unexpected_rule_execution,
    )

    application = build_application(paths)
    try:
        bootstrap = application.api.bootstrap()
        assert bootstrap["ok"] is True
        assert bootstrap["data"]["appName"] == "GameShelf"
        assert bootstrap["data"]["schemaVersion"] == 4
        assert application.schema_version == 4
        assert bootstrap["data"]["uiScale"] == 1.0
        assert isinstance(bootstrap["data"]["assetSessionToken"], str)
        assert paths.config_file.exists()
        assert paths.database_file.exists()
        assert paths.user_engine_rules_dir.is_dir()
        assert paths.user_save_rules_dir.is_dir()
        assert not paths.rule_settings_file.exists()
        assert not paths.legacy_manifests_dir.exists()
        assert paths.logs_dir.joinpath("gameshelf.log").exists()
        snapshot = application.rule_catalog.snapshot()
        assert snapshot.generation == 1
        assert snapshot.catalog_version
        assert application.builtin_save_rules is snapshot.save_rules
        assert application.guided_saves.current() is None
        assert application.api.current_guided_save_detection() == {
            "ok": True,
            "data": None,
        }
        assert application.api.current_batch_save_task() == {
            "ok": True,
            "data": None,
        }
        assert application.api.list_batch_save_candidates(
            {"offset": 0, "limit": 20}
        ) == {
            "ok": True,
            "data": {"items": [], "total": 0},
        }
        application.writer.submit(
            lambda connection: connection.execute(
                """
                INSERT INTO games(id, title, status, added_at, updated_at)
                VALUES ('game-1', 'Game', 'save_only', 'now', 'now')
                """
            ).rowcount
        ).result()
        created_group = application.api.create_game_group({"name": "RPG"})
        group_id = created_group["data"]["id"]
        assigned = application.api.set_game_groups(
            {"gameId": "game-1", "groupIds": [group_id]}
        )
        listed_groups = application.api.list_game_groups()
        assert assigned["data"]["groupIds"] == [group_id]
        assert listed_groups["data"][0]["gameCount"] == 1
        assert all(
            path == paths.data_dir or paths.data_dir in path.parents
            for path in paths.owned_paths()
        )
    finally:
        application.close()
        application.close()


def test_application_recovers_interrupted_batch_save_session(tmp_path: Path) -> None:
    paths = AppPaths.from_root(tmp_path / "便携应用")
    first = build_application(paths)
    first.writer.submit(
        lambda connection: connection.execute(
            """
            INSERT INTO scan_sessions(
                id, root_id, kind, status, started_at,
                scope_json, counts_json, rules_version
            ) VALUES (
                'batch-session-1', NULL, 'save_discovery', 'running', 'now',
                '{}', '{}', 'test'
            )
            """
        ).rowcount
    ).result()
    first.close()

    second = build_application(paths)
    try:
        with second.database.connect(readonly=True) as connection:
            row = connection.execute(
                "SELECT status FROM scan_sessions WHERE id = 'batch-session-1'"
            ).fetchone()

        assert row is not None
        assert row["status"] == "interrupted"
    finally:
        second.close()


class _EmptyBatchRules:
    def collect(self, _context: object) -> BatchRuleCatalog:
        return BatchRuleCatalog(
            candidates=(),
            identities_by_path=MappingProxyType({}),
            reverse_path_rules=(),
            warnings=(),
            rules_version="shutdown-test",
        )


class _BlockingBatchScanner:
    def __init__(self) -> None:
        self.entered = Event()

    def scan(self, _scopes: object, _catalog: object, context: TaskContext) -> None:
        self.entered.set()
        while True:
            context.raise_if_cancelled()
            self.entered.wait(0.01)


def test_application_close_interrupts_active_batch_scan_before_writer_close(
    tmp_path: Path,
) -> None:
    application = build_application(AppPaths.from_root(tmp_path / "便携应用"))
    scanner = _BlockingBatchScanner()
    batch_saves = application.api._batch_saves
    assert batch_saves is not None
    batch_saves._rule_provider = _EmptyBatchRules()
    batch_saves._scanner = scanner

    started = application.api.start_batch_save_scan(
        {"standardScopeIds": ["documents"], "customRootIds": []}
    )
    assert started["ok"] is True
    assert scanner.entered.wait(2)

    application.close()

    with application.database.connect(readonly=True) as connection:
        row = connection.execute(
            """
            SELECT status FROM scan_sessions
            WHERE kind = 'save_discovery'
            ORDER BY rowid DESC LIMIT 1
            """
        ).fetchone()
    assert row is not None
    assert row["status"] == "interrupted"


def test_application_close_releases_its_logging_handler(tmp_path: Path) -> None:
    application = build_application(AppPaths.from_root(tmp_path / "便携应用"))
    logger = application.logger

    application.close()

    assert logger.propagate is True
    assert not any(isinstance(handler, RotatingFileHandler) for handler in logger.handlers)


def test_application_close_releases_scan_analysis_threads(tmp_path: Path) -> None:
    application = build_application(AppPaths.from_root(tmp_path / "便携应用"))
    context = TaskContext(Event(), lambda *_: None)

    assert application.analysis_pool.map_ordered((1, 2), lambda value: value, context) == (
        1,
        2,
    )
    assert any(
        thread.name.startswith("gameshelf-scan-analysis")
        for thread in enumerate_threads()
    )

    application.close()

    assert not any(
        thread.name.startswith("gameshelf-scan-analysis")
        for thread in enumerate_threads()
    )


def test_application_uses_injected_resource_paths(tmp_path: Path) -> None:
    resource_root = tmp_path / "injected-resources"
    ui_dir = resource_root / "ui"
    ui_dir.mkdir(parents=True)
    ui_marker = "injected portable UI"
    (ui_dir / "index.html").write_text(ui_marker, encoding="utf-8")
    rules_file = resource_root / "rules" / "builtin" / "engines.yaml"
    rules_file.parent.mkdir(parents=True)
    rules_file.write_text(
        """\
version: test
rules:
  - id: injected_engine
    label: Injected Engine
    references: [https://example.com/injected-engine]
    all:
      - op: path_exists
        path: injected.marker
        weight: 1.0
""",
        encoding="utf-8",
    )
    save_rules_file = resource_root / "rules" / "builtin" / "saves.yaml"
    save_rules_file.write_text("version: test\nrules: []\n", encoding="utf-8")
    resources = ResourcePaths(
        root=resource_root,
        ui_dir=ui_dir,
        builtin_engine_rules_file=rules_file,
        builtin_save_rules_file=save_rules_file,
        rule_schemas_dir=resource_root / "rules" / "schemas",
        ludusavi_dir=resource_root / "missing-ludusavi",
    )

    application = build_application(
        AppPaths.from_root(tmp_path / "便携应用"),
        resources=resources,
    )
    try:
        engine_options = application.api.list_engine_options()
        with urlopen(application.asset_address.ui_url) as response:
            served_ui = response.read().decode("utf-8")

        assert engine_options["ok"] is True
        assert any(
            item["id"] == "injected_engine" for item in engine_options["data"]
        )
        assert served_ui == ui_marker
        assert application.api.ludusavi_status()["data"]["available"] is False
    finally:
        application.close()


@pytest.mark.parametrize(
    "rules_content",
    (
        "version: [",
        "version: test\nrules: not-a-list\n",
    ),
)
def test_application_degrades_to_builtin_detectors_for_invalid_rules(
    tmp_path: Path,
    rules_content: str,
) -> None:
    resource_root = tmp_path / "resources"
    ui_dir = resource_root / "ui"
    ui_dir.mkdir(parents=True)
    (ui_dir / "index.html").write_text("test ui", encoding="utf-8")
    rules_file = resource_root / "rules" / "builtin" / "engines.yaml"
    rules_file.parent.mkdir(parents=True)
    rules_file.write_text(rules_content, encoding="utf-8")
    save_rules_file = resource_root / "rules" / "builtin" / "saves.yaml"
    save_rules_file.write_text("version: test\nrules: []\n", encoding="utf-8")
    resources = ResourcePaths(
        root=resource_root,
        ui_dir=ui_dir,
        builtin_engine_rules_file=rules_file,
        builtin_save_rules_file=save_rules_file,
        rule_schemas_dir=resource_root / "rules" / "schemas",
        ludusavi_dir=resource_root / "missing-ludusavi",
    )
    paths = AppPaths.from_root(tmp_path / "便携应用")

    application = build_application(paths, resources=resources)
    try:
        option_ids = {
            item["id"] for item in application.api.list_engine_options()["data"]
        }
        log_text = paths.logs_dir.joinpath("gameshelf.log").read_text(
            encoding="utf-8"
        )

        assert application.api.bootstrap()["ok"] is True
        assert "unity" in option_ids
        assert "声明式引擎规则加载失败" in log_text
        assert str(rules_file) in log_text
    finally:
        application.close()


def test_application_rejects_missing_engine_rules_before_database_start(
    tmp_path: Path,
) -> None:
    resource_root = tmp_path / "resources"
    ui_dir = resource_root / "ui"
    ui_dir.mkdir(parents=True)
    (ui_dir / "index.html").write_text("test ui", encoding="utf-8")
    resources = ResourcePaths(
        root=resource_root,
        ui_dir=ui_dir,
        builtin_engine_rules_file=resource_root / "rules" / "missing.yaml",
        builtin_save_rules_file=resource_root / "rules" / "builtin" / "saves.yaml",
        rule_schemas_dir=resource_root / "rules" / "schemas",
        ludusavi_dir=resource_root / "missing-ludusavi",
    )
    paths = AppPaths.from_root(tmp_path / "便携应用")

    with pytest.raises(RuleSchemaError, match="Cannot read engine rules"):
        build_application(paths, resources=resources)

    assert not paths.database_file.exists()


@pytest.mark.parametrize(
    "rules_content",
    (
        "version: [",
        "version: test\nrules: not-a-list\n",
    ),
)
def test_application_disables_only_invalid_builtin_save_rules(
    tmp_path: Path,
    rules_content: str,
) -> None:
    resource_root = tmp_path / "resources"
    ui_dir = resource_root / "ui"
    ui_dir.mkdir(parents=True)
    (ui_dir / "index.html").write_text("test ui", encoding="utf-8")
    rules_dir = resource_root / "rules" / "builtin"
    rules_dir.mkdir(parents=True)
    engine_rules_file = rules_dir / "engines.yaml"
    engine_rules_file.write_text("version: test\nrules: []\n", encoding="utf-8")
    save_rules_file = rules_dir / "saves.yaml"
    save_rules_file.write_text(rules_content, encoding="utf-8")
    resources = ResourcePaths(
        root=resource_root,
        ui_dir=ui_dir,
        builtin_engine_rules_file=engine_rules_file,
        builtin_save_rules_file=save_rules_file,
        rule_schemas_dir=resource_root / "rules" / "schemas",
        ludusavi_dir=resource_root / "missing-ludusavi",
    )
    paths = AppPaths.from_root(tmp_path / "便携应用")

    application = build_application(paths, resources=resources)
    try:
        log_text = paths.logs_dir.joinpath("gameshelf.log").read_text(
            encoding="utf-8"
        )

        assert application.api.bootstrap()["ok"] is True
        assert application.builtin_save_rules.rules_version is None
        assert "内置存档规则加载失败" in log_text
        assert str(save_rules_file) in log_text
    finally:
        application.close()


def test_rule_catalog_refresh_does_not_trigger_library_analysis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = build_application(AppPaths.from_root(tmp_path / "便携应用"))
    scanner = application.api._scanner
    assert scanner is not None

    def unexpected_analysis(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("刷新规则不应触发游戏扫描或重新检测")

    monkeypatch.setattr(scanner, "scan_root", unexpected_analysis)
    monkeypatch.setattr(scanner, "reanalyze_game", unexpected_analysis)
    rule_file = application.paths.user_engine_rules_dir / "refresh_test.yaml"
    rule_file.write_text(
        """\
version: test
rules:
  - id: refresh_test
    label: 刷新测试引擎
    type: engine
    all:
      - op: path_exists
        path: marker.dat
        weight: 1.0
""",
        encoding="utf-8",
    )
    try:
        result = application.rule_catalog.refresh()
        options = application.api.list_engine_options()

        assert result.applied is True
        assert any(item["id"] == "refresh_test" for item in options["data"])
    finally:
        application.close()


def test_application_rejects_missing_save_rules_before_database_start(
    tmp_path: Path,
) -> None:
    resource_root = tmp_path / "resources"
    ui_dir = resource_root / "ui"
    ui_dir.mkdir(parents=True)
    (ui_dir / "index.html").write_text("test ui", encoding="utf-8")
    rules_dir = resource_root / "rules" / "builtin"
    rules_dir.mkdir(parents=True)
    engine_rules_file = rules_dir / "engines.yaml"
    engine_rules_file.write_text("version: test\nrules: []\n", encoding="utf-8")
    resources = ResourcePaths(
        root=resource_root,
        ui_dir=ui_dir,
        builtin_engine_rules_file=engine_rules_file,
        builtin_save_rules_file=rules_dir / "missing-saves.yaml",
        rule_schemas_dir=resource_root / "rules" / "schemas",
        ludusavi_dir=resource_root / "missing-ludusavi",
    )
    paths = AppPaths.from_root(tmp_path / "便携应用")

    with pytest.raises(SaveRuleSchemaError, match="Cannot read save rules"):
        build_application(paths, resources=resources)

    assert not paths.database_file.exists()


def test_application_closes_guided_session_before_shared_writer(
    tmp_path: Path, monkeypatch
) -> None:
    application = build_application(AppPaths.from_root(tmp_path / "便携应用"))
    order: list[str] = []
    original_guided_close = application.guided_saves.close
    original_tasks_close = application.tasks.close
    original_analysis_close = application.analysis_pool.close
    original_wizard_close = application.cover_wizard.close_all
    original_assets_stop = application.asset_server.stop
    original_writer_close = application.writer.close

    def close_guided() -> None:
        order.append("guided")
        original_guided_close()

    def close_writer(timeout: float = 5.0) -> None:
        order.append("writer")
        original_writer_close(timeout)

    def close_tasks() -> None:
        order.append("tasks")
        original_tasks_close()

    def close_analysis() -> None:
        order.append("analysis")
        original_analysis_close()

    def close_wizard() -> None:
        order.append("wizard")
        original_wizard_close()

    def stop_assets() -> None:
        order.append("assets")
        original_assets_stop()

    monkeypatch.setattr(application.guided_saves, "close", close_guided)
    monkeypatch.setattr(application.tasks, "close", close_tasks)
    monkeypatch.setattr(application.analysis_pool, "close", close_analysis)
    monkeypatch.setattr(application.cover_wizard, "close_all", close_wizard)
    monkeypatch.setattr(application.asset_server, "stop", stop_assets)
    monkeypatch.setattr(application.writer, "close", close_writer)

    application.close()
    application.close()

    assert order == ["guided", "tasks", "analysis", "wizard", "assets", "writer"]
