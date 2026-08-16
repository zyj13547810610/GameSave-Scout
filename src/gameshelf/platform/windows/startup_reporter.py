"""Native startup error reporting for a console-free frozen executable."""

from __future__ import annotations

import ctypes
import traceback
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_MESSAGE_BOX_FLAGS = 0x00000010 | 0x00002000
_IDYES = 6
_INSTALL_PROMPT_FLAGS = 0x00000004 | 0x00000020 | 0x00000100 | 0x00002000

type MessageBox = Callable[[str, str, int], int]


def _native_message_box(message: str, title: str, flags: int) -> int:
    user32: Any = ctypes.WinDLL("user32", use_last_error=True)
    message_box = user32.MessageBoxW
    message_box.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
    message_box.restype = ctypes.c_int
    return int(message_box(None, message, title, flags))


@dataclass
class FrozenRuntimeInstallPrompt:
    """Ask whether to open the verified manual installer location."""

    message_box: MessageBox = _native_message_box

    def confirm(self) -> bool:
        try:
            result = self.message_box(
                "系统未检测到 Microsoft WebView2 Runtime。\n\n"
                "GameShelf 将打开安装器所在文件夹。\n"
                "请双击 MicrosoftEdgeWebview2Setup.exe 联网完成安装，\n"
                "安装完成后重新启动 GameShelf。\n\n"
                "是否打开安装位置？",
                "GameShelf 需要 WebView2",
                _INSTALL_PROMPT_FLAGS,
            )
        except Exception:
            return False
        return result == _IDYES


@dataclass
class FrozenStartupReporter:
    """Persist a traceback when possible and show one native error dialog."""

    message_box: MessageBox = _native_message_box

    def show(self, error: BaseException, logs_dir: Path) -> Path | None:
        log_file = self._write_log(error, logs_dir)
        message = f"GameShelf 无法启动。\n\n{error}"
        if log_file is not None:
            message += f"\n\n诊断日志：{log_file}"
        else:
            message += "\n\n无法写入诊断日志，请将整个程序目录移动到可写位置。"
        with suppress(Exception):
            self.message_box(message, "GameShelf 启动失败", _MESSAGE_BOX_FLAGS)
        return log_file

    @staticmethod
    def _write_log(error: BaseException, logs_dir: Path) -> Path | None:
        try:
            logs_dir.mkdir(parents=True, exist_ok=True)
            log_file = logs_dir / "startup-error.log"
            formatted = "".join(
                traceback.format_exception(type(error), error, error.__traceback__)
            )
            with log_file.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(formatted)
                if not formatted.endswith("\n"):
                    stream.write("\n")
            return log_file
        except Exception:
            return None
