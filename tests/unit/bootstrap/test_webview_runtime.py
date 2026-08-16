from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from gameshelf.bootstrap.release_runtime import ReleaseRuntimeConfig, RuntimeMode
from gameshelf.bootstrap.webview_bootstrapper import EvergreenRuntimeGuide
from gameshelf.bootstrap.webview_runtime import WebViewRuntime, WebViewRuntimeError


def test_source_runtime_does_not_require_bundled_webview(tmp_path: Path) -> None:
    webview = SimpleNamespace(settings={"WEBVIEW2_RUNTIME_PATH": None})
    runtime = WebViewRuntime.for_runtime(tmp_path, frozen=False)

    runtime.validate()
    prepared = runtime.prepare_windows10_permissions()
    runtime.configure(webview)

    assert runtime.path is None
    assert prepared is False
    assert webview.settings["WEBVIEW2_RUNTIME_PATH"] is None


def test_frozen_runtime_uses_executable_adjacent_directory(tmp_path: Path) -> None:
    app_root = tmp_path / "GameShelf"
    runtime_executable = app_root / "runtime" / "msedgewebview2.exe"
    runtime_executable.parent.mkdir(parents=True)
    runtime_executable.write_bytes(b"webview2")

    runtime = WebViewRuntime.for_runtime(
        app_root,
        frozen=True,
        release_config=ReleaseRuntimeConfig(RuntimeMode.FIXED),
        drive_type=lambda _path: 3,
        windows_build=22631,
        system_directory=tmp_path / "Windows" / "System32",
    )

    runtime.validate()

    assert runtime.path == app_root / "runtime"
    assert runtime.executable == runtime_executable


def test_frozen_runtime_rejects_missing_browser_executable(tmp_path: Path) -> None:
    runtime = WebViewRuntime.for_runtime(
        tmp_path,
        frozen=True,
        release_config=ReleaseRuntimeConfig(RuntimeMode.FIXED),
        drive_type=lambda _path: 3,
        windows_build=22631,
        system_directory=tmp_path / "Windows" / "System32",
    )

    with pytest.raises(WebViewRuntimeError, match="msedgewebview2.exe"):
        runtime.validate()


def test_frozen_runtime_rejects_unc_and_non_fixed_drives(tmp_path: Path) -> None:
    unc_runtime = WebViewRuntime.for_runtime(
        Path(r"\\server\share\GameShelf"),
        frozen=True,
        release_config=ReleaseRuntimeConfig(RuntimeMode.FIXED),
        drive_type=lambda _path: 3,
        windows_build=22631,
        system_directory=tmp_path / "Windows" / "System32",
    )
    local_runtime = tmp_path / "GameShelf" / "runtime"
    local_runtime.mkdir(parents=True)
    (local_runtime / "msedgewebview2.exe").write_bytes(b"webview2")
    removable_runtime = WebViewRuntime.for_runtime(
        local_runtime.parent,
        frozen=True,
        release_config=ReleaseRuntimeConfig(RuntimeMode.FIXED),
        drive_type=lambda _path: 2,
        windows_build=22631,
        system_directory=tmp_path / "Windows" / "System32",
    )

    with pytest.raises(WebViewRuntimeError, match="UNC|网络"):
        unc_runtime.validate()
    with pytest.raises(WebViewRuntimeError, match="本地固定磁盘"):
        removable_runtime.validate()


def test_windows_10_grants_runtime_permissions_once(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "GameShelf" / "runtime"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "msedgewebview2.exe").write_bytes(b"webview2")
    system_directory = tmp_path / "Windows" / "System32"
    system_directory.mkdir(parents=True)
    icacls = system_directory / "icacls.exe"
    icacls.write_bytes(b"icacls")
    calls: list[tuple[str, ...]] = []

    def run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        calls.append(tuple(command))
        return subprocess.CompletedProcess(command, 0, "processed", "")

    runtime = WebViewRuntime.for_runtime(
        runtime_dir.parent,
        frozen=True,
        release_config=ReleaseRuntimeConfig(RuntimeMode.FIXED),
        drive_type=lambda _path: 3,
        windows_build=19045,
        runner=run,
        system_directory=system_directory,
    )

    first = runtime.prepare_windows10_permissions()
    second = runtime.prepare_windows10_permissions()

    assert first is True
    assert second is False
    assert calls == [
        (
            str(icacls),
            str(runtime_dir),
            "/grant",
            "*S-1-15-2-2:(OI)(CI)(RX)",
        ),
        (
            str(icacls),
            str(runtime_dir),
            "/grant",
            "*S-1-15-2-1:(OI)(CI)(RX)",
        ),
    ]


def test_windows_11_does_not_change_runtime_permissions(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "GameShelf" / "runtime"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "msedgewebview2.exe").write_bytes(b"webview2")

    def unexpected_run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        raise AssertionError(f"unexpected command: {command}")

    runtime = WebViewRuntime.for_runtime(
        runtime_dir.parent,
        frozen=True,
        release_config=ReleaseRuntimeConfig(RuntimeMode.FIXED),
        drive_type=lambda _path: 3,
        windows_build=22631,
        runner=unexpected_run,
        system_directory=tmp_path / "Windows" / "System32",
    )

    assert runtime.prepare_windows10_permissions() is False


def test_windows_10_permission_failure_preserves_stderr(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "GameShelf" / "runtime"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "msedgewebview2.exe").write_bytes(b"webview2")
    system_directory = tmp_path / "Windows" / "System32"
    system_directory.mkdir(parents=True)
    (system_directory / "icacls.exe").write_bytes(b"icacls")

    def deny(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 5, "", "Access is denied")

    runtime = WebViewRuntime.for_runtime(
        runtime_dir.parent,
        frozen=True,
        release_config=ReleaseRuntimeConfig(RuntimeMode.FIXED),
        drive_type=lambda _path: 3,
        windows_build=19045,
        runner=deny,
        system_directory=system_directory,
    )

    with pytest.raises(WebViewRuntimeError, match="Access is denied"):
        runtime.prepare_windows10_permissions()


def test_configure_sets_fixed_runtime_before_webview_creation(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "GameShelf" / "runtime"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "msedgewebview2.exe").write_bytes(b"webview2")
    webview = SimpleNamespace(settings={"WEBVIEW2_RUNTIME_PATH": None})
    runtime = WebViewRuntime.for_runtime(
        runtime_dir.parent,
        frozen=True,
        release_config=ReleaseRuntimeConfig(RuntimeMode.FIXED),
        drive_type=lambda _path: 3,
        windows_build=22631,
        system_directory=tmp_path / "Windows" / "System32",
    )

    runtime.configure(webview)

    assert webview.settings["WEBVIEW2_RUNTIME_PATH"] == str(runtime_dir)


def test_fixed_runtime_ensure_available_validates_bundled_path(
    tmp_path: Path,
) -> None:
    runtime_dir = tmp_path / "GameShelf" / "runtime"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "msedgewebview2.exe").write_bytes(b"webview2")
    runtime = WebViewRuntime.for_runtime(
        runtime_dir.parent,
        frozen=True,
        release_config=ReleaseRuntimeConfig(RuntimeMode.FIXED),
        drive_type=lambda _path: 3,
        windows_build=22631,
        system_directory=tmp_path / "Windows" / "System32",
    )

    assert runtime.ensure_available(allow_manual_guide=False) is None


def test_evergreen_runtime_uses_system_and_never_sets_fixed_path(
    tmp_path: Path,
) -> None:
    class RecordingGuide:
        def __init__(self) -> None:
            self.calls: list[bool] = []

        def ensure_available(
            self,
            _config: ReleaseRuntimeConfig,
            *,
            allow_manual_guide: bool,
        ) -> str:
            self.calls.append(allow_manual_guide)
            return "151.0.4129.86"

    guide = RecordingGuide()
    config = ReleaseRuntimeConfig(
        RuntimeMode.EVERGREEN,
        tmp_path / "prerequisites" / "MicrosoftEdgeWebview2Setup.exe",
        "a" * 64,
    )
    webview = SimpleNamespace(settings={"WEBVIEW2_RUNTIME_PATH": "stale"})
    runtime = WebViewRuntime.for_runtime(
        tmp_path,
        frozen=True,
        release_config=config,
        evergreen_guide=cast(EvergreenRuntimeGuide, guide),
        drive_type=lambda _path: pytest.fail("drive type must not be inspected"),
    )

    assert (
        runtime.ensure_available(allow_manual_guide=True)
        == "151.0.4129.86"
    )
    assert guide.calls == [True]
    assert runtime.prepare_windows10_permissions() is False
    runtime.configure(webview)

    assert runtime.path is None
    assert webview.settings["WEBVIEW2_RUNTIME_PATH"] is None
