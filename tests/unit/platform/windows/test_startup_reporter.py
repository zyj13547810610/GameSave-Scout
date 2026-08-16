from __future__ import annotations

from pathlib import Path

from gameshelf.platform.windows.startup_reporter import (
    FrozenRuntimeInstallPrompt,
    FrozenStartupReporter,
)


def test_reporter_writes_log_and_shows_one_native_error(tmp_path: Path) -> None:
    calls: list[tuple[str, str, int]] = []

    def message_box(message: str, title: str, flags: int) -> int:
        calls.append((message, title, flags))
        return 1

    reporter = FrozenStartupReporter(message_box=message_box)

    log_file = reporter.show(RuntimeError("runtime missing"), tmp_path / "logs")

    assert log_file == tmp_path / "logs" / "startup-error.log"
    assert "runtime missing" in log_file.read_text(encoding="utf-8")
    assert len(calls) == 1
    message, title, flags = calls[0]
    assert "runtime missing" in message
    assert str(log_file) in message
    assert title == "GameShelf 启动失败"
    assert flags != 0


def test_reporter_failure_does_not_raise_or_hide_startup_error(tmp_path: Path) -> None:
    blocked_logs = tmp_path / "blocked"
    blocked_logs.write_text("not a directory", encoding="utf-8")

    def broken_message_box(_message: str, _title: str, _flags: int) -> int:
        raise OSError("message box unavailable")

    reporter = FrozenStartupReporter(message_box=broken_message_box)

    log_file = reporter.show(RuntimeError("original startup error"), blocked_logs)

    assert log_file is None


def test_runtime_prompt_explains_manual_install_and_restart() -> None:
    calls: list[tuple[str, str, int]] = []
    prompt = FrozenRuntimeInstallPrompt(
        message_box=lambda message, title, flags: calls.append(
            (message, title, flags)
        )
        or 6
    )

    assert prompt.confirm() is True
    message, title, flags = calls[0]
    assert "打开安装器所在文件夹" in message
    assert "双击 MicrosoftEdgeWebview2Setup.exe" in message
    assert "安装完成后重新启动 GameShelf" in message
    assert "联网" in message
    assert "Microsoft WebView2 Runtime" in message
    assert title == "GameShelf 需要 WebView2"
    assert flags & 0x00000004
    assert flags & 0x00000100


def test_runtime_prompt_returns_false_for_no() -> None:
    prompt = FrozenRuntimeInstallPrompt(message_box=lambda _message, _title, _flags: 7)

    assert prompt.confirm() is False


def test_runtime_prompt_returns_false_when_native_dialog_fails() -> None:
    def broken_message_box(_message: str, _title: str, _flags: int) -> int:
        raise OSError("message box unavailable")

    prompt = FrozenRuntimeInstallPrompt(message_box=broken_message_box)

    assert prompt.confirm() is False
