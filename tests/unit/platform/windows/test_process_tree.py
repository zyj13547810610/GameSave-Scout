from __future__ import annotations

from threading import Event
from threading import enumerate as enumerate_threads

from gamesave_scout.platform.windows.process_tree import (
    ProcessRecord,
    WindowsProcessTreeTracker,
)


def test_tracker_waits_until_seen_child_exits() -> None:
    now = [100.0]
    snapshots = iter(
        [
            (ProcessRecord(10, 1), ProcessRecord(11, 10)),
            (ProcessRecord(11, 10),),
            (),
        ]
    )
    sink = RecordingProcessSink()
    tracker = WindowsProcessTreeTracker(
        lambda: next(snapshots), poll_seconds=0, monotonic_clock=lambda: now[0]
    )

    tracker.poll_once(10, sink)
    tracker.poll_once(10, sink)
    now[0] = 105.0
    tracker.poll_once(10, sink)

    assert sink.exits == 1
    assert sink.degraded == []


def test_tracker_discovers_descendant_after_its_parent_has_exited() -> None:
    now = [100.0]
    snapshots = iter(
        [
            (ProcessRecord(10, 1), ProcessRecord(11, 10)),
            (ProcessRecord(12, 11),),
            (ProcessRecord(12, 11),),
            (),
        ]
    )
    sink = RecordingProcessSink()
    tracker = WindowsProcessTreeTracker(
        lambda: next(snapshots), poll_seconds=0, monotonic_clock=lambda: now[0]
    )

    for _ in range(3):
        tracker.poll_once(10, sink)
    now[0] = 106.0
    tracker.poll_once(10, sink)

    assert sink.exits == 1
    assert sink.degraded == []


def test_tracker_degrades_when_observed_tree_disappears_during_launch() -> None:
    snapshots = iter(
        [
            (ProcessRecord(10, 1),),
            (),
        ]
    )
    sink = RecordingProcessSink()
    tracker = WindowsProcessTreeTracker(lambda: next(snapshots), poll_seconds=0)

    tracker.poll_once(10, sink)
    tracker.poll_once(10, sink)

    assert sink.exits == 0
    assert sink.degraded == ["tree_exited_during_launch_grace"]


def test_tracker_degrades_when_root_is_missing_from_first_successful_snapshot() -> None:
    sink = RecordingProcessSink()
    tracker = WindowsProcessTreeTracker(lambda: (), poll_seconds=0)

    tracker.poll_once(10, sink)
    tracker.poll_once(10, sink)

    assert sink.exits == 0
    assert sink.degraded == ["root_missing_from_initial_snapshot"]


def test_tracker_degrades_once_when_snapshot_api_fails() -> None:
    sink = RecordingProcessSink()

    def failing_snapshot() -> tuple[ProcessRecord, ...]:
        raise OSError(5, "access denied")

    tracker = WindowsProcessTreeTracker(failing_snapshot, poll_seconds=0)

    tracker.poll_once(10, sink)
    tracker.poll_once(10, sink)

    assert sink.exits == 0
    assert sink.degraded == ["snapshot_failed"]


def test_process_tree_handle_stops_named_thread_idempotently() -> None:
    snapshot_called = Event()

    def snapshots() -> tuple[ProcessRecord, ...]:
        snapshot_called.set()
        return (ProcessRecord(10, 1),)

    sink = RecordingProcessSink()
    handle = WindowsProcessTreeTracker(snapshots, poll_seconds=10).start(10, sink)
    assert snapshot_called.wait(3)
    thread_name = handle.thread_name

    handle.stop()
    handle.stop()

    assert handle.is_alive is False
    assert not any(thread.name == thread_name for thread in enumerate_threads())


class RecordingProcessSink:
    def __init__(self) -> None:
        self.exits = 0
        self.degraded: list[str] = []
        self.exit_event = Event()

    def on_tree_exit(self) -> None:
        self.exits += 1
        self.exit_event.set()

    def on_tracking_degraded(self, reason: str) -> None:
        self.degraded.append(reason)
