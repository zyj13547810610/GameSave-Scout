from __future__ import annotations

import struct
from collections.abc import Callable
from pathlib import Path
from threading import Condition, Event, Lock

import pytest

from gamesave_scout.platform.windows.directory_watcher import (
    DirectoryNotification,
    DirectoryWatchError,
    WindowsDirectoryWatcher,
    parse_notify_buffer,
)
from gamesave_scout.saves.guided_events import RawFileChange


def test_parse_notify_buffer_decodes_each_supported_action() -> None:
    payload = _notify_buffer(
        (1, "slot.sav"),
        (3, "slot.sav"),
        (4, "slot.tmp"),
        (5, "slot.sav"),
    )

    notifications = parse_notify_buffer(payload)

    assert notifications == (
        DirectoryNotification("created", "slot.sav"),
        DirectoryNotification("modified", "slot.sav"),
        DirectoryNotification("renamed_old", "slot.tmp"),
        DirectoryNotification("renamed_new", "slot.sav"),
    )


def test_watcher_pairs_rename_and_emits_bounded_raw_changes(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    api = FakeDirectoryApi(
        [_notify_buffer((1, "slot.tmp"), (4, "slot.tmp"), (5, "slot.sav"))]
    )
    sink = RecordingDirectorySink()
    watcher = WindowsDirectoryWatcher(api=api, monotonic_ns=iter((10, 11)).__next__)

    handle = watcher.start(root, sink)
    try:
        assert sink.wait_for(lambda: len(sink.changes) == 2)
    finally:
        handle.stop()

    assert sink.changes == [
        RawFileChange("created", root / "slot.tmp", None, 10, root=root),
        RawFileChange("moved", root / "slot.tmp", root / "slot.sav", 11, root=root),
    ]
    assert api.cancel_calls == 1
    assert api.close_calls == 1
    assert handle.is_alive is False


def test_zero_byte_read_reports_overflow_without_fabricating_change(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    api = FakeDirectoryApi([b""])
    sink = RecordingDirectorySink()
    handle = WindowsDirectoryWatcher(api=api).start(root, sink)
    try:
        assert sink.wait_for(lambda: sink.overflows == [root])
    finally:
        handle.stop()

    assert sink.changes == []
    assert sink.failures == []


def test_non_cancelled_read_failure_is_reported_and_stop_is_idempotent(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    api = FakeDirectoryApi([OSError(5, "access denied")])
    sink = RecordingDirectorySink()
    handle = WindowsDirectoryWatcher(api=api).start(root, sink)

    assert sink.wait_for(lambda: bool(sink.failures))
    handle.stop()
    handle.stop()

    assert sink.failures == [(root, "win32_error_5")]
    assert api.cancel_calls == 1
    assert api.close_calls == 1


def test_failure_before_first_read_is_armed_rejects_watcher_start(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    api = FailingBeforeArmedDirectoryApi()
    sink = RecordingDirectorySink()

    with pytest.raises(DirectoryWatchError):
        WindowsDirectoryWatcher(api=api).start(root, sink)

    assert sink.failures == [(root, "win32_error_5")]
    assert api.cancel_calls == 1
    assert api.close_calls == 1


def test_stop_retries_cancel_when_next_read_arms_after_first_cancel(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    api = CancellationArmRaceDirectoryApi()
    sink = RecordingDirectorySink()
    handle = WindowsDirectoryWatcher(api=api).start(root, sink)

    assert api.second_read_started.wait(1)
    try:
        handle.stop(timeout=0.5)
    finally:
        api.force_release()
        if handle.is_alive:
            handle.stop(timeout=1)

    assert api.cancel_calls >= 2
    assert api.close_calls == 1


class FakeDirectoryApi:
    def __init__(self, batches: list[bytes | OSError]) -> None:
        self._batches = list(batches)
        self._cancelled = Event()
        self._lock = Lock()
        self.cancel_calls = 0
        self.close_calls = 0

    def open(self, root: Path) -> object:
        return root

    def read(
        self,
        _handle: object,
        _buffer_size: int,
        on_armed: Callable[[], None],
    ) -> bytes:
        on_armed()
        with self._lock:
            batch = self._batches.pop(0) if self._batches else None
        if isinstance(batch, OSError):
            raise batch
        if batch is not None:
            return batch
        self._cancelled.wait(3)
        raise OSError(995, "operation cancelled")

    def cancel(self, _handle: object) -> None:
        self.cancel_calls += 1
        self._cancelled.set()

    def close(self, _handle: object) -> None:
        self.close_calls += 1


class FailingBeforeArmedDirectoryApi(FakeDirectoryApi):
    def __init__(self) -> None:
        super().__init__([])

    def read(
        self,
        _handle: object,
        _buffer_size: int,
        _on_armed: Callable[[], None],
    ) -> bytes:
        raise OSError(5, "access denied")


class CancellationArmRaceDirectoryApi:
    def __init__(self) -> None:
        self.second_read_started = Event()
        self._allow_second_arm = Event()
        self._second_read_pending = Event()
        self._release = Event()
        self._read_count = 0
        self.cancel_calls = 0
        self.close_calls = 0

    def open(self, root: Path) -> object:
        return root

    def read(
        self,
        _handle: object,
        _buffer_size: int,
        on_armed: Callable[[], None],
    ) -> bytes:
        self._read_count += 1
        on_armed()
        if self._read_count == 1:
            return _notify_buffer((1, "slot.sav"))
        self.second_read_started.set()
        self._allow_second_arm.wait(1)
        self._second_read_pending.set()
        self._release.wait(2)
        raise OSError(995, "operation cancelled")

    def cancel(self, _handle: object) -> None:
        self.cancel_calls += 1
        self._allow_second_arm.set()
        if self._second_read_pending.is_set():
            self._release.set()

    def close(self, _handle: object) -> None:
        self.close_calls += 1

    def force_release(self) -> None:
        self._release.set()


class RecordingDirectorySink:
    def __init__(self) -> None:
        self.changes: list[RawFileChange] = []
        self.overflows: list[Path] = []
        self.failures: list[tuple[Path, str]] = []
        self._condition = Condition()

    def on_change(self, change: RawFileChange) -> None:
        with self._condition:
            self.changes.append(change)
            self._condition.notify_all()

    def on_overflow(self, root: Path) -> None:
        with self._condition:
            self.overflows.append(root)
            self._condition.notify_all()

    def on_failure(self, root: Path, code: str) -> None:
        with self._condition:
            self.failures.append((root, code))
            self._condition.notify_all()

    def wait_for(self, predicate: Callable[[], bool], timeout: float = 3.0) -> bool:
        with self._condition:
            return self._condition.wait_for(predicate, timeout)


def _notify_buffer(*entries: tuple[int, str]) -> bytes:
    encoded_entries: list[bytes] = []
    for action, name in entries:
        encoded_name = name.encode("utf-16-le")
        size = 12 + len(encoded_name)
        padded_size = (size + 3) & ~3
        encoded_entries.append(
            struct.pack("<III", padded_size, action, len(encoded_name))
            + encoded_name
            + bytes(padded_size - size)
        )
    if encoded_entries:
        last = encoded_entries[-1]
        encoded_entries[-1] = struct.pack("<I", 0) + last[4:]
    return b"".join(encoded_entries)
