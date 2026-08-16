"""Validate and configure the bundled WebView2 Fixed Version Runtime."""

from __future__ import annotations

import ctypes
import subprocess
import sys
from collections.abc import Callable, MutableMapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

DRIVE_FIXED = 3
WINDOWS_11_FIRST_BUILD = 22000
_APPCONTAINER_SIDS = ("S-1-15-2-2", "S-1-15-2-1")

type DriveTypeLookup = Callable[[Path], int]
type CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


class WebViewRuntimeError(RuntimeError):
    """Raised when the bundled WebView2 runtime cannot be used safely."""


class WebViewSettings(Protocol):
    settings: MutableMapping[str, object]


@dataclass
class WebViewRuntime:
    """Runtime-specific WebView2 location and Windows permission preparation."""

    path: Path | None
    frozen: bool
    windows_build: int | None
    _drive_type: DriveTypeLookup = field(repr=False)
    _runner: CommandRunner = field(repr=False)
    _system_directory: Path | None = field(repr=False)
    _permissions_prepared: bool = field(default=False, init=False, repr=False)

    @classmethod
    def for_runtime(
        cls,
        app_root: Path,
        *,
        frozen: bool | None = None,
        drive_type: DriveTypeLookup | None = None,
        windows_build: int | None = None,
        runner: CommandRunner | None = None,
        system_directory: Path | None = None,
    ) -> WebViewRuntime:
        is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
        if not is_frozen:
            return cls(None, False, None, _windows_drive_type, _run_command, None)
        return cls(
            path=Path(app_root) / "runtime",
            frozen=True,
            windows_build=_windows_build() if windows_build is None else windows_build,
            _drive_type=drive_type or _windows_drive_type,
            _runner=runner or _run_command,
            _system_directory=(
                _windows_system_directory()
                if system_directory is None
                else system_directory
            ),
        )

    @property
    def executable(self) -> Path | None:
        return None if self.path is None else self.path / "msedgewebview2.exe"

    def validate(self) -> None:
        if not self.frozen:
            return
        if self.path is None:
            raise WebViewRuntimeError("冻结环境缺少内置 WebView2 Runtime 路径。")
        if _is_unc(self.path):
            raise WebViewRuntimeError("内置 WebView2 Runtime 不能位于 UNC 或网络路径。")
        if self._drive_type(self.path) != DRIVE_FIXED:
            raise WebViewRuntimeError("内置 WebView2 Runtime 必须位于本地固定磁盘。")
        executable = self.executable
        if executable is None or not executable.is_file():
            raise WebViewRuntimeError(
                f"内置 WebView2 Runtime 缺少 msedgewebview2.exe：{self.path}"
            )

    def prepare_windows10_permissions(self) -> bool:
        if (
            not self.frozen
            or self.windows_build is None
            or self.windows_build >= WINDOWS_11_FIRST_BUILD
            or self._permissions_prepared
        ):
            return False
        self.validate()
        if self.path is None or self._system_directory is None:
            raise WebViewRuntimeError("无法确定 WebView2 Runtime 或 Windows 系统目录。")
        icacls = self._system_directory / "icacls.exe"
        if not icacls.is_file():
            raise WebViewRuntimeError(f"找不到 Windows 权限工具：{icacls}")
        for sid in _APPCONTAINER_SIDS:
            result = self._runner(
                (
                    str(icacls),
                    str(self.path),
                    "/grant",
                    f"*{sid}:(OI)(CI)(RX)",
                )
            )
            if result.returncode != 0:
                detail = result.stderr.strip() or result.stdout.strip() or "未知错误"
                raise WebViewRuntimeError(
                    f"无法为内置 WebView2 Runtime 准备 Windows 10 权限：{detail}"
                )
        self._permissions_prepared = True
        return True

    def configure(self, webview_module: WebViewSettings) -> None:
        if not self.frozen:
            return
        self.validate()
        if self.path is None:
            raise WebViewRuntimeError("冻结环境缺少内置 WebView2 Runtime 路径。")
        webview_module.settings["WEBVIEW2_RUNTIME_PATH"] = str(self.path)


def _is_unc(path: Path) -> bool:
    return str(path).startswith("\\\\")


def _windows_drive_type(path: Path) -> int:
    anchor = path.anchor
    if not anchor:
        return 0
    kernel32: Any = ctypes.WinDLL("kernel32", use_last_error=True)
    get_drive_type = kernel32.GetDriveTypeW
    get_drive_type.argtypes = [ctypes.c_wchar_p]
    get_drive_type.restype = ctypes.c_uint
    return int(get_drive_type(anchor))


def _windows_system_directory() -> Path:
    kernel32: Any = ctypes.WinDLL("kernel32", use_last_error=True)
    get_system_directory = kernel32.GetSystemDirectoryW
    get_system_directory.argtypes = [ctypes.c_wchar_p, ctypes.c_uint]
    get_system_directory.restype = ctypes.c_uint
    buffer = ctypes.create_unicode_buffer(32768)
    length = int(get_system_directory(buffer, len(buffer)))
    if length == 0 or length >= len(buffer):
        raise WebViewRuntimeError("无法确定 Windows 系统目录。")
    return Path(buffer.value)


def _windows_build() -> int:
    get_windows_version = getattr(sys, "getwindowsversion", None)
    if not callable(get_windows_version):
        raise WebViewRuntimeError("冻结版仅支持 Windows 10/11 x64。")
    build = getattr(get_windows_version(), "build", None)
    if not isinstance(build, int):
        raise WebViewRuntimeError("无法确定 Windows 系统版本。")
    return build


def _run_command(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
        shell=False,
    )
