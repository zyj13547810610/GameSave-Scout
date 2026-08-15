from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from threading import Condition
from threading import enumerate as enumerate_threads

import pytest

from gameshelf.platform.windows.directory_watcher import WindowsDirectoryWatcher
from gameshelf.saves.guided_events import RawFileChange

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows watcher integration")


def test_real_windows_watcher_observes_create_modify_and_atomic_rename(
    tmp_path: Path,
) -> None:
    root = tmp_path / "watched"
    root.mkdir()
    sink = RecordingSink()
    handle = WindowsDirectoryWatcher().start(root, sink)
    try:
        temporary = root / "slot.tmp"
        final = root / "slot.sav"
        temporary.write_bytes(b"first")
        temporary.write_bytes(b"second")
        temporary.replace(final)

        assert sink.wait_for(
            lambda: any(
                change.operation == "moved" and change.destination_path == final
                for change in sink.changes
            )
        )
    finally:
        thread_name = handle.thread_name
        handle.stop()

    assert any(change.operation == "created" for change in sink.changes)
    assert any(change.operation == "modified" for change in sink.changes)
    assert not any(thread.name == thread_name for thread in enumerate_threads())


class RecordingSink:
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
