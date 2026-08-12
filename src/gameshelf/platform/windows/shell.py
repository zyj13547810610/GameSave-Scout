"""Narrow Windows shell integration."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path


class DirectoryOpenError(OSError):
    """Raised when a directory cannot safely be handed to Windows Explorer."""


class WindowsShell:
    def __init__(
        self,
        *,
        start_file: Callable[[str], object] | None = None,
        spawn: Callable[[Sequence[str]], object] | None = None,
    ) -> None:
        self._start_file = start_file or os.startfile
        self._spawn = spawn or _spawn

    def open_directory(self, path: Path) -> None:
        if not path.is_dir():
            raise DirectoryOpenError(f"Directory does not exist: {path}")
        try:
            self._start_file(str(path))
        except OSError as error:
            raise DirectoryOpenError(f"Windows could not open directory: {path}") from error

    def reveal_file(self, path: Path) -> None:
        if not path.is_file():
            raise DirectoryOpenError(f"File does not exist: {path}")
        try:
            self._spawn(("explorer.exe", f"/select,{path}"))
        except OSError as error:
            raise DirectoryOpenError(f"Windows could not reveal file: {path}") from error


def _spawn(command: Sequence[str]) -> object:
    return subprocess.Popen(list(command))
