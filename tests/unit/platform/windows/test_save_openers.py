from contextlib import nullcontext
from pathlib import Path

import pytest

from gamesave_scout.platform.windows.registry import WindowsRegistry
from gamesave_scout.platform.windows.shell import (
    DirectoryOpenError,
    UrlOpenError,
    WindowsShell,
)


def test_shell_reveals_existing_file_with_explorer_select(tmp_path: Path) -> None:
    save_file = tmp_path / "slot 1.sav"
    save_file.write_bytes(b"save")
    spawned: list[tuple[str, ...]] = []
    shell = WindowsShell(
        start_file=lambda _path: None,
        spawn=lambda command: spawned.append(tuple(command)),
    )

    shell.reveal_file(save_file)

    assert spawned == [("explorer.exe", f"/select,{save_file}")]


def test_shell_rejects_missing_file_before_starting_explorer(tmp_path: Path) -> None:
    shell = WindowsShell(
        start_file=lambda _path: None,
        spawn=lambda _command: None,
    )

    with pytest.raises(DirectoryOpenError, match="File does not exist"):
        shell.reveal_file(tmp_path / "missing.sav")


def test_shell_opens_allowlisted_https_url() -> None:
    opened: list[str] = []
    shell = WindowsShell(
        start_file=lambda path: opened.append(path),
        spawn=lambda _command: None,
    )

    shell.open_url("https://vndb.org/v?q=Alice")

    assert opened == ["https://vndb.org/v?q=Alice"]


@pytest.mark.parametrize(
    "url",
    (
        "http://vndb.org/v?q=Alice",
        "https://evil.example/v?q=Alice",
        "https://user:password@vndb.org/v?q=Alice",
        "https://vndb.org.evil.example/v?q=Alice",
    ),
)
def test_shell_rejects_unsafe_external_url(url: str) -> None:
    opened: list[str] = []
    shell = WindowsShell(
        start_file=lambda path: opened.append(path),
        spawn=lambda _command: None,
    )

    with pytest.raises(UrlOpenError):
        shell.open_url(url)

    assert opened == []


class FakeWinreg:
    HKEY_CURRENT_USER = 1
    HKEY_LOCAL_MACHINE = 2
    HKEY_CLASSES_ROOT = 3
    HKEY_USERS = 4
    REG_SZ = 1

    def __init__(self) -> None:
        self.existing = {(self.HKEY_CURRENT_USER, r"Software\Studio\Alice")}
        self.last_key = ""

    def OpenKey(self, root: int, suffix: str):
        if (root, suffix) not in self.existing:
            raise FileNotFoundError(suffix)
        return nullcontext()

    def CreateKey(self, root: int, suffix: str):
        assert root == self.HKEY_CURRENT_USER
        assert suffix == r"Software\Microsoft\Windows\CurrentVersion\Applets\Regedit"
        return nullcontext()

    def SetValueEx(
        self,
        _handle: object,
        name: str,
        _reserved: int,
        value_type: int,
        value: str,
    ) -> None:
        assert name == "LastKey"
        assert value_type == self.REG_SZ
        self.last_key = value


def test_registry_checks_and_opens_canonical_key() -> None:
    registry_api = FakeWinreg()
    spawned: list[tuple[str, ...]] = []
    registry = WindowsRegistry(
        registry_api=registry_api,
        spawn=lambda command: spawned.append(tuple(command)),
    )
    key = r"HKEY_CURRENT_USER\Software\Studio\Alice"

    assert registry.key_exists(key) is True
    assert registry.key_exists(r"HKEY_CURRENT_USER\Software\Missing") is False
    registry.open_key(key)

    assert registry_api.last_key == key
    assert spawned == [("regedit.exe",)]
