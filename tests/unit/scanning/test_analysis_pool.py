from collections.abc import Callable
from threading import Condition, Event, Lock, Thread
from time import sleep

import pytest

from gamesave_scout.bridge.tasks import TaskCancelled, TaskContext
from gamesave_scout.scanning.analysis_pool import ScanAnalysisPool


def _context(cancelled: Event | None = None) -> TaskContext:
    return TaskContext(cancelled or Event(), lambda *_: None)


class _Activity:
    def __init__(self) -> None:
        self.condition = Condition()
        self.active = 0
        self.maximum = 0

    def enter(self) -> None:
        with self.condition:
            self.active += 1
            self.maximum = max(self.maximum, self.active)
            self.condition.notify_all()

    def leave(self) -> None:
        with self.condition:
            self.active -= 1
            self.condition.notify_all()

    def wait_for(self, count: int) -> None:
        with self.condition:
            assert self.condition.wait_for(lambda: self.active >= count, timeout=2)


def _run_in_thread(operation: Callable[[], object]) -> tuple[Thread, list[object]]:
    outcome: list[object] = []

    def run() -> None:
        try:
            outcome.append(operation())
        except BaseException as error:
            outcome.append(error)

    thread = Thread(target=run)
    thread.start()
    return thread, outcome


@pytest.mark.parametrize("limit", [1, 2, 4])
def test_pool_obeys_limit_and_returns_input_order(limit: int) -> None:
    pool = ScanAnalysisPool(lambda: limit)
    activity = _Activity()
    release = Event()

    def worker(item: int) -> int:
        activity.enter()
        try:
            assert release.wait(timeout=2)
            return item * 10
        finally:
            activity.leave()

    thread, outcome = _run_in_thread(
        lambda: pool.map_ordered((3, 1, 2, 0), worker, _context())
    )
    activity.wait_for(limit)
    sleep(0.05)

    assert activity.maximum == limit
    release.set()
    thread.join(timeout=2)
    pool.close()

    assert not thread.is_alive()
    assert outcome == [(30, 10, 20, 0)]


def test_two_callers_share_one_global_limit() -> None:
    pool = ScanAnalysisPool(lambda: 2)
    activity = _Activity()
    release = Event()

    def worker(item: int) -> int:
        activity.enter()
        try:
            assert release.wait(timeout=2)
            return item
        finally:
            activity.leave()

    first, first_outcome = _run_in_thread(
        lambda: pool.map_ordered((1, 2, 3), worker, _context())
    )
    second, second_outcome = _run_in_thread(
        lambda: pool.map_ordered((4, 5, 6), worker, _context())
    )
    activity.wait_for(2)
    sleep(0.05)

    assert activity.maximum == 2
    release.set()
    first.join(timeout=2)
    second.join(timeout=2)
    pool.close()

    assert first_outcome == [(1, 2, 3)]
    assert second_outcome == [(4, 5, 6)]


def test_decreasing_limit_applies_before_the_next_worker_starts() -> None:
    limit = [2]
    pool = ScanAnalysisPool(lambda: limit[0])
    activity = _Activity()
    release_first = Event()
    release_later = Event()
    later_started = Event()
    later_maximum = [0]
    later_lock = Lock()

    def worker(item: int) -> int:
        activity.enter()
        try:
            if item < 2:
                assert release_first.wait(timeout=2)
            else:
                with later_lock:
                    later_maximum[0] = max(later_maximum[0], activity.active)
                later_started.set()
                assert release_later.wait(timeout=2)
            return item
        finally:
            activity.leave()

    thread, outcome = _run_in_thread(
        lambda: pool.map_ordered((0, 1, 2, 3), worker, _context())
    )
    activity.wait_for(2)
    limit[0] = 1
    release_first.set()
    assert later_started.wait(timeout=2)
    sleep(0.05)

    assert later_maximum[0] == 1
    release_later.set()
    thread.join(timeout=2)
    pool.close()

    assert outcome == [(0, 1, 2, 3)]


def test_cancellation_stops_before_submitting_the_next_item() -> None:
    pool = ScanAnalysisPool(lambda: 1)
    cancelled = Event()
    first_started = Event()
    release = Event()
    calls: list[int] = []

    def worker(item: int) -> int:
        calls.append(item)
        first_started.set()
        assert release.wait(timeout=2)
        return item

    thread, outcome = _run_in_thread(
        lambda: pool.map_ordered((1, 2, 3), worker, _context(cancelled))
    )
    assert first_started.wait(timeout=2)
    cancelled.set()
    release.set()
    thread.join(timeout=2)
    pool.close()

    assert calls == [1]
    assert len(outcome) == 1
    assert isinstance(outcome[0], TaskCancelled)


def test_close_waits_for_running_work_and_rejects_new_calls() -> None:
    pool = ScanAnalysisPool(lambda: 1)
    started = Event()
    release = Event()

    def worker(item: int) -> int:
        started.set()
        assert release.wait(timeout=2)
        return item

    mapping, outcome = _run_in_thread(
        lambda: pool.map_ordered((1,), worker, _context())
    )
    assert started.wait(timeout=2)
    closed = Event()

    def close() -> None:
        pool.close()
        closed.set()

    closing = Thread(target=close)
    closing.start()
    sleep(0.05)
    assert not closed.is_set()
    release.set()
    mapping.join(timeout=2)
    closing.join(timeout=2)

    assert outcome == [(1,)]
    assert closed.is_set()
    with pytest.raises(RuntimeError, match="关闭"):
        pool.map_ordered((2,), worker, _context())
