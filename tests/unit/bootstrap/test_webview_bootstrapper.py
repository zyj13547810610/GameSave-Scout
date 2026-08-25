from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import gamesave_scout.bootstrap.webview_bootstrapper as bootstrapper_module
from gamesave_scout.bootstrap.release_runtime import ReleaseRuntimeConfig, RuntimeMode
from gamesave_scout.bootstrap.webview_bootstrapper import (
    EvergreenRuntimeGuide,
    WebViewBootstrapperError,
    WebViewInstallCancelled,
    WebViewManualInstallRequired,
    detect_evergreen_version,
)


def test_existing_evergreen_skips_prompt_and_location_opener(tmp_path: Path) -> None:
    guide = EvergreenRuntimeGuide(
        detector=lambda: "151.0.4129.86",
        prompt=lambda: pytest.fail("prompt must not run"),
        opener=lambda _path: pytest.fail("Explorer must not open"),
    )

    version = guide.ensure_available(
        _evergreen_config(tmp_path),
        allow_manual_guide=True,
    )

    assert version == "151.0.4129.86"


def test_smoke_does_not_prompt_or_open_location(tmp_path: Path) -> None:
    guide = EvergreenRuntimeGuide(
        detector=lambda: None,
        prompt=lambda: pytest.fail("prompt must not run"),
        opener=lambda _path: pytest.fail("Explorer must not open"),
    )

    with pytest.raises(WebViewBootstrapperError, match="smoke.*不会打开安装位置"):
        guide.ensure_available(
            _evergreen_config(tmp_path),
            allow_manual_guide=False,
        )


def test_smoke_validates_bootstrapper_even_when_evergreen_exists(
    tmp_path: Path,
) -> None:
    config = _evergreen_config(tmp_path, payload=b"tampered")
    config = ReleaseRuntimeConfig(
        config.mode,
        config.bootstrapper_path,
        hashlib.sha256(b"official").hexdigest(),
    )
    guide = EvergreenRuntimeGuide(
        detector=lambda: "151.0.4129.86",
        prompt=lambda: pytest.fail("prompt must not run"),
        opener=lambda _path: pytest.fail("Explorer must not open"),
    )

    with pytest.raises(WebViewBootstrapperError, match="SHA-256 不匹配"):
        guide.ensure_available(config, allow_manual_guide=False)


def test_user_can_cancel_evergreen_install(tmp_path: Path) -> None:
    guide = EvergreenRuntimeGuide(
        detector=lambda: None,
        prompt=lambda: False,
        opener=lambda _path: pytest.fail("Explorer must not open"),
    )

    with pytest.raises(WebViewInstallCancelled):
        guide.ensure_available(
            _evergreen_config(tmp_path),
            allow_manual_guide=True,
        )


def test_missing_evergreen_opens_verified_bootstrapper_location(
    tmp_path: Path,
) -> None:
    config = _evergreen_config(tmp_path, payload=b"official bootstrapper")
    opened: list[Path] = []
    guide = EvergreenRuntimeGuide(
        detector=lambda: None,
        prompt=lambda: True,
        opener=opened.append,
    )

    with pytest.raises(WebViewManualInstallRequired):
        guide.ensure_available(config, allow_manual_guide=True)

    assert opened == [config.bootstrapper_path]


def test_invalid_bootstrapper_is_rejected_before_prompt(tmp_path: Path) -> None:
    config = _evergreen_config(tmp_path, payload=b"tampered")
    config = ReleaseRuntimeConfig(
        config.mode,
        config.bootstrapper_path,
        hashlib.sha256(b"official").hexdigest(),
    )
    guide = EvergreenRuntimeGuide(
        detector=lambda: None,
        prompt=lambda: pytest.fail("prompt must not run"),
        opener=lambda _path: pytest.fail("Explorer must not open"),
    )

    with pytest.raises(WebViewBootstrapperError, match="SHA-256 不匹配"):
        guide.ensure_available(config, allow_manual_guide=True)


def test_reparse_bootstrapper_is_rejected_before_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guide = EvergreenRuntimeGuide(
        detector=lambda: None,
        prompt=lambda: pytest.fail("prompt must not run"),
        opener=lambda _path: pytest.fail("Explorer must not open"),
    )
    monkeypatch.setattr(
        bootstrapper_module,
        "_is_reparse_point",
        lambda _path: True,
        raising=False,
    )

    with pytest.raises(WebViewBootstrapperError, match="重解析点"):
        guide.ensure_available(
            _evergreen_config(tmp_path),
            allow_manual_guide=True,
        )


def test_location_opener_selects_bootstrapper_with_system_explorer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    windows = tmp_path / "Windows"
    windows.mkdir()
    explorer = windows / "explorer.exe"
    explorer.write_bytes(b"explorer")
    bootstrapper = (
        tmp_path
        / "GameSave-Scout"
        / "prerequisites"
        / "MicrosoftEdgeWebview2Setup.exe"
    )
    bootstrapper.parent.mkdir(parents=True)
    bootstrapper.write_bytes(b"official")
    calls: list[tuple[Path, Path]] = []
    monkeypatch.setenv("WINDIR", str(windows))
    monkeypatch.setattr(
        bootstrapper_module,
        "_shell_execute_explorer",
        lambda executable, selected: calls.append((executable, selected)) or 33,
        raising=False,
    )

    bootstrapper_module._open_bootstrapper_location(bootstrapper)

    assert calls == [(explorer, bootstrapper)]


def test_location_opener_reports_shell_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    windows = tmp_path / "Windows"
    windows.mkdir()
    (windows / "explorer.exe").write_bytes(b"explorer")
    bootstrapper = tmp_path / "MicrosoftEdgeWebview2Setup.exe"
    bootstrapper.write_bytes(b"official")
    monkeypatch.setenv("WINDIR", str(windows))
    monkeypatch.setattr(
        bootstrapper_module,
        "_shell_execute_explorer",
        lambda _executable, _selected: 31,
        raising=False,
    )

    with pytest.raises(WebViewBootstrapperError, match="ShellExecuteW 返回 31"):
        bootstrapper_module._open_bootstrapper_location(bootstrapper)


def test_location_opener_wraps_shell_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    windows = tmp_path / "Windows"
    windows.mkdir()
    (windows / "explorer.exe").write_bytes(b"explorer")
    bootstrapper = tmp_path / "MicrosoftEdgeWebview2Setup.exe"
    bootstrapper.write_bytes(b"official")
    monkeypatch.setenv("WINDIR", str(windows))

    def fail_to_open(_executable: Path, _selected: Path) -> int:
        raise OSError("access denied")

    monkeypatch.setattr(
        bootstrapper_module,
        "_shell_execute_explorer",
        fail_to_open,
    )

    with pytest.raises(WebViewBootstrapperError, match="无法打开.*access denied"):
        bootstrapper_module._open_bootstrapper_location(bootstrapper)


def test_default_guide_uses_native_dependencies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        bootstrapper_module,
        "detect_evergreen_version",
        lambda: "151.0.4129.86",
    )

    guide = EvergreenRuntimeGuide()

    assert (
        guide.ensure_available(
            _evergreen_config(tmp_path),
            allow_manual_guide=True,
        )
        == "151.0.4129.86"
    )


def test_missing_bootstrapper_is_rejected_before_prompt(tmp_path: Path) -> None:
    config = _evergreen_config(tmp_path)
    assert config.bootstrapper_path is not None
    config.bootstrapper_path.unlink()
    guide = EvergreenRuntimeGuide(
        detector=lambda: None,
        prompt=lambda: pytest.fail("prompt must not run"),
        opener=lambda _path: pytest.fail("Explorer must not open"),
    )

    with pytest.raises(WebViewBootstrapperError, match="Bootstrapper 文件不存在"):
        guide.ensure_available(config, allow_manual_guide=True)


def test_bootstrapper_digest_mismatch_is_rejected_before_prompt(tmp_path: Path) -> None:
    config = _evergreen_config(tmp_path, payload=b"tampered")
    config = ReleaseRuntimeConfig(
        config.mode,
        config.bootstrapper_path,
        hashlib.sha256(b"official").hexdigest(),
    )
    guide = EvergreenRuntimeGuide(
        detector=lambda: None,
        prompt=lambda: pytest.fail("prompt must not run"),
        opener=lambda _path: pytest.fail("Explorer must not open"),
    )

    with pytest.raises(WebViewBootstrapperError, match="SHA-256 不匹配"):
        guide.ensure_available(config, allow_manual_guide=True)


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
