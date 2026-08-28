from pathlib import Path

from gamesave_scout.bootstrap.config import ConfigService, JsonConfigStore
from gamesave_scout.bootstrap.paths import AppPaths
from gamesave_scout.bridge.api import BridgeApi
from gamesave_scout.bridge.tasks import TaskRegistry


def test_bootstrap_returns_json_safe_success(tmp_path: Path) -> None:
    api, tasks, _ = _api(tmp_path)
    try:
        assert api.bootstrap() == {
            "ok": True,
            "data": {
                "appName": "GameSave Scout",
                "schemaVersion": 1,
                "portable": True,
                "uiScale": 1.0,
                "libraryScanSettings": {
                    "startupQuickScan": True,
                    "scanConcurrency": 1,
                },
                "coverWizardSettings": {
                    "coverOnlineEnabled": False,
                    "coverVndbCandidateLimit": 5,
                    "coverLocalScanCandidateLimit": 10,
                    "coverOptimizeEnabled": True,
                    "coverLocalScanDepth": 2,
                },
                "batchSaveSettings": {"customRoots": []},
            },
        }
    finally:
        tasks.close()


def test_unknown_task_returns_stable_error(tmp_path: Path) -> None:
    api, tasks, _ = _api(tmp_path)
    try:
        result = api.task_snapshot("not-a-uuid")
        assert result["ok"] is False
        assert result["error"]["code"] == "task_not_found"
    finally:
        tasks.close()


def test_task_snapshot_uses_camel_case_json_fields(tmp_path: Path) -> None:
    api, tasks, _ = _api(tmp_path)
    try:
        task_id = tasks.submit("example", lambda context: {"answer": 42})
        tasks.wait(task_id, timeout=2)

        result = api.task_snapshot(task_id)

        assert result["ok"] is True
        assert result["data"] == {
            "id": task_id,
            "kind": "example",
            "status": "completed",
                "progress": {"completed": 0, "total": None},
                "message": "",
                "details": {},
                "result": {"answer": 42},
            "error": None,
        }
    finally:
        tasks.close()


def test_set_ui_scale_persists_a_valid_value(tmp_path: Path) -> None:
    api, tasks, config = _api(tmp_path)
    try:
        result = api.set_ui_scale({"uiScale": 0.8})

        assert result == {"ok": True, "data": {"uiScale": 0.8}}
        assert config.current.ui_scale == 0.8
    finally:
        tasks.close()


def test_set_ui_scale_rejects_values_outside_the_supported_options(tmp_path: Path) -> None:
    api, tasks, config = _api(tmp_path)
    try:
        result = api.set_ui_scale({"uiScale": 0.95})

        assert result["ok"] is False
        assert result["error"]["code"] == "invalid_ui_scale"
        assert config.current.ui_scale == 1.0
    finally:
        tasks.close()


def test_set_ui_scale_reports_an_atomic_save_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    api, tasks, config = _api(tmp_path)

    def fail_save(ui_scale: object) -> None:
        raise OSError("read only")

    monkeypatch.setattr(config, "set_ui_scale", fail_save)
    try:
        result = api.set_ui_scale({"uiScale": 0.8})

        assert result["ok"] is False
        assert result["error"]["code"] == "config_save_failed"
    finally:
        tasks.close()


def test_set_library_scan_settings_persists_both_values(tmp_path: Path) -> None:
    api, tasks, config = _api(tmp_path)
    try:
        result = api.set_library_scan_settings(
            {"startupQuickScan": False, "scanConcurrency": 3}
        )

        assert result == {
            "ok": True,
            "data": {"startupQuickScan": False, "scanConcurrency": 3},
        }
        assert config.current.startup_quick_scan is False
        assert config.current.scan_concurrency == 3
    finally:
        tasks.close()


def test_set_library_scan_settings_rejects_an_incomplete_or_extra_payload(
    tmp_path: Path,
) -> None:
    api, tasks, config = _api(tmp_path)
    try:
        missing = api.set_library_scan_settings({"startupQuickScan": False})
        extra = api.set_library_scan_settings(
            {"startupQuickScan": False, "scanConcurrency": 2, "other": True}
        )

        assert missing["ok"] is False
        assert missing["error"]["code"] == "invalid_request"
        assert extra["ok"] is False
        assert extra["error"]["code"] == "invalid_request"
        assert config.current.scan_concurrency == 1
    finally:
        tasks.close()


def test_set_library_scan_settings_rejects_out_of_range_concurrency(
    tmp_path: Path,
) -> None:
    api, tasks, config = _api(tmp_path)
    try:
        result = api.set_library_scan_settings(
            {"startupQuickScan": True, "scanConcurrency": 5}
        )

        assert result["ok"] is False
        assert result["error"]["code"] == "invalid_library_scan_settings"
        assert config.current.scan_concurrency == 1
    finally:
        tasks.close()


def test_set_library_scan_settings_reports_an_atomic_save_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    api, tasks, config = _api(tmp_path)

    def fail_save(*, startup_quick_scan: object, scan_concurrency: object) -> None:
        raise OSError("read only")

    monkeypatch.setattr(config, "set_library_scan_settings", fail_save)
    try:
        result = api.set_library_scan_settings(
            {"startupQuickScan": False, "scanConcurrency": 4}
        )

        assert result["ok"] is False
        assert result["error"]["code"] == "config_save_failed"
    finally:
        tasks.close()


def test_set_cover_wizard_settings_persists_valid_values(tmp_path: Path) -> None:
    api, tasks, config = _api(tmp_path)
    try:
        result = api.set_cover_wizard_settings(
            {
                "coverOnlineEnabled": True,
                "coverVndbCandidateLimit": 8,
                "coverLocalScanCandidateLimit": 25,
                "coverOptimizeEnabled": False,
                "coverLocalScanDepth": 3,
            }
        )

        assert result == {
            "ok": True,
            "data": {
                "coverOnlineEnabled": True,
                "coverVndbCandidateLimit": 8,
                "coverLocalScanCandidateLimit": 25,
                "coverOptimizeEnabled": False,
                "coverLocalScanDepth": 3,
            },
        }
        assert config.current.ui_scale == 1.0
        assert config.current.cover_online_enabled is True
        assert config.current.cover_optimize_enabled is False
        assert config.current.cover_local_scan_depth == 3
    finally:
        tasks.close()


def test_set_cover_wizard_settings_rejects_out_of_range_values(tmp_path: Path) -> None:
    api, tasks, config = _api(tmp_path)
    try:
        result = api.set_cover_wizard_settings(
            {
                "coverOnlineEnabled": False,
                "coverVndbCandidateLimit": 21,
                "coverLocalScanCandidateLimit": 10,
                "coverOptimizeEnabled": True,
                "coverLocalScanDepth": 2,
            }
        )

        assert result["ok"] is False
        assert result["error"]["code"] == "invalid_cover_wizard_settings"
        assert config.current.cover_vndb_candidate_limit == 5
    finally:
        tasks.close()


def _api(tmp_path: Path) -> tuple[BridgeApi, TaskRegistry, ConfigService]:
    paths = AppPaths.from_root(tmp_path / "portable")
    tasks = TaskRegistry(max_workers=1)
    config = ConfigService(JsonConfigStore(paths.config_file))
    return BridgeApi(paths, tasks, schema_version=1, config=config), tasks, config
