"""Detect Evergreen WebView2 and guide the user to its manual installer."""

from __future__ import annotations

import ctypes
import hashlib
import importlib
import os
import stat
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, cast

from gameshelf.bootstrap.release_runtime import ReleaseRuntimeConfig, RuntimeMode
from gameshelf.platform.windows.startup_reporter import FrozenRuntimeInstallPrompt

type VersionDetector = Callable[[], str | None]
type ConsentPrompt = Callable[[], bool]
type LocationOpener = Callable[[Path], None]


class _CoreWebView2Environment(Protocol):
    @staticmethod
    def GetAvailableBrowserVersionString() -> object: ...


class WebViewInstallCancelled(Exception):
    """Raised when the user declines to open the manual installer location."""


class WebViewManualInstallRequired(Exception):
    """Raised after Explorer opens so the user can install and restart."""


class WebViewBootstrapperError(RuntimeError):
    """Raised when Evergreen detection or manual-install guidance fails."""


@dataclass
class EvergreenRuntimeGuide:
    """Guide a missing Evergreen runtime to a verified manual installer."""

    detector: VersionDetector = field(default_factory=lambda: detect_evergreen_version)
    prompt: ConsentPrompt = field(
        default_factory=lambda: FrozenRuntimeInstallPrompt().confirm
    )
    opener: LocationOpener = field(default_factory=lambda: _open_bootstrapper_location)

    def ensure_available(
        self,
        config: ReleaseRuntimeConfig,
        *,
        allow_manual_guide: bool,
    ) -> str:
        version = self.detector()
        if not allow_manual_guide:
            _validate_bootstrapper(config)
            if version is not None:
                return version
            raise WebViewBootstrapperError(
                "系统未安装 Evergreen WebView2；smoke 不会打开安装位置。"
            )
        if version is not None:
            return version

        _validate_bootstrapper(config)
        if not self.prompt():
            raise WebViewInstallCancelled
        path = config.bootstrapper_path
        if path is None:
            raise WebViewBootstrapperError("发布配置缺少 WebView2 Bootstrapper 路径。")
        self.opener(path)
        raise WebViewManualInstallRequired
def detect_evergreen_version() -> str | None:
    """Return the installed Evergreen version or ``None`` when it is absent."""

    try:
        environment, runtime_not_found = _load_core_webview2_environment()
    except Exception as exc:
        raise WebViewBootstrapperError(f"无法加载 WebView2 检测组件：{exc}") from exc
    try:
        raw_version = environment.GetAvailableBrowserVersionString()
    except runtime_not_found:
        return None
    except Exception as exc:
        raise WebViewBootstrapperError(f"检测 Evergreen WebView2 失败：{exc}") from exc
    version = str(raw_version).strip()
    if not version:
        raise WebViewBootstrapperError("检测 Evergreen WebView2 返回了空版本。")
    return version


def _load_core_webview2_environment(
) -> tuple[type[_CoreWebView2Environment], type[BaseException]]:
    try:
        clr = importlib.import_module("clr")
    except Exception:
        os.environ["PYTHONNET_RUNTIME"] = "coreclr"
        clr = importlib.import_module("clr")

    webview_util = importlib.import_module("webview.util")
    add_reference = clr.AddReference
    interop_dll_path = webview_util.interop_dll_path
    add_reference(interop_dll_path("Microsoft.Web.WebView2.Core.dll"))
    core = importlib.import_module("Microsoft.Web.WebView2.Core")
    environment = cast(
        type[_CoreWebView2Environment],
        core.CoreWebView2Environment,
    )
    runtime_not_found = cast(
        type[BaseException],
        core.WebView2RuntimeNotFoundException,
    )
    return environment, runtime_not_found


def _validate_bootstrapper(config: ReleaseRuntimeConfig) -> None:
    if config.mode is not RuntimeMode.EVERGREEN:
        raise WebViewBootstrapperError("只有 Evergreen 发布配置可以运行 Bootstrapper。")
    path = config.bootstrapper_path
    digest = config.bootstrapper_sha256
    if path is None or not path.is_absolute() or not path.is_file():
        raise WebViewBootstrapperError(f"WebView2 Bootstrapper 文件不存在：{path}")
    if _is_reparse_point(path):
        raise WebViewBootstrapperError(
            f"WebView2 Bootstrapper 不能是重解析点：{path}"
        )
    if digest is None:
        raise WebViewBootstrapperError("发布配置缺少 WebView2 Bootstrapper SHA-256。")
    actual_digest = _sha256(path)
    if actual_digest != digest:
        raise WebViewBootstrapperError(
            "WebView2 Bootstrapper SHA-256 不匹配："
            f"expected={digest}, actual={actual_digest}"
        )


def _sha256(path: os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_reparse_point(path: Path) -> bool:
    try:
        attributes = path.lstat().st_file_attributes
    except OSError as exc:
        raise WebViewBootstrapperError(
            f"无法检查 WebView2 Bootstrapper 文件属性：{path}"
        ) from exc
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _open_bootstrapper_location(path: Path) -> None:
    windows_directory = os.environ.get("WINDIR")
    if not windows_directory:
        raise WebViewBootstrapperError("无法确定 Windows 目录，不能打开安装位置。")
    explorer = Path(windows_directory) / "explorer.exe"
    if not explorer.is_absolute() or not explorer.is_file():
        raise WebViewBootstrapperError(f"找不到 Windows Explorer：{explorer}")
    try:
        result = _shell_execute_explorer(explorer, path)
    except OSError as exc:
        raise WebViewBootstrapperError(
            f"无法打开 WebView2 安装位置：{exc}"
        ) from exc
    if result <= 32:
        raise WebViewBootstrapperError(
            f"无法打开 WebView2 安装位置，ShellExecuteW 返回 {result}。"
        )


def _shell_execute_explorer(explorer: Path, selected_file: Path) -> int:
    shell32: Any = ctypes.WinDLL("shell32", use_last_error=True)
    shell_execute = shell32.ShellExecuteW
    shell_execute.argtypes = [
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_int,
    ]
    shell_execute.restype = ctypes.c_void_p
    result = shell_execute(
        None,
        "open",
        str(explorer),
        f'/select,"{selected_file}"',
        str(selected_file.parent),
        1,
    )
    return int(result or 0)
