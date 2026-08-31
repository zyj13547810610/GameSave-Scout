from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import gamesave_scout.app as app_module
from gamesave_scout.app import _allow_window_close, _run_desktop
from gamesave_scout.bootstrap.application import Application
from gamesave_scout.bootstrap.release_runtime import ReleaseRuntimeConfig, RuntimeMode
from gamesave_scout.bootstrap.webview_runtime import WebViewRuntime


class FakeGuidedSaves:
    def __init__(self, allow: bool) -> None:
        self.allow = allow
        self.calls = 0

    def request_close(self) -> bool:
        self.calls += 1
        return self.allow


def test_window_close_is_allowed_without_an_active_guided_session() -> None:
    guided = FakeGuidedSaves(True)
    application = cast(Application, SimpleNamespace(guided_saves=guided))

    assert _allow_window_close(application) is True
    assert guided.calls == 1


def test_window_close_is_blocked_while_guided_session_awaits_resolution() -> None:
    guided = FakeGuidedSaves(False)
    application = cast(Application, SimpleNamespace(guided_saves=guided))

    assert _allow_window_close(application) is False
    assert guided.calls == 1


class EventHook:
    def __init__(self) -> None:
        self.handlers: list[object] = []

    def __iadd__(self, handler: object) -> EventHook:
        self.handlers.append(handler)
        return self


class DesktopGuidedSaves:
    def set_exit_callback(self, callback: object) -> None:
        self.exit_callback = callback

    def request_close(self) -> bool:
        return True


class FakeWebview:
    def __init__(self) -> None:
        self.settings: dict[str, object] = {"WEBVIEW2_RUNTIME_PATH": None}
        self.calls: list[tuple[str, object]] = []
        self.create_kwargs: dict[str, object] = {}
        self.screens = [
            SimpleNamespace(frame=SimpleNamespace(Width=1100, Height=700))
        ]
        self.window = SimpleNamespace(
            destroy=lambda: None,
            events=SimpleNamespace(closing=EventHook(), closed=EventHook()),
        )

    def create_window(self, *args: object, **kwargs: object) -> object:
        del args
        self.create_kwargs = kwargs
        self.calls.append(("create", self.settings["WEBVIEW2_RUNTIME_PATH"]))
        return self.window

    def start(self, **kwargs: object) -> None:
        self.calls.append(("start", kwargs))


def test_desktop_configures_fixed_runtime_and_forces_edgechromium(
    tmp_path: Path,
) -> None:
    runtime_dir = tmp_path / "GameSave-Scout" / "runtime"
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
    attached: list[object] = []
    closes: list[bool] = []
    application = cast(
        Application,
        SimpleNamespace(
            api=SimpleNamespace(attach_window=attached.append),
            guided_saves=DesktopGuidedSaves(),
            asset_address=SimpleNamespace(ui_url="http://127.0.0.1/ui"),
            paths=SimpleNamespace(webview_dir=tmp_path / "webview-data"),
            config=SimpleNamespace(
                current=SimpleNamespace(window_width=1800, window_height=1000)
            ),
            close=lambda: closes.append(True),
        ),
    )
    webview = FakeWebview()

    exit_code = _run_desktop(
        application,
        runtime,
        webview_module=webview,
    )

    assert exit_code == 0
    assert attached == [webview.window]
    assert closes == [True]
    assert webview.create_kwargs["width"] == 1100
    assert webview.create_kwargs["height"] == 700
    assert webview.calls == [
        ("create", str(runtime_dir)),
        (
            "start",
            {
                "debug": False,
                "private_mode": False,
                "storage_path": str(tmp_path / "webview-data"),
                "gui": "edgechromium",
            },
        ),
    ]


class RecordingWindowConfig:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.saved: list[tuple[object, object]] = []

    def set_window_size(self, width: object, height: object) -> None:
        if self.fail:
            raise OSError("read only")
        self.saved.append((width, height))


def _closing_application(
    *,
    allow: bool,
    config: RecordingWindowConfig,
) -> Application:
    return cast(
        Application,
        SimpleNamespace(
            guided_saves=FakeGuidedSaves(allow),
            config=config,
            logger=__import__("logging").getLogger("test-window-close"),
        ),
    )


def test_allowed_window_close_persists_restore_bounds() -> None:
    config = RecordingWindowConfig()
    application = _closing_application(allow=True, config=config)
    window = SimpleNamespace(
        native=SimpleNamespace(
            RestoreBounds=SimpleNamespace(Width=1500, Height=900),
            _scale=1.25,
            WindowState="Maximized",
        ),
        width=1100,
        height=700,
    )

    allowed = app_module._handle_window_closing(application, window)

    assert allowed is True
    assert config.saved == [(1200, 720)]


def test_blocked_window_close_does_not_persist_size() -> None:
    config = RecordingWindowConfig()
    application = _closing_application(allow=False, config=config)
    window = SimpleNamespace(native=None, width=1200, height=720)

    allowed = app_module._handle_window_closing(application, window)

    assert allowed is False
    assert config.saved == []


def test_window_size_save_failure_does_not_block_close(
    caplog,
) -> None:
    config = RecordingWindowConfig(fail=True)
    application = _closing_application(allow=True, config=config)
    window = SimpleNamespace(native=None, width=1200, height=720)

    allowed = app_module._handle_window_closing(application, window)

    assert allowed is True
    assert "无法保存窗口尺寸" in caplog.text
