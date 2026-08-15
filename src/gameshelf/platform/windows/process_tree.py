"""Windows process-tree lifecycle tracking without file-write attribution."""

from __future__ import annotations

import ctypes
import itertools
from collections.abc import Callable, Sequence
from ctypes import wintypes
from dataclasses import dataclass, field
from threading import Event, Lock, Thread
from typing import Any, Protocol, cast

TH32CS_SNAPPROCESS = 0x00000002
ERROR_NO_MORE_FILES = 18
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


@dataclass(frozen=True, slots=True)
class ProcessRecord:
    pid: int
    parent_pid: int


class ProcessTreeSink(Protocol):
    def on_tree_exit(self) -> None: ...

    def on_tracking_degraded(self, reason: str) -> None: ...


type ProcessSnapshotter = Callable[[], Sequence[ProcessRecord]]


@dataclass(slots=True)
class _TrackingState:
    seen_pids: set[int] = field(default_factory=set)
    observed_any: bool = False
    terminal: bool = False


class ProcessTreeHandle:
    def __init__(self, stop_event: Event, thread: Thread) -> None:
        self._stop_event = stop_event
        self._thread = thread
        self._lock = Lock()
        self._stopped = False
        self.thread_name = thread.name

    @property
    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def stop(self, timeout: float = 5.0) -> None:
        with self._lock:
            self._stopped = True
            self._stop_event.set()
        self._thread.join(timeout)
        if self._thread.is_alive():
            raise TimeoutError("进程树跟踪线程未能在限定时间内停止。")


class WindowsProcessTreeTracker:
    _thread_numbers = itertools.count(1)

    def __init__(
        self,
        snapshotter: ProcessSnapshotter | None = None,
        *,
        poll_seconds: float = 1.0,
    ) -> None:
        if poll_seconds < 0:
            raise ValueError("Process tree poll interval cannot be negative.")
        self._snapshotter = snapshotter or _ToolhelpSnapshotter()
        self._poll_seconds = poll_seconds
        self._manual_states: dict[int, _TrackingState] = {}
        self._manual_lock = Lock()

    def poll_once(self, root_pid: int, sink: ProcessTreeSink) -> None:
        if root_pid <= 0:
            raise ValueError("Root process ID must be positive.")
        with self._manual_lock:
            state = self._manual_states.setdefault(root_pid, _TrackingState())
            self._poll_state(root_pid, sink, state)

    def start(self, root_pid: int, sink: ProcessTreeSink) -> ProcessTreeHandle:
        if root_pid <= 0:
            raise ValueError("Root process ID must be positive.")
        stop_event = Event()
        state = _TrackingState()
        thread = Thread(
            target=self._run,
            name=f"gameshelf-process-tree-{next(self._thread_numbers)}",
            daemon=True,
            args=(root_pid, sink, state, stop_event),
        )
        handle = ProcessTreeHandle(stop_event, thread)
        thread.start()
        return handle

    def _run(
        self,
        root_pid: int,
        sink: ProcessTreeSink,
        state: _TrackingState,
        stop_event: Event,
    ) -> None:
        while not stop_event.is_set():
            self._poll_state(root_pid, sink, state)
            if state.terminal or stop_event.wait(self._poll_seconds):
                return

    def _poll_state(
        self, root_pid: int, sink: ProcessTreeSink, state: _TrackingState
    ) -> None:
        if state.terminal:
            return
        try:
            records = tuple(self._snapshotter())
        except (OSError, RuntimeError):
            state.terminal = True
            sink.on_tracking_degraded("snapshot_failed")
            return
        current = _current_tree(records, root_pid, state.seen_pids)
        if current:
            state.observed_any = True
            state.seen_pids.update(current)
            return
        state.terminal = True
        if state.observed_any:
            sink.on_tree_exit()
        else:
            sink.on_tracking_degraded("root_missing_from_initial_snapshot")


def _current_tree(
    records: Sequence[ProcessRecord], root_pid: int, seen_pids: set[int]
) -> set[int]:
    known_parents = {root_pid, *seen_pids}
    current: set[int] = set()
    changed = True
    while changed:
        changed = False
        for record in records:
            if (
                record.pid not in current
                and (record.pid == root_pid or record.parent_pid in known_parents)
            ):
                current.add(record.pid)
                known_parents.add(record.pid)
                changed = True
    return current


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


class _ToolhelpSnapshotter:
    def __init__(self) -> None:
        kernel32: Any = ctypes.WinDLL("kernel32", use_last_error=True)
        self._create_snapshot = kernel32.CreateToolhelp32Snapshot
        self._create_snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        self._create_snapshot.restype = wintypes.HANDLE
        self._first = kernel32.Process32FirstW
        self._first.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
        self._first.restype = wintypes.BOOL
        self._next = kernel32.Process32NextW
        self._next.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
        self._next.restype = wintypes.BOOL
        self._close = kernel32.CloseHandle
        self._close.argtypes = [wintypes.HANDLE]
        self._close.restype = wintypes.BOOL

    def __call__(self) -> tuple[ProcessRecord, ...]:
        handle = self._create_snapshot(TH32CS_SNAPPROCESS, 0)
        if cast(int | None, handle) == INVALID_HANDLE_VALUE:
            raise ctypes.WinError(ctypes.get_last_error())
        records: list[ProcessRecord] = []
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        try:
            if not self._first(handle, ctypes.byref(entry)):
                error = ctypes.get_last_error()
                if error == ERROR_NO_MORE_FILES:
                    return ()
                raise ctypes.WinError(error)
            while True:
                records.append(
                    ProcessRecord(
                        pid=int(entry.th32ProcessID),
                        parent_pid=int(entry.th32ParentProcessID),
                    )
                )
                entry.dwSize = ctypes.sizeof(entry)
                if self._next(handle, ctypes.byref(entry)):
                    continue
                error = ctypes.get_last_error()
                if error != ERROR_NO_MORE_FILES:
                    raise ctypes.WinError(error)
                break
        finally:
            self._close(handle)
        return tuple(records)
