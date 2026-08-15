from __future__ import annotations

import os
import subprocess
import sys
from threading import Event

import pytest

from gameshelf.platform.windows.process_tree import WindowsProcessTreeTracker

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows process tree integration")


def test_real_windows_tracker_waits_for_child_after_parent_exits() -> None:
    script = (
        "import subprocess,sys,time; "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(0.8)']); "
        "print(child.pid, flush=True); time.sleep(0.3)"
    )
    parent = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert parent.stdout is not None
    child_pid = int(parent.stdout.readline().strip())
    sink = RecordingSink()
    handle = WindowsProcessTreeTracker(poll_seconds=0.05).start(parent.pid, sink)
    try:
        assert parent.wait(timeout=3) == 0
        assert sink.exit_event.wait(0.1) is False
        assert sink.exit_event.wait(3)
    finally:
        handle.stop()
        parent.stdout.close()

    assert child_pid > 0
    assert sink.exits == 1
    assert sink.degraded == []


class RecordingSink:
    def __init__(self) -> None:
        self.exits = 0
        self.degraded: list[str] = []
        self.exit_event = Event()

    def on_tree_exit(self) -> None:
        self.exits += 1
        self.exit_event.set()

    def on_tracking_degraded(self, reason: str) -> None:
        self.degraded.append(reason)
