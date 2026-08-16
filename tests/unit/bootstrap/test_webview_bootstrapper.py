from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

import pytest

import gameshelf.bootstrap.webview_bootstrapper as bootstrapper_module
from gameshelf.bootstrap.release_runtime import ReleaseRuntimeConfig, RuntimeMode
from gameshelf.bootstrap.webview_bootstrapper import (
    EvergreenRuntimeInstaller,
    WebViewBootstrapperError,
    WebViewInstallCancelled,
    _run_bootstrapper,
    detect_evergreen_version,
)


def test_existing_evergreen_skips_prompt_and_installer(tmp_path: Path) -> None:
    installer = EvergreenRuntimeInstaller(
        detector=lambda: "151.0.4129.86",
        prompt=lambda: pytest.fail("prompt must not run"),
        runner=lambda _command: pytest.fail("installer must not run"),
    )

    version = installer.ensure_available(_evergreen_config(tmp_path), allow_install=True)

    assert version == "151.0.4129.86"


def test_smoke_does_not_prompt_or_run_installer(tmp_path: Path) -> None:
    installer = EvergreenRuntimeInstaller(
        detector=lambda: None,
        prompt=lambda: pytest.fail("prompt must not run"),
        runner=lambda _command: pytest.fail("installer must not run"),
    )

    with pytest.raises(WebViewBootstrapperError, match="smoke.*不会运行安装器"):
        installer.ensure_available(_evergreen_config(tmp_path), allow_install=False)


def test_smoke_validates_bootstrapper_even_when_evergreen_exists(
    tmp_path: Path,
) -> None:
    config = _evergreen_config(tmp_path, payload=b"tampered")
    config = ReleaseRuntimeConfig(
        config.mode,
        config.bootstrapper_path,
        hashlib.sha256(b"official").hexdigest(),
    )
    installer = EvergreenRuntimeInstaller(
        detector=lambda: "151.0.4129.86",
        prompt=lambda: pytest.fail("prompt must not run"),
        runner=lambda _command: pytest.fail("installer must not run"),
    )

    with pytest.raises(WebViewBootstrapperError, match="SHA-256 不匹配"):
        installer.ensure_available(config, allow_install=False)


def test_user_can_cancel_evergreen_install(tmp_path: Path) -> None:
    installer = EvergreenRuntimeInstaller(
        detector=lambda: None,
        prompt=lambda: False,
        runner=lambda _command: pytest.fail("installer must not run"),
    )

    with pytest.raises(WebViewInstallCancelled):
        installer.ensure_available(_evergreen_config(tmp_path), allow_install=True)


def test_missing_evergreen_installs_and_rechecks_in_same_call(tmp_path: Path) -> None:
    config = _evergreen_config(tmp_path, payload=b"official bootstrapper")
    detected = iter((None, None, "151.0.4129.86"))
    commands: list[tuple[str, ...]] = []
    installer = EvergreenRuntimeInstaller(
        detector=lambda: next(detected),
        prompt=lambda: True,
        runner=lambda command: commands.append(tuple(command))
        or subprocess.CompletedProcess(command, 0, "", ""),
        monotonic=_monotonic(0.0, 0.1, 0.2),
        sleeper=lambda _seconds: None,
        timeout_seconds=1.0,
    )

    version = installer.ensure_available(config, allow_install=True)

    assert version == "151.0.4129.86"
    assert commands == [(str(config.bootstrapper_path), "/silent", "/install")]


def test_missing_bootstrapper_is_rejected_before_process_start(tmp_path: Path) -> None:
    config = _evergreen_config(tmp_path)
    assert config.bootstrapper_path is not None
    config.bootstrapper_path.unlink()
    installer = EvergreenRuntimeInstaller(
        detector=lambda: None,
        prompt=lambda: True,
        runner=lambda _command: pytest.fail("installer must not run"),
    )

    with pytest.raises(WebViewBootstrapperError, match="Bootstrapper 文件不存在"):
        installer.ensure_available(config, allow_install=True)


def test_bootstrapper_digest_mismatch_is_rejected(tmp_path: Path) -> None:
    config = _evergreen_config(tmp_path, payload=b"tampered")
    config = ReleaseRuntimeConfig(
        config.mode,
        config.bootstrapper_path,
        hashlib.sha256(b"official").hexdigest(),
    )
    installer = EvergreenRuntimeInstaller(
        detector=lambda: None,
        prompt=lambda: True,
        runner=lambda _command: pytest.fail("installer must not run"),
    )

    with pytest.raises(WebViewBootstrapperError, match="SHA-256 不匹配"):
        installer.ensure_available(config, allow_install=True)


def test_installer_failure_preserves_stdout_and_stderr(tmp_path: Path) -> None:
    installer = EvergreenRuntimeInstaller(
        detector=lambda: None,
        prompt=lambda: True,
        runner=lambda command: subprocess.CompletedProcess(
            command,
            7,
            "installer output",
            "installer error",
        ),
    )

    with pytest.raises(WebViewBootstrapperError) as raised:
        installer.ensure_available(_evergreen_config(tmp_path), allow_install=True)

    message = str(raised.value)
    assert "退出码 7" in message
    assert "installer output" in message
    assert "installer error" in message


def test_install_times_out_when_runtime_remains_missing(tmp_path: Path) -> None:
    installer = EvergreenRuntimeInstaller(
        detector=lambda: None,
        prompt=lambda: True,
        runner=lambda command: subprocess.CompletedProcess(command, 0, "", ""),
        monotonic=_monotonic(0.0, 0.5, 1.0),
        sleeper=lambda _seconds: None,
        timeout_seconds=1.0,
    )

    with pytest.raises(WebViewBootstrapperError, match="安装完成后.*仍未检测到"):
        installer.ensure_available(_evergreen_config(tmp_path), allow_install=True)


def test_bootstrapper_process_disables_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def fake_run(
        command: Sequence[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        calls.append((tuple(command), kwargs))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = _run_bootstrapper(("setup.exe", "/silent", "/install"))

    assert result.returncode == 0
    assert calls[0][0] == ("setup.exe", "/silent", "/install")
    assert calls[0][1]["shell"] is False


def test_detector_returns_none_only_for_runtime_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RuntimeNotFoundError(Exception):
        pass

    class MissingEnvironment:
        @staticmethod
        def GetAvailableBrowserVersionString() -> str:
            raise RuntimeNotFoundError

    monkeypatch.setattr(
        bootstrapper_module,
        "_load_core_webview2_environment",
        lambda: (MissingEnvironment, RuntimeNotFoundError),
    )

    assert detect_evergreen_version() is None


def test_detector_wraps_unexpected_clr_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RuntimeNotFoundError(Exception):
        pass

    class BrokenEnvironment:
        @staticmethod
        def GetAvailableBrowserVersionString() -> str:
            raise OSError("CLR failed")

    monkeypatch.setattr(
        bootstrapper_module,
        "_load_core_webview2_environment",
        lambda: (BrokenEnvironment, RuntimeNotFoundError),
    )

    with pytest.raises(WebViewBootstrapperError, match="检测.*CLR failed"):
        detect_evergreen_version()


def _evergreen_config(
    tmp_path: Path,
    payload: bytes = b"official bootstrapper",
) -> ReleaseRuntimeConfig:
    bootstrapper = tmp_path / "prerequisites" / "MicrosoftEdgeWebview2Setup.exe"
    bootstrapper.parent.mkdir(parents=True)
    bootstrapper.write_bytes(payload)
    return ReleaseRuntimeConfig(
        RuntimeMode.EVERGREEN,
        bootstrapper,
        hashlib.sha256(payload).hexdigest(),
    )


def _monotonic(*values: float) -> Callable[[], float]:
    iterator: Iterator[float] = iter(values)

    def read() -> float:
        try:
            return next(iterator)
        except StopIteration:
            pytest.fail("monotonic clock exhausted")

    return read
