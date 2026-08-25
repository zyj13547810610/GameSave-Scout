"""Narrow Windows shell integration."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from urllib.parse import urlsplit

_EXTERNAL_HOSTS = frozenset({"vndb.org", "www.dlsite.com", "2dfan.com"})


class DirectoryOpenError(OSError):
    """Raised when a directory cannot safely be handed to Windows Explorer."""


class UrlOpenError(OSError):
    """Raised when an external URL is unsafe or cannot be opened."""


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

    def open_url(self, url: str) -> None:
        if not isinstance(url, str) or not url:
            raise UrlOpenError("External URL is invalid.")
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError as error:
            raise UrlOpenError("External URL is invalid.") from error
        if (
            parsed.scheme != "https"
            or parsed.hostname not in _EXTERNAL_HOSTS
            or parsed.username is not None
            or parsed.password is not None
            or port is not None
        ):
            raise UrlOpenError("External URL is not allowlisted.")
        try:
            self._start_file(url)
        except OSError as error:
            raise UrlOpenError("Windows could not open external URL.") from error


def _spawn(command: Sequence[str]) -> object:
    return subprocess.Popen(list(command))
