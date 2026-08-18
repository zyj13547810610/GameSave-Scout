"""One bounded analysis executor shared by every library scan."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Condition
from typing import TypeVar

from gameshelf.bridge.tasks import TaskContext

T = TypeVar("T")
R = TypeVar("R")


class ScanAnalysisPool:
    def __init__(self, limit_provider: Callable[[], int]) -> None:
        self._limit_provider = limit_provider
        self._executor = ThreadPoolExecutor(
            max_workers=4,
            thread_name_prefix="gameshelf-scan-analysis",
        )
        self._condition = Condition()
        self._active = 0
        self._closed = False

    def map_ordered(
        self,
        items: Sequence[T],
        worker: Callable[[T], R],
        context: TaskContext,
    ) -> tuple[R, ...]:
        with self._condition:
            if self._closed:
                raise RuntimeError("扫描分析池已经关闭。")

        iterator = iter(items)
        pending: deque[Future[R]] = deque()
        results: list[R] = []
        exhausted = False
        try:
            while pending or not exhausted:
                while not exhausted and len(pending) < 4:
                    context.raise_if_cancelled()
                    try:
                        item = next(iterator)
                    except StopIteration:
                        exhausted = True
                        break
                    self._acquire_slot(context)
                    try:
                        future = self._executor.submit(
                            self._run_item,
                            item,
                            worker,
                            context,
                        )
                    except BaseException:
                        self._release_slot()
                        raise
                    future.add_done_callback(lambda _: self._release_slot())
                    pending.append(future)

                if pending:
                    results.append(pending.popleft().result())
                    context.raise_if_cancelled()
        except BaseException:
            for future in pending:
                future.cancel()
            raise
        return tuple(results)

    def close(self) -> None:
        with self._condition:
            if self._closed:
                return
            self._closed = True
            self._condition.notify_all()
        self._executor.shutdown(wait=True, cancel_futures=False)

    @staticmethod
    def _run_item(
        item: T,
        worker: Callable[[T], R],
        context: TaskContext,
    ) -> R:
        context.raise_if_cancelled()
        result = worker(item)
        context.raise_if_cancelled()
        return result

    def _acquire_slot(self, context: TaskContext) -> None:
        with self._condition:
            while True:
                context.raise_if_cancelled()
                if self._closed:
                    raise RuntimeError("扫描分析池已经关闭。")
                if self._active < self._limit():
                    self._active += 1
                    return
                self._condition.wait(timeout=0.1)

    def _release_slot(self) -> None:
        with self._condition:
            self._active -= 1
            self._condition.notify_all()

    def _limit(self) -> int:
        value = self._limit_provider()
        return value if type(value) is int and 1 <= value <= 4 else 1
