"""Narrow pywebview API exposed to the Vue frontend."""

from __future__ import annotations

from typing import cast

from gameshelf.bootstrap.paths import AppPaths
from gameshelf.bridge.contracts import ApiResult, JSONValue, failure, success
from gameshelf.bridge.tasks import TaskRegistry, TaskSnapshot


class BridgeApi:
    def __init__(self, paths: AppPaths, tasks: TaskRegistry, *, schema_version: int) -> None:
        self._paths = paths
        self._tasks = tasks
        self._schema_version = schema_version

    def bootstrap(self) -> ApiResult:
        return success(
            {
                "appName": "GameShelf",
                "schemaVersion": self._schema_version,
                "portable": True,
            }
        )

    def task_snapshot(self, task_id: str) -> ApiResult:
        try:
            snapshot = self._tasks.get_snapshot(task_id)
        except KeyError:
            return failure("task_not_found", "没有找到对应的后台任务。")
        return success(self._snapshot_data(snapshot))

    def cancel_task(self, task_id: str) -> ApiResult:
        try:
            self._tasks.get_snapshot(task_id)
        except KeyError:
            return failure("task_not_found", "没有找到对应的后台任务。")
        return success({"cancelled": self._tasks.cancel(task_id)})

    @staticmethod
    def _snapshot_data(snapshot: TaskSnapshot) -> dict[str, JSONValue]:
        return {
            "id": snapshot.id,
            "kind": snapshot.kind,
            "status": snapshot.status,
            "progress": cast(dict[str, JSONValue], snapshot.progress),
            "message": snapshot.message,
            "result": cast(JSONValue, snapshot.result),
            "error": cast(JSONValue, snapshot.error),
        }
