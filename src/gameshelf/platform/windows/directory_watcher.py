"""Narrow overlapped ReadDirectoryChangesW adapter for guided save discovery."""

from __future__ import annotations

import ctypes
import itertools
import struct
import time
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from threading import Event, Lock, Thread
from typing import Any, Literal, Protocol, cast

from gameshelf.saves.guided_events import RawFileChange
from gameshelf.scanning.path_keys import is_same_or_child, windows_path_key

BUFFER_SIZE = 64_000
FILE_LIST_DIRECTORY = 0x0001
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
FILE_SHARE_DELETE = 0x00000004
OPEN_EXISTING = 3
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
FILE_FLAG_OVERLAPPED = 0x40000000
FILE_NOTIFY_CHANGE_FILE_NAME = 0x00000001
FILE_NOTIFY_CHANGE_DIR_NAME = 0x00000002
FILE_NOTIFY_CHANGE_SIZE = 0x00000008
FILE_NOTIFY_CHANGE_LAST_WRITE = 0x00000010
FILE_NOTIFY_CHANGE_CREATION = 0x00000040
NOTIFY_FILTER = (
    FILE_NOTIFY_CHANGE_FILE_NAME
    | FILE_NOTIFY_CHANGE_DIR_NAME
    | FILE_NOTIFY_CHANGE_SIZE
    | FILE_NOTIFY_CHANGE_LAST_WRITE
    | FILE_NOTIFY_CHANGE_CREATION
)
ERROR_IO_PENDING = 997
ERROR_OPERATION_ABORTED = 995
ERROR_NOT_FOUND = 1168
WAIT_OBJECT_0 = 0
INFINITE = 0xFFFFFFFF
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

type DirectoryNotificationAction = Literal[
    "created", "modified", "deleted", "renamed_old", "renamed_new"
]


class DirectoryWatchError(OSError):
    """Raised when a watch root cannot be armed safely."""


class MalformedNotificationBuffer(ValueError):
    """Raised when Windows returns an invalid FILE_NOTIFY_INFORMATION chain."""


@dataclass(frozen=True, slots=True)
class DirectoryNotification:
    action: DirectoryNotificationAction
    relative_path: str


class DirectoryWatchSink(Protocol):
    def on_change(self, change: RawFileChange) -> None: ...

    def on_overflow(self, root: Path) -> None: ...

    def on_failure(self, root: Path, code: str) -> None: ...


class _DirectoryApi(Protocol):
    def open(self, root: Path) -> object: ...

    def read(
        self,
        handle: object,
        buffer_size: int,
        on_armed: Callable[[], None],
    ) -> bytes: ...

    def cancel(self, handle: object) -> None: ...

    def close(self, handle: object) -> None: ...


class DirectoryWatchHandle:
    def __init__(
        self,
        *,
        root: Path,
        native_handle: object,
        api: _DirectoryApi,
        stop_event: Event,
        thread_name: str,
    ) -> None:
        self.root = root
        self.thread_name = thread_name
        self._native_handle = native_handle
        self._api = api
        self._stop_event = stop_event
        self._thread: Thread | None = None
        self._lock = Lock()
        self._stopped = False
        self._closed = False

    @property
    def is_alive(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def attach_thread(self, thread: Thread) -> None:
        self._thread = thread

    def stop(self, timeout: float = 5.0) -> None:
        with self._lock:
            first_stop = not self._stopped
            self._stopped = True
            self._stop_event.set()
        thread = self._thread
        if thread is None or not thread.is_alive():
            if first_stop:
                self._api.cancel(self._native_handle)
        else:
            deadline = time.monotonic() + max(timeout, 0.0)
            while thread.is_alive():
                self._api.cancel(self._native_handle)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"目录观察线程未能停止：{self.root}")
                thread.join(min(0.05, remaining))
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._api.close(self._native_handle)


class WindowsDirectoryWatcher:
    _thread_numbers = itertools.count(1)

    def __init__(
        self,
        *,
        api: _DirectoryApi | None = None,
        buffer_size: int = BUFFER_SIZE,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        ready_timeout: float = 5.0,
    ) -> None:
        if buffer_size < 1 or ready_timeout <= 0:
            raise ValueError("Directory watcher limits are invalid.")
        self._api = api or _Win32DirectoryApi()
        self._buffer_size = buffer_size
        self._monotonic_ns = monotonic_ns
        self._ready_timeout = ready_timeout

    def start(self, root: Path, sink: DirectoryWatchSink) -> DirectoryWatchHandle:
        if not root.is_dir():
            raise DirectoryWatchError(f"监控目录不存在或不可访问：{root}")
        native_handle = self._api.open(root)
        stop_event = Event()
        ready = Event()
        startup_failures: list[str] = []
        thread_name = f"gameshelf-save-watch-{next(self._thread_numbers)}"
        watch_handle = DirectoryWatchHandle(
            root=root,
            native_handle=native_handle,
            api=self._api,
            stop_event=stop_event,
            thread_name=thread_name,
        )
        thread = Thread(
            target=self._watch_loop,
            name=thread_name,
            daemon=True,
            args=(root, native_handle, sink, stop_event, ready, startup_failures),
        )
        watch_handle.attach_thread(thread)
        thread.start()
        if not ready.wait(self._ready_timeout):
            watch_handle.stop()
            raise DirectoryWatchError(f"目录观察器未能及时就绪：{root}")
        if startup_failures:
            watch_handle.stop()
            raise DirectoryWatchError(f"目录观察器启动失败：{root}")
        return watch_handle

    def _watch_loop(
        self,
        root: Path,
        native_handle: object,
        sink: DirectoryWatchSink,
        stop_event: Event,
        ready: Event,
        startup_failures: list[str],
    ) -> None:
        pending_rename: Path | None = None
        while not stop_event.is_set():
            try:
                payload = self._api.read(
                    native_handle, self._buffer_size, ready.set
                )
            except OSError as error:
                error_code = f"win32_error_{_error_number(error)}"
                if not ready.is_set():
                    startup_failures.append(error_code)
                ready.set()
                if stop_event.is_set() or _error_number(error) == ERROR_OPERATION_ABORTED:
                    return
                sink.on_failure(root, error_code)
                return
            if stop_event.is_set():
                return
            if not payload:
                pending_rename = None
                sink.on_overflow(root)
                continue
            try:
                notifications = parse_notify_buffer(payload)
            except MalformedNotificationBuffer:
                sink.on_failure(root, "malformed_notification_buffer")
                return
            for notification in notifications:
                path = _safe_child(root, notification.relative_path)
                if path is None:
                    sink.on_failure(root, "notification_outside_root")
                    continue
                if notification.action == "renamed_old":
                    if pending_rename is not None:
                        self._emit(sink, root, "deleted", pending_rename)
                    pending_rename = path
                    continue
                if notification.action == "renamed_new":
                    if pending_rename is None:
                        self._emit(sink, root, "created", path)
                    else:
                        self._emit(
                            sink,
                            root,
                            "moved",
                            pending_rename,
                            destination=path,
                        )
                        pending_rename = None
                    continue
                if pending_rename is not None:
                    self._emit(sink, root, "deleted", pending_rename)
                    pending_rename = None
                self._emit(sink, root, notification.action, path)

    def _emit(
        self,
        sink: DirectoryWatchSink,
        root: Path,
        operation: Literal["created", "modified", "deleted", "moved"],
        path: Path,
        *,
        destination: Path | None = None,
    ) -> None:
        sink.on_change(
            RawFileChange(
                operation,
                path,
                destination,
                self._monotonic_ns(),
                root=root,
            )
        )


def parse_notify_buffer(payload: bytes) -> tuple[DirectoryNotification, ...]:
    notifications: list[DirectoryNotification] = []
    offset = 0
    action_names: dict[int, DirectoryNotificationAction] = {
        1: "created",
        2: "deleted",
        3: "modified",
        4: "renamed_old",
        5: "renamed_new",
    }
    while offset < len(payload):
        if len(payload) - offset < 12:
            raise MalformedNotificationBuffer("FILE_NOTIFY_INFORMATION header is incomplete.")
        next_offset, action, name_length = struct.unpack_from("<III", payload, offset)
        name_start = offset + 12
        name_end = name_start + name_length
        if name_length % 2 or name_end > len(payload):
            raise MalformedNotificationBuffer("FILE_NOTIFY_INFORMATION name is invalid.")
        try:
            relative_path = payload[name_start:name_end].decode("utf-16-le")
        except UnicodeDecodeError as error:
            raise MalformedNotificationBuffer(
                "FILE_NOTIFY_INFORMATION name is not UTF-16LE."
            ) from error
        action_name = action_names.get(action)
        if action_name is not None:
            notifications.append(DirectoryNotification(action_name, relative_path))
        if next_offset == 0:
            break
        if next_offset < 12 or offset + next_offset > len(payload):
            raise MalformedNotificationBuffer("FILE_NOTIFY_INFORMATION offset is invalid.")
        offset += next_offset
    return tuple(notifications)


def _safe_child(root: Path, relative_path: str) -> Path | None:
    windows_path = PureWindowsPath(relative_path)
    if windows_path.drive or windows_path.root or ".." in windows_path.parts:
        return None
    candidate = root.joinpath(*windows_path.parts)
    if not is_same_or_child(windows_path_key(candidate), windows_path_key(root)):
        return None
    return candidate


def _error_number(error: OSError) -> int:
    value = getattr(error, "winerror", None) or error.errno
    if value is None and error.args and isinstance(error.args[0], int):
        value = error.args[0]
    return int(value or 1)


class _OVERLAPPED(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.c_size_t),
        ("InternalHigh", ctypes.c_size_t),
        ("Offset", wintypes.DWORD),
        ("OffsetHigh", wintypes.DWORD),
        ("hEvent", wintypes.HANDLE),
    ]


class _Win32DirectoryApi:
    def __init__(self) -> None:
        kernel32: Any = ctypes.WinDLL("kernel32", use_last_error=True)
        self._create_file = kernel32.CreateFileW
        self._create_file.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        self._create_file.restype = wintypes.HANDLE
        self._read_changes = kernel32.ReadDirectoryChangesW
        self._read_changes.argtypes = [
            wintypes.HANDLE,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(_OVERLAPPED),
            wintypes.LPVOID,
        ]
        self._read_changes.restype = wintypes.BOOL
        self._cancel_io = kernel32.CancelIoEx
        self._cancel_io.argtypes = [wintypes.HANDLE, ctypes.POINTER(_OVERLAPPED)]
        self._cancel_io.restype = wintypes.BOOL
        self._get_result = kernel32.GetOverlappedResult
        self._get_result.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_OVERLAPPED),
            ctypes.POINTER(wintypes.DWORD),
            wintypes.BOOL,
        ]
        self._get_result.restype = wintypes.BOOL
        self._create_event = kernel32.CreateEventW
        self._create_event.argtypes = [
            wintypes.LPVOID,
            wintypes.BOOL,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        ]
        self._create_event.restype = wintypes.HANDLE
        self._wait = kernel32.WaitForSingleObject
        self._wait.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self._wait.restype = wintypes.DWORD
        self._close_handle = kernel32.CloseHandle
        self._close_handle.argtypes = [wintypes.HANDLE]
        self._close_handle.restype = wintypes.BOOL

    def open(self, root: Path) -> object:
        handle = self._create_file(
            str(root),
            FILE_LIST_DIRECTORY,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            None,
            OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OVERLAPPED,
            None,
        )
        if cast(int | None, handle) == INVALID_HANDLE_VALUE:
            raise ctypes.WinError(ctypes.get_last_error())
        return handle

    def read(
        self,
        handle: object,
        buffer_size: int,
        on_armed: Callable[[], None],
    ) -> bytes:
        native_handle = cast(wintypes.HANDLE, handle)
        event_handle = self._create_event(None, True, False, None)
        if not event_handle:
            raise ctypes.WinError(ctypes.get_last_error())
        buffer = ctypes.create_string_buffer(buffer_size)
        overlapped = _OVERLAPPED()
        overlapped.hEvent = event_handle
        bytes_returned = wintypes.DWORD()
        try:
            succeeded = self._read_changes(
                native_handle,
                buffer,
                buffer_size,
                True,
                NOTIFY_FILTER,
                None,
                ctypes.byref(overlapped),
                None,
            )
            if not succeeded and ctypes.get_last_error() != ERROR_IO_PENDING:
                raise ctypes.WinError(ctypes.get_last_error())
            on_armed()
            wait_result = self._wait(event_handle, INFINITE)
            if wait_result != WAIT_OBJECT_0:
                raise ctypes.WinError(ctypes.get_last_error())
            if not self._get_result(
                native_handle,
                ctypes.byref(overlapped),
                ctypes.byref(bytes_returned),
                False,
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            return bytes(buffer.raw[: bytes_returned.value])
        finally:
            self._close_handle(event_handle)

    def cancel(self, handle: object) -> None:
        if self._cancel_io(cast(wintypes.HANDLE, handle), None):
            return
        error = ctypes.get_last_error()
        if error not in {ERROR_NOT_FOUND, ERROR_OPERATION_ABORTED}:
            raise ctypes.WinError(error)

    def close(self, handle: object) -> None:
        if not self._close_handle(cast(wintypes.HANDLE, handle)):
            raise ctypes.WinError(ctypes.get_last_error())
