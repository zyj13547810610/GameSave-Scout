"""Detect and, with explicit consent, install Evergreen WebView2."""

from __future__ import annotations

import hashlib
import importlib
import os
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol, cast

from gameshelf.bootstrap.release_runtime import ReleaseRuntimeConfig, RuntimeMode
from gameshelf.platform.windows.startup_reporter import FrozenRuntimeInstallPrompt

type VersionDetector = Callable[[], str | None]
type ConsentPrompt = Callable[[], bool]
type CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]
type Clock = Callable[[], float]
type Sleeper = Callable[[float], None]


class _CoreWebView2Environment(Protocol):
    @staticmethod
    def GetAvailableBrowserVersionString() -> object: ...


class WebViewInstallCancelled(Exception):
    """Raised only when the user declines the Evergreen installation prompt."""


class WebViewBootstrapperError(RuntimeError):
    """Raised when Evergreen detection or controlled installation fails."""


@dataclass
class EvergreenRuntimeInstaller:
    """Ensure Evergreen WebView2 is available without restarting GameShelf."""

    detector: VersionDetector = field(default_factory=lambda: detect_evergreen_version)
    prompt: ConsentPrompt = field(
        default_factory=lambda: FrozenRuntimeInstallPrompt().confirm
    )
    runner: CommandRunner = field(default_factory=lambda: _run_bootstrapper)
    monotonic: Clock = time.monotonic
    sleeper: Sleeper = time.sleep
    timeout_seconds: float = 15.0

    def ensure_available(
        self,
        config: ReleaseRuntimeConfig,
        *,
        allow_install: bool,
    ) -> str:
        version = self.detector()
        if not allow_install:
            _validate_bootstrapper(config)
            if version is not None:
                return version
            raise WebViewBootstrapperError(
                "系统未安装 Evergreen WebView2；smoke 不会运行安装器。"
            )
        if version is not None:
            return version
        if not self.prompt():
            raise WebViewInstallCancelled

        _validate_bootstrapper(config)
        path = config.bootstrapper_path
        if path is None:
            raise WebViewBootstrapperError("发布配置缺少 WebView2 Bootstrapper 路径。")
        result = self.runner((str(path), "/silent", "/install"))
        _require_success(result)
        return self._wait_for_runtime()

    def _wait_for_runtime(self) -> str:
        deadline = self.monotonic() + self.timeout_seconds
        while self.monotonic() < deadline:
            version = self.detector()
            if version is not None:
                return version
            self.sleeper(0.1)
        raise WebViewBootstrapperError(
            "WebView2 安装完成后仍未检测到 Evergreen Runtime。"
        )


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


def _require_success(result: subprocess.CompletedProcess[str]) -> None:
    if result.returncode == 0:
        return
    details = "\n".join(
        detail.strip()
        for detail in (result.stdout, result.stderr)
        if detail and detail.strip()
    )
    if not details:
        details = "无输出"
    raise WebViewBootstrapperError(
        f"WebView2 Bootstrapper 退出码 {result.returncode}：{details}"
    )


def _run_bootstrapper(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
        shell=False,
    )
