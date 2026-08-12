from threading import Event

from gameshelf.bridge.tasks import TaskRegistry


def test_task_reports_progress_and_result() -> None:
    registry = TaskRegistry(max_workers=1)

    def work(context: object) -> dict[str, int]:
        context.report(1, 2, "一半")
        return {"answer": 42}

    task_id = registry.submit("example", work)
    snapshot = registry.wait(task_id, timeout=2)

    assert snapshot.status == "completed"
    assert snapshot.progress == {"completed": 1, "total": 2}
    assert snapshot.message == "一半"
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
    assert snapshot.error == {"code": "task_failed", "message": "任务执行失败。"}
    assert "secret" not in str(snapshot)
    registry.close()
