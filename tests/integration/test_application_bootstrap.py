from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Event
from threading import enumerate as enumerate_threads
from urllib.request import urlopen

import pytest

from gameshelf.bootstrap.application import build_application
from gameshelf.bootstrap.paths import AppPaths
from gameshelf.bootstrap.resources import ResourcePaths
from gameshelf.bridge.tasks import TaskContext
from gameshelf.engines.rule_schema import RuleSchemaError


def test_application_bootstrap_creates_only_portable_state(tmp_path: Path) -> None:
    paths = AppPaths.from_root(tmp_path / "便携应用")

    application = build_application(paths)
    try:
        bootstrap = application.api.bootstrap()
        assert bootstrap["ok"] is True
        assert bootstrap["data"]["appName"] == "GameShelf"
        assert bootstrap["data"]["schemaVersion"] == 2
        assert application.schema_version == 2
        assert bootstrap["data"]["uiScale"] == 1.0
        assert isinstance(bootstrap["data"]["assetSessionToken"], str)
        assert paths.config_file.exists()
        assert paths.database_file.exists()
        assert paths.logs_dir.joinpath("gameshelf.log").exists()
        assert application.guided_saves.current() is None
        assert application.api.current_guided_save_detection() == {
            "ok": True,
            "data": None,
        }
        assert all(
            path == paths.data_dir or paths.data_dir in path.parents
            for path in paths.owned_paths()
        )
    finally:
        application.close()
        application.close()


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
    rules_file = resource_root / "rules" / "engines.yaml"
    rules_file.parent.mkdir()
    rules_file.write_text(
        """\
version: test
rules:
  - id: injected_engine
    label: Injected Engine
    all:
      - op: path_exists
        path: injected.marker
        weight: 1.0
""",
        encoding="utf-8",
    )
    resources = ResourcePaths(
        root=resource_root,
        ui_dir=ui_dir,
        engine_rules_file=rules_file,
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
    rules_file = resource_root / "rules" / "engines.yaml"
    rules_file.parent.mkdir()
    rules_file.write_text(rules_content, encoding="utf-8")
    resources = ResourcePaths(
        root=resource_root,
        ui_dir=ui_dir,
        engine_rules_file=rules_file,
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
        engine_rules_file=resource_root / "rules" / "missing.yaml",
        ludusavi_dir=resource_root / "missing-ludusavi",
    )
    paths = AppPaths.from_root(tmp_path / "便携应用")

    with pytest.raises(RuleSchemaError, match="Cannot read engine rules"):
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
