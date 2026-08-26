import logging
from threading import Event

import pytest

from gamesave_scout.bridge.tasks import (
    ActiveTaskConflict,
    TaskCancelled,
    TaskRegistry,
)


def test_task_reports_progress_and_result() -> None:
    registry = TaskRegistry(max_workers=1)

    def work(context: object) -> dict[str, int]:
        context.report(
            1,
            2,
            "一半",
            details={"stage": "discovering", "currentPath": "Alice"},
        )
        return {"answer": 42}

    task_id = registry.submit("example", work)
    snapshot = registry.wait(task_id, timeout=2)

    assert snapshot.status == "completed"
    assert snapshot.progress == {"completed": 1, "total": 2}
    assert snapshot.message == "一半"
    assert snapshot.details == {"stage": "discovering", "currentPath": "Alice"}
    assert snapshot.result == {"answer": 42}
    registry.close()


def test_task_can_be_cancelled_cooperatively() -> None:
    entered = Event()
    release = Event()

    def work(context: object) -> None:
        entered.set()
        release.wait(2)
        context.raise_if_cancelled()

    registry = TaskRegistry(max_workers=1)
    task_id = registry.submit("example", work)
    assert entered.wait(1)

    assert registry.cancel(task_id) is True
    release.set()
    assert registry.wait(task_id, timeout=2).status == "cancelled"
    registry.close()


def test_task_failure_isolated_as_user_safe_snapshot() -> None:
    registry = TaskRegistry(max_workers=1)

    def fail(context: object) -> None:
        raise RuntimeError("secret internal detail")

    task_id = registry.submit("example", fail)
    snapshot = registry.wait(task_id, timeout=2)

    assert snapshot.status == "failed"
    assert snapshot.error == {
        "code": "task_failed",
        "message": "任务执行失败，请查看 data/logs/gamesave-scout.log。",
    }
    assert "secret" not in str(snapshot)
    registry.close()


def test_task_failure_logs_internal_exception(caplog) -> None:
    logger = logging.getLogger("tests.tasks")
    registry = TaskRegistry(max_workers=1, logger=logger)

    def fail(_context: object) -> None:
        raise RuntimeError("secret internal detail")

    with caplog.at_level(logging.ERROR, logger=logger.name):
        snapshot = registry.wait(registry.submit("example", fail), timeout=2)
    registry.close()

    assert "secret internal detail" in caplog.text
    assert "secret" not in str(snapshot)


def test_exclusive_groups_block_only_active_tasks_in_the_same_group() -> None:
    entered = Event()
    release = Event()

    def blocked(_context: object) -> None:
        entered.set()
        release.wait(2)

    registry = TaskRegistry(max_workers=2)
    first = registry.submit("library", blocked, exclusive_group="disk_scan")
    assert entered.wait(1)
    with pytest.raises(ActiveTaskConflict) as captured:
        registry.submit("batch", blocked, exclusive_group="disk_scan")
    assert captured.value.group == "disk_scan"

    other = registry.submit("other", lambda _context: 1, exclusive_group="network")
    assert registry.wait(other, timeout=2).status == "completed"
    release.set()
    assert registry.wait(first, timeout=2).status == "completed"

    replacement = registry.submit(
        "batch",
        lambda _context: 2,
        exclusive_group="disk_scan",
    )
    assert registry.wait(replacement, timeout=2).result == 2
    registry.close()


def test_shared_group_tasks_can_coexist_but_block_an_exclusive_owner() -> None:
    entered = (Event(), Event())
    release = Event()

    def blocked(index: int):
        def operation(_context: object) -> None:
            entered[index].set()
            release.wait(2)

        return operation

    registry = TaskRegistry(max_workers=2)
    first = registry.submit(
        "library-1",
        blocked(0),
        shared_group="disk_scan",
    )
    second = registry.submit(
        "library-2",
        blocked(1),
        shared_group="disk_scan",
    )
    try:
        assert entered[0].wait(1)
        assert entered[1].wait(1)
        with pytest.raises(ActiveTaskConflict) as captured:
            registry.submit(
                "batch",
                lambda _context: None,
                exclusive_group="disk_scan",
            )
        assert captured.value.group == "disk_scan"
    finally:
        release.set()
        assert registry.wait(first, timeout=2).status == "completed"
        assert registry.wait(second, timeout=2).status == "completed"

    replacement = registry.submit(
        "batch",
        lambda _context: 2,
        exclusive_group="disk_scan",
    )
    assert registry.wait(replacement, timeout=2).result == 2
    registry.close()


def test_cancellation_reason_distinguishes_user_and_shutdown() -> None:
    entered = Event()
    release = Event()
    reasons: list[str] = []

    def blocked(context: object) -> None:
        entered.set()
        release.wait(2)
        try:
            context.raise_if_cancelled()
        except TaskCancelled as error:
            reasons.append(error.reason)
            raise

    registry = TaskRegistry(max_workers=1)
    task_id = registry.submit("user", blocked)
    assert entered.wait(1)
    assert registry.cancel(task_id) is True
    release.set()
    assert registry.wait(task_id, timeout=2).status == "cancelled"
    assert reasons == ["user"]
    registry.close()

    entered.clear()

    def shutdown_blocked(context: object) -> None:
        entered.set()
        Event().wait(0.1)
        try:
            context.raise_if_cancelled()
        except TaskCancelled as error:
            reasons.append(error.reason)
            raise

    registry = TaskRegistry(max_workers=1)
    registry.submit("shutdown", shutdown_blocked)
    assert entered.wait(1)
    registry.close()
    assert reasons == ["user", "shutdown"]


def test_latest_snapshot_returns_a_copy_and_can_filter_active_tasks() -> None:
    registry = TaskRegistry(max_workers=1)
    first = registry.submit("scan", lambda _context: "first")
    registry.wait(first, timeout=2)
    second = registry.submit("scan", lambda _context: "second")
    registry.wait(second, timeout=2)

    latest = registry.latest_snapshot("scan")

    assert latest is not None
    assert latest.id == second
    assert registry.latest_snapshot("scan", active_only=True) is None
    latest.progress["completed"] = 999
    assert registry.get_snapshot(second).progress["completed"] != 999
    registry.close()
