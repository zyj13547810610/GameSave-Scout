from pathlib import Path

from gameshelf.bootstrap.paths import AppPaths
from gameshelf.bridge.api import BridgeApi
from gameshelf.bridge.tasks import TaskRegistry


def test_bootstrap_returns_json_safe_success(tmp_path: Path) -> None:
    api, tasks = _api(tmp_path)
    try:
        assert api.bootstrap() == {
            "ok": True,
            "data": {"appName": "GameShelf", "schemaVersion": 1, "portable": True},
        }
    finally:
        tasks.close()


def test_unknown_task_returns_stable_error(tmp_path: Path) -> None:
    api, tasks = _api(tmp_path)
    try:
        result = api.task_snapshot("not-a-uuid")
        assert result["ok"] is False
        assert result["error"]["code"] == "task_not_found"
    finally:
        tasks.close()


def test_task_snapshot_uses_camel_case_json_fields(tmp_path: Path) -> None:
    api, tasks = _api(tmp_path)
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
            "result": {"answer": 42},
            "error": None,
        }
    finally:
        tasks.close()


def _api(tmp_path: Path) -> tuple[BridgeApi, TaskRegistry]:
    paths = AppPaths.from_root(tmp_path / "portable")
    tasks = TaskRegistry(max_workers=1)
    return BridgeApi(paths, tasks, schema_version=1), tasks
