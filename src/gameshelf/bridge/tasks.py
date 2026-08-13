"""Thread-safe background task snapshots with cooperative cancellation."""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, replace
from threading import Event, RLock
from typing import Any, Literal
from uuid import uuid4

type TaskStatus = Literal["queued", "running", "completed", "cancelled", "failed"]
type TaskOperation = Callable[["TaskContext"], Any]


class TaskCancelled(RuntimeError):
    """Internal control flow for cooperative task cancellation."""


@dataclass(frozen=True)
class TaskSnapshot:
    id: str
    kind: str
    status: TaskStatus
    progress: dict[str, int | None]
    message: str
    result: Any = None
    error: dict[str, str] | None = None


class TaskContext:
    def __init__(
        self,
        cancel_event: Event,
        reporter: Callable[[int, int | None, str], None],
    ) -> None:
        self._cancel_event = cancel_event
        self._reporter = reporter

    def report(self, completed: int, total: int | None, message: str) -> None:
        if completed < 0 or (total is not None and (total < 0 or completed > total)):
            raise ValueError("任务进度数值无效。")
        self._reporter(completed, total, message)

    def raise_if_cancelled(self) -> None:
        if self._cancel_event.is_set():
            raise TaskCancelled("任务已取消。")


class TaskRegistry:
    def __init__(
        self,
        *,
        max_workers: int = 2,
        logger: logging.Logger | None = None,
    ) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="gameshelf-task"
        )
        self._lock = RLock()
        self._snapshots: dict[str, TaskSnapshot] = {}
        self._cancel_events: dict[str, Event] = {}
        self._workers: dict[str, Future[None]] = {}
        self._closed = False
        self._logger = logger or logging.getLogger(__name__)

    def submit(self, kind: str, operation: TaskOperation) -> str:
        task_id = str(uuid4())
        cancel_event = Event()
        with self._lock:
            if self._closed:
                raise RuntimeError("后台任务注册表已经关闭。")
            self._snapshots[task_id] = TaskSnapshot(
                id=task_id,
                kind=kind,
                status="queued",
                progress={"completed": 0, "total": None},
                message="",
            )
            self._cancel_events[task_id] = cancel_event
            worker = self._executor.submit(self._run, task_id, operation, cancel_event)
            self._workers[task_id] = worker
        return task_id

    def get_snapshot(self, task_id: str) -> TaskSnapshot:
        with self._lock:
            snapshot = self._snapshots.get(task_id)
            if snapshot is None:
                raise KeyError(task_id)
            return snapshot

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
            cancel_event.set()
            return True

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for task_id, snapshot in self._snapshots.items():
                if snapshot.status in {"queued", "running"}:
                    self._cancel_events[task_id].set()
        self._executor.shutdown(wait=True, cancel_futures=False)

    def _run(self, task_id: str, operation: TaskOperation, cancel_event: Event) -> None:
        self._update(task_id, status="running")
        context = TaskContext(
            cancel_event,
            lambda completed, total, message: self._report(
                task_id, completed, total, message
            ),
        )
        try:
            context.raise_if_cancelled()
            result = operation(context)
            context.raise_if_cancelled()
        except TaskCancelled:
            self._update(task_id, status="cancelled", message="任务已取消。")
        except Exception:
            self._logger.exception(
                "Background task %s (%s) failed",
                task_id,
                self._snapshots[task_id].kind,
            )
            message = "任务执行失败，请查看 data/logs/gameshelf.log。"
            self._update(
                task_id,
                status="failed",
                message=message,
                error={"code": "task_failed", "message": message},
            )
        else:
            self._update(task_id, status="completed", result=result)

    def _report(self, task_id: str, completed: int, total: int | None, message: str) -> None:
        self._update(
            task_id,
            progress={"completed": completed, "total": total},
            message=message,
        )

    def _update(self, task_id: str, **changes: Any) -> None:
        with self._lock:
            self._snapshots[task_id] = replace(self._snapshots[task_id], **changes)
