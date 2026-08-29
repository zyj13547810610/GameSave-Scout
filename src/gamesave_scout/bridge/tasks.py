"""Thread-safe background task snapshots with cooperative cancellation."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from threading import Event, RLock
from typing import Any, Literal
from uuid import uuid4

type TaskStatus = Literal["queued", "running", "completed", "cancelled", "failed"]
type TaskCancelReason = Literal["user", "shutdown"]
type TaskOperation = Callable[["TaskContext"], Any]
type TaskDetailValue = str | int | float | bool | None
type TaskDetails = dict[str, TaskDetailValue]


class TaskCancelled(RuntimeError):
    """Internal control flow for cooperative task cancellation."""

    def __init__(self, reason: TaskCancelReason) -> None:
        super().__init__("任务已取消。")
        self.reason = reason


class TaskFailure(RuntimeError):
    """A deliberately user-safe background-task failure."""

    def __init__(self, code: str, message: str) -> None:
        if not code.strip() or not message.strip():
            raise ValueError("任务失败代码和消息不能为空。")
        super().__init__(message)
        self.code = code
        self.message = message


class ActiveTaskConflict(RuntimeError):
    """Raised when an active task owns an incompatible resource group."""

    def __init__(self, group: str) -> None:
        super().__init__(f"互斥任务组正在使用中：{group}")
        self.group = group


@dataclass(frozen=True)
class TaskSnapshot:
    id: str
    kind: str
    status: TaskStatus
    progress: dict[str, int | None]
    message: str
    details: TaskDetails = field(default_factory=dict)
    result: Any = None
    error: dict[str, str] | None = None


class TaskContext:
    def __init__(
        self,
        cancel_event: Event,
        reporter: Callable[[int, int | None, str, TaskDetails], None],
        cancel_reason: Callable[[], TaskCancelReason | None] | None = None,
    ) -> None:
        self._cancel_event = cancel_event
        self._cancel_reason = cancel_reason or (lambda: None)
        self._reporter = reporter

    def report(
        self,
        completed: int,
        total: int | None,
        message: str,
        *,
        details: Mapping[str, TaskDetailValue] | None = None,
    ) -> None:
        if completed < 0 or (total is not None and (total < 0 or completed > total)):
            raise ValueError("任务进度数值无效。")
        self._reporter(completed, total, message, dict(details or {}))

    def raise_if_cancelled(self) -> None:
        if self._cancel_event.is_set():
            raise TaskCancelled(self._cancel_reason() or "user")


class TaskRegistry:
    def __init__(
        self,
        *,
        max_workers: int = 2,
        logger: logging.Logger | None = None,
    ) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="gamesave-scout-task"
        )
        self._lock = RLock()
        self._snapshots: dict[str, TaskSnapshot] = {}
        self._cancel_events: dict[str, Event] = {}
        self._cancel_reasons: dict[str, TaskCancelReason] = {}
        self._workers: dict[str, Future[None]] = {}
        self._active_exclusive_groups: dict[str, str] = {}
        self._task_exclusive_groups: dict[str, str] = {}
        self._active_shared_groups: dict[str, set[str]] = {}
        self._task_shared_groups: dict[str, str] = {}
        self._closed = False
        self._logger = logger or logging.getLogger(__name__)

    def submit(
        self,
        kind: str,
        operation: TaskOperation,
        exclusive_group: str | None = None,
        shared_group: str | None = None,
    ) -> str:
        normalized_exclusive_group = _normalize_group(exclusive_group, "互斥")
        normalized_shared_group = _normalize_group(shared_group, "共享")
        if normalized_exclusive_group is not None and normalized_shared_group is not None:
            raise ValueError("后台任务不能同时声明互斥任务组和共享任务组。")
        task_id = str(uuid4())
        cancel_event = Event()
        with self._lock:
            if self._closed:
                raise RuntimeError("后台任务注册表已经关闭。")
            if normalized_exclusive_group is not None and (
                normalized_exclusive_group in self._active_exclusive_groups
                or normalized_exclusive_group in self._active_shared_groups
            ):
                raise ActiveTaskConflict(normalized_exclusive_group)
            if (
                normalized_shared_group is not None
                and normalized_shared_group in self._active_exclusive_groups
            ):
                raise ActiveTaskConflict(normalized_shared_group)
            self._snapshots[task_id] = TaskSnapshot(
                id=task_id,
                kind=kind,
                status="queued",
                progress={"completed": 0, "total": None},
                message="",
            )
            self._cancel_events[task_id] = cancel_event
            if normalized_exclusive_group is not None:
                self._active_exclusive_groups[normalized_exclusive_group] = task_id
                self._task_exclusive_groups[task_id] = normalized_exclusive_group
            if normalized_shared_group is not None:
                self._active_shared_groups.setdefault(normalized_shared_group, set()).add(
                    task_id
                )
                self._task_shared_groups[task_id] = normalized_shared_group
            try:
                worker = self._executor.submit(
                    self._run,
                    task_id,
                    operation,
                    cancel_event,
                )
            except Exception:
                self._snapshots.pop(task_id, None)
                self._cancel_events.pop(task_id, None)
                self._release_resource_group(task_id)
                raise
            self._workers[task_id] = worker
        return task_id

    def get_snapshot(self, task_id: str) -> TaskSnapshot:
        with self._lock:
            snapshot = self._snapshots.get(task_id)
            if snapshot is None:
                raise KeyError(task_id)
            return _copy_snapshot(snapshot)

    def latest_snapshot(
        self,
        kind: str,
        *,
        active_only: bool = False,
    ) -> TaskSnapshot | None:
        with self._lock:
            for snapshot in reversed(tuple(self._snapshots.values())):
                if snapshot.kind != kind:
                    continue
                if active_only and snapshot.status not in {"queued", "running"}:
                    continue
                return _copy_snapshot(snapshot)
        return None

    def wait(self, task_id: str, *, timeout: float | None = None) -> TaskSnapshot:
        with self._lock:
            worker = self._workers.get(task_id)
            if worker is None:
                raise KeyError(task_id)
        worker.result(timeout=timeout)
        return self.get_snapshot(task_id)

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            snapshot = self._snapshots.get(task_id)
            cancel_event = self._cancel_events.get(task_id)
            if snapshot is None or cancel_event is None:
                return False
            if snapshot.status not in {"queued", "running"}:
                return False
            self._cancel_reasons[task_id] = "user"
            cancel_event.set()
            return True

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for task_id, snapshot in self._snapshots.items():
                if snapshot.status in {"queued", "running"}:
                    self._cancel_reasons.setdefault(task_id, "shutdown")
                    self._cancel_events[task_id].set()
        self._executor.shutdown(wait=True, cancel_futures=False)

    def _run(self, task_id: str, operation: TaskOperation, cancel_event: Event) -> None:
        self._update(task_id, status="running")
        context = TaskContext(
            cancel_event,
            lambda completed, total, message, details: self._report(
                task_id, completed, total, message, details
            ),
            cancel_reason=lambda: self._cancellation_reason(task_id),
        )
        try:
            context.raise_if_cancelled()
            result = operation(context)
            context.raise_if_cancelled()
        except TaskCancelled:
            self._update(task_id, status="cancelled", message="任务已取消。")
        except TaskFailure as error:
            self._logger.warning(
                "Background task %s (%s) reported %s: %s",
                task_id,
                self._snapshots[task_id].kind,
                error.code,
                error.message,
            )
            self._update(
                task_id,
                status="failed",
                message=error.message,
                error={"code": error.code, "message": error.message},
            )
        except Exception:
            self._logger.exception(
                "Background task %s (%s) failed",
                task_id,
                self._snapshots[task_id].kind,
            )
            message = "任务执行失败，请查看 data/logs/gamesave-scout.log。"
            self._update(
                task_id,
                status="failed",
                message=message,
                error={"code": "task_failed", "message": message},
            )
        else:
            self._update(task_id, status="completed", result=result)
        finally:
            self._release_resource_group(task_id)

    def _report(
        self,
        task_id: str,
        completed: int,
        total: int | None,
        message: str,
        details: TaskDetails,
    ) -> None:
        self._update(
            task_id,
            progress={"completed": completed, "total": total},
            message=message,
            details=details,
        )

    def _update(self, task_id: str, **changes: Any) -> None:
        with self._lock:
            self._snapshots[task_id] = replace(self._snapshots[task_id], **changes)

    def _cancellation_reason(self, task_id: str) -> TaskCancelReason | None:
        with self._lock:
            return self._cancel_reasons.get(task_id)

    def _release_resource_group(self, task_id: str) -> None:
        with self._lock:
            exclusive_group = self._task_exclusive_groups.pop(task_id, None)
            if (
                exclusive_group is not None
                and self._active_exclusive_groups.get(exclusive_group) == task_id
            ):
                self._active_exclusive_groups.pop(exclusive_group, None)
            shared_group = self._task_shared_groups.pop(task_id, None)
            if shared_group is not None:
                owners = self._active_shared_groups.get(shared_group)
                if owners is not None:
                    owners.discard(task_id)
                    if not owners:
                        self._active_shared_groups.pop(shared_group, None)


def _normalize_group(group: str | None, label: str) -> str | None:
    if group is None:
        return None
    if not isinstance(group, str) or not group.strip() or "\x00" in group:
        raise ValueError(f"{label}任务组必须是非空字符串。")
    return group.strip()


def _copy_snapshot(snapshot: TaskSnapshot) -> TaskSnapshot:
    return replace(
        snapshot,
        progress=dict(snapshot.progress),
        details=dict(snapshot.details),
        error=None if snapshot.error is None else dict(snapshot.error),
    )
