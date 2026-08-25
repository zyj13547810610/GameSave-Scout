from collections.abc import Mapping
from pathlib import Path

import pytest

from gamesave_scout.platform.windows.known_folders import (
    KnownFolderError,
    WindowsKnownFolderProvider,
)


def _folder_values() -> Mapping[str, Path]:
    return {
        "profile": Path(r"C:\Users\Alice"),
        "app_data": Path(r"C:\Users\Alice\AppData\Roaming"),
        "local_app_data": Path(r"C:\Users\Alice\AppData\Local"),
        "documents": Path(r"C:\Users\Alice\Documents"),
        "saved_games": Path(r"C:\Users\Alice\Saved Games"),
        "public": Path(r"C:\Users\Public"),
        "windows": Path(r"C:\Windows"),
    }


def test_provider_loads_known_folders_and_derives_local_low() -> None:
    values = _folder_values()
    provider = WindowsKnownFolderProvider(
        folder_lookup=lambda name: values[name],
        environ={"PROGRAMDATA": r"C:\ProgramData"},
    )

    folders = provider.load()

    assert folders.home == Path(r"C:\Users\Alice")
    assert folders.local_app_data_low == Path(r"C:\Users\Alice\AppData\LocalLow")
    assert folders.program_data == Path(r"C:\ProgramData")


@pytest.mark.parametrize("program_data", [None, "ProgramData", ""])
def test_provider_rejects_missing_or_relative_program_data(program_data: str | None) -> None:
    values = _folder_values()
    environ = {} if program_data is None else {"PROGRAMDATA": program_data}
    provider = WindowsKnownFolderProvider(
        folder_lookup=lambda name: values[name],
        environ=environ,
    )

    with pytest.raises(KnownFolderError) as caught:
        provider.load()

    assert caught.value.code == "invalid_program_data"


def test_provider_wraps_lookup_errors_with_stable_code() -> None:
    def fail_lookup(name: str) -> Path:
        raise OSError(f"cannot load {name}")

    provider = WindowsKnownFolderProvider(
        folder_lookup=fail_lookup,
        environ={"PROGRAMDATA": r"C:\ProgramData"},
    )

    with pytest.raises(KnownFolderError) as caught:
        provider.load()

    assert caught.value.code == "known_folder_lookup_failed"
