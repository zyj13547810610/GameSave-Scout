from __future__ import annotations

import hashlib
import json
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass
from typing import Any

import pytest

from gameshelf.platform.windows.registry import (
    UnsupportedRegistryKey,
    WindowsRegistry,
)
from gameshelf.saves.guided_registry import (
    RegistryMetadataReader,
    diff_registry_snapshots,
)


def test_registry_snapshot_hashes_values_without_retaining_raw_data() -> None:
    registry_api = FakeMetadataWinreg()
    key = r"HKEY_CURRENT_USER\Software\Game"
    registry_api.add_key(
        registry_api.HKEY_CURRENT_USER,
        r"Software\Game",
        values=(
            ("Token", "secret-save-value", registry_api.REG_SZ),
            ("Slot", 7, registry_api.REG_DWORD),
            ("Blob", b"\x00\x01", registry_api.REG_BINARY),
        ),
    )
    reader = RegistryMetadataReader(WindowsRegistry(registry_api=registry_api))

    snapshot = reader.snapshot((key,))
    encoded = json.dumps(asdict(snapshot), ensure_ascii=False)
    values = snapshot.targets[0].keys[0].values
    token = next(value for value in values if value.name == "Token")

    assert "secret-save-value" not in encoded
    assert "0001" not in encoded
    assert token.sha256 == hashlib.sha256(
        b"REG_SZ\0secret-save-value"
    ).hexdigest()
    assert token.length == len(b"secret-save-value")
    assert {(value.name, value.type_name) for value in values} == {
        ("Blob", "REG_BINARY"),
        ("Slot", "REG_DWORD"),
        ("Token", "REG_SZ"),
    }


def test_registry_enumeration_is_bounded_and_only_accepts_hkcu_or_hklm() -> None:
    registry_api = FakeMetadataWinreg()
    registry_api.add_key(
        registry_api.HKEY_CURRENT_USER,
        r"Software\Game",
        values=(("One", "1", registry_api.REG_SZ), ("Two", "2", registry_api.REG_SZ)),
        subkeys=("Child",),
    )
    registry_api.add_key(
        registry_api.HKEY_CURRENT_USER,
        r"Software\Game\Child",
        values=(("Three", "3", registry_api.REG_SZ),),
    )
    registry = WindowsRegistry(registry_api=registry_api)

    enumeration = registry.iter_metadata(
        r"HKEY_CURRENT_USER\Software\Game",
        max_subkey_depth=0,
        max_keys=1,
        max_values=1,
    )

    assert enumeration.truncated is True
    assert len(enumeration.keys) == 1
    assert len(enumeration.keys[0].values) == 1
    with pytest.raises(UnsupportedRegistryKey):
        registry.iter_metadata(r"HKEY_USERS\Alice\Software\Game")


def test_registry_diff_uses_approved_root_and_never_preselects_candidate() -> None:
    registry_api = FakeMetadataWinreg()
    key = r"HKEY_CURRENT_USER\Software\Game"
    registry_api.add_key(
        registry_api.HKEY_CURRENT_USER,
        r"Software\Game",
        values=(("Slot", "before-secret", registry_api.REG_SZ),),
    )
    reader = RegistryMetadataReader(WindowsRegistry(registry_api=registry_api))
    before = reader.snapshot((key,))
    registry_api.add_key(
        registry_api.HKEY_CURRENT_USER,
        r"Software\Game",
        values=(
            ("Slot", "after-secret", registry_api.REG_SZ),
            ("Profile", "created-secret", registry_api.REG_SZ),
        ),
    )
    after = reader.snapshot((key,))

    drafts = diff_registry_snapshots(before, after)
    encoded = json.dumps([asdict(draft) for draft in drafts], ensure_ascii=False)

    assert len(drafts) == 1
    assert drafts[0].candidate_template == key
    assert drafts[0].display_path == key
    assert drafts[0].kind == "registry"
    assert drafts[0].preselected is False
    assert "before-secret" not in encoded
    assert "after-secret" not in encoded
    assert "created-secret" not in encoded
    assert any("Profile" in item for item in drafts[0].evidence)
    assert any("Slot" in item for item in drafts[0].evidence)


@dataclass
class FakeKeyHandle(AbstractContextManager["FakeKeyHandle"]):
    root: int
    suffix: str

    def __exit__(self, *_args: object) -> None:
        return None


class FakeMetadataWinreg:
    HKEY_CURRENT_USER = 1
    HKEY_LOCAL_MACHINE = 2
    HKEY_CLASSES_ROOT = 3
    HKEY_USERS = 4
    REG_NONE = 0
    REG_SZ = 1
    REG_EXPAND_SZ = 2
    REG_BINARY = 3
    REG_DWORD = 4
    REG_MULTI_SZ = 7
    REG_QWORD = 11

    def __init__(self) -> None:
        self._keys: dict[
            tuple[int, str],
            tuple[tuple[tuple[str, Any, int], ...], tuple[str, ...]],
        ] = {}

    def add_key(
        self,
        root: int,
        suffix: str,
        *,
        values: tuple[tuple[str, Any, int], ...] = (),
        subkeys: tuple[str, ...] = (),
    ) -> None:
        self._keys[(root, suffix)] = (values, subkeys)

    def OpenKey(self, root: int, suffix: str) -> FakeKeyHandle:
        if (root, suffix) not in self._keys:
            raise FileNotFoundError(suffix)
        return FakeKeyHandle(root, suffix)

    def EnumValue(self, handle: FakeKeyHandle, index: int) -> tuple[str, Any, int]:
        values = self._keys[(handle.root, handle.suffix)][0]
        if index >= len(values):
            raise OSError("no more values")
        return values[index]

    def EnumKey(self, handle: FakeKeyHandle, index: int) -> str:
        subkeys = self._keys[(handle.root, handle.suffix)][1]
        if index >= len(subkeys):
            raise OSError("no more subkeys")
        return subkeys[index]
