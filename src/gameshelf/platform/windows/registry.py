"""Minimal Windows Registry access for save-location verification and navigation."""

from __future__ import annotations

import subprocess
import winreg
from collections.abc import Callable, Sequence
from typing import Any


class RegistryOpenError(OSError):
    """A registry save location could not be opened."""


class WindowsRegistry:
    def __init__(
        self,
        *,
        registry_api: Any = winreg,
        spawn: Callable[[Sequence[str]], object] | None = None,
    ) -> None:
        self._registry = registry_api
        self._spawn = spawn or _spawn

    def key_exists(self, key: str) -> bool:
        parsed = self._split_key(key)
        if parsed is None:
            return False
        root, suffix = parsed
        try:
            with self._registry.OpenKey(root, suffix):
                return True
        except (FileNotFoundError, OSError):
            return False

    def open_key(self, key: str) -> None:
        if self._split_key(key) is None:
            raise RegistryOpenError(f"Unsupported registry key: {key}")
        try:
            with self._registry.CreateKey(
                self._registry.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Applets\Regedit",
            ) as handle:
                self._registry.SetValueEx(
                    handle,
                    "LastKey",
                    0,
                    self._registry.REG_SZ,
                    key,
                )
            self._spawn(("regedit.exe",))
        except OSError as error:
            raise RegistryOpenError(f"Windows could not open registry key: {key}") from error

    def _split_key(self, key: str) -> tuple[object, str] | None:
        root_name, separator, suffix = key.partition("\\")
        if not separator or not suffix:
            return None
        roots = {
            "HKEY_CURRENT_USER": self._registry.HKEY_CURRENT_USER,
            "HKEY_LOCAL_MACHINE": self._registry.HKEY_LOCAL_MACHINE,
            "HKEY_CLASSES_ROOT": self._registry.HKEY_CLASSES_ROOT,
            "HKEY_USERS": self._registry.HKEY_USERS,
        }
        root = roots.get(root_name.upper())
        return None if root is None else (root, suffix)


def _spawn(command: Sequence[str]) -> object:
    return subprocess.Popen(list(command))
