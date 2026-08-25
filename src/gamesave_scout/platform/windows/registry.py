"""Minimal Windows Registry access for save-location verification and navigation."""

from __future__ import annotations

import hashlib
import json
import subprocess
import winreg
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any


class RegistryOpenError(OSError):
    """A registry save location could not be opened."""


class UnsupportedRegistryKey(ValueError):
    """Raised when metadata enumeration targets a hive outside HKCU/HKLM."""


@dataclass(frozen=True, slots=True)
class RegistryValueMetadata:
    name: str
    type_name: str
    length: int
    sha256: str


@dataclass(frozen=True, slots=True)
class RegistryKeyMetadata:
    key: str
    values: tuple[RegistryValueMetadata, ...]
    available: bool


@dataclass(frozen=True, slots=True)
class RegistryMetadataEnumeration:
    keys: tuple[RegistryKeyMetadata, ...]
    truncated: bool


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

    def iter_metadata(
        self,
        key: str,
        *,
        max_subkey_depth: int = 4,
        max_keys: int = 256,
        max_values: int = 2048,
    ) -> RegistryMetadataEnumeration:
        if max_subkey_depth < 0 or max_keys < 1 or max_values < 1:
            raise ValueError("Registry metadata limits are invalid.")
        root_name, root, suffix = self._split_metadata_key(key)
        stack: list[tuple[str, int]] = [(suffix, 0)]
        collected: list[RegistryKeyMetadata] = []
        value_count = 0
        truncated = False

        while stack:
            current_suffix, depth = stack.pop()
            if len(collected) >= max_keys:
                truncated = True
                break
            canonical_key = f"{root_name}\\{current_suffix}"
            try:
                handle_context = self._registry.OpenKey(root, current_suffix)
            except (FileNotFoundError, OSError):
                collected.append(RegistryKeyMetadata(canonical_key, (), False))
                continue
            with handle_context as handle:
                values: list[RegistryValueMetadata] = []
                value_index = 0
                while True:
                    try:
                        name, raw_value, value_type = self._registry.EnumValue(
                            handle, value_index
                        )
                    except OSError:
                        break
                    value_index += 1
                    if value_count >= max_values:
                        truncated = True
                        break
                    values.append(
                        _value_metadata(self._registry, name, raw_value, value_type)
                    )
                    value_count += 1

                subkeys: list[str] = []
                subkey_index = 0
                while True:
                    try:
                        subkey = self._registry.EnumKey(handle, subkey_index)
                    except OSError:
                        break
                    subkey_index += 1
                    if depth >= max_subkey_depth:
                        truncated = True
                        continue
                    subkeys.append(str(subkey))
            collected.append(
                RegistryKeyMetadata(
                    canonical_key,
                    tuple(sorted(values, key=lambda item: item.name.casefold())),
                    True,
                )
            )
            for subkey in sorted(subkeys, key=str.casefold, reverse=True):
                stack.append((f"{current_suffix}\\{subkey}", depth + 1))

        return RegistryMetadataEnumeration(tuple(collected), truncated)

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

    def _split_metadata_key(self, key: str) -> tuple[str, object, str]:
        root_name, separator, suffix = key.replace("/", "\\").partition("\\")
        canonical_root = root_name.upper()
        roots = {
            "HKEY_CURRENT_USER": self._registry.HKEY_CURRENT_USER,
            "HKEY_LOCAL_MACHINE": self._registry.HKEY_LOCAL_MACHINE,
        }
        if not separator or not suffix or canonical_root not in roots:
            raise UnsupportedRegistryKey(key)
        return canonical_root, roots[canonical_root], suffix


def _value_metadata(
    registry_api: Any, name: object, raw_value: object, value_type: object
) -> RegistryValueMetadata:
    type_name = _type_name(registry_api, value_type)
    value_bytes = _value_bytes(raw_value)
    digest = hashlib.sha256(type_name.encode("ascii") + b"\0" + value_bytes).hexdigest()
    return RegistryValueMetadata(str(name), type_name, len(value_bytes), digest)


def _type_name(registry_api: Any, value_type: object) -> str:
    names = (
        "REG_NONE",
        "REG_SZ",
        "REG_EXPAND_SZ",
        "REG_BINARY",
        "REG_DWORD",
        "REG_MULTI_SZ",
        "REG_QWORD",
    )
    for name in names:
        if getattr(registry_api, name, object()) == value_type:
            return name
    return f"REG_TYPE_{value_type}"


def _value_bytes(value: object) -> bytes:
    if value is None:
        return b""
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, int):
        return str(value).encode("ascii")
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return "\0".join(value).encode("utf-8")
    return json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")


def _spawn(command: Sequence[str]) -> object:
    return subprocess.Popen(list(command))
