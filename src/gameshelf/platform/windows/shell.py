"""Narrow Windows shell integration."""

from __future__ import annotations

import os
from pathlib import Path


class DirectoryOpenError(OSError):
    """Raised when a directory cannot safely be handed to Windows Explorer."""


class WindowsShell:
    def open_directory(self, path: Path) -> None:
        if not path.is_dir():
            raise DirectoryOpenError(f"Directory does not exist: {path}")
        try:
            os.startfile(str(path))
        except OSError as error:
            raise DirectoryOpenError(f"Windows could not open directory: {path}") from error
