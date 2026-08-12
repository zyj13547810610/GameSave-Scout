"""Resolve Windows known folders without persisting machine-specific paths."""

from __future__ import annotations

import ctypes
import ntpath
import os
from collections.abc import Callable, Mapping
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class KnownFolders:
    home: Path
    app_data: Path
    local_app_data: Path
    local_app_data_low: Path
    documents: Path
    saved_games: Path
    program_data: Path
    public: Path
    windows: Path


class KnownFolderError(RuntimeError):
    """A Windows known-folder lookup failed with a stable application code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class _GUID(ctypes.Structure):
    _fields_ = [
        ("data1", wintypes.DWORD),
        ("data2", wintypes.WORD),
        ("data3", wintypes.WORD),
        ("data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def from_uuid(cls, value: UUID) -> _GUID:
        return cls.from_buffer_copy(value.bytes_le)


_FOLDER_IDS = {
    "profile": UUID("5e6c858f-0e22-4760-9afe-ea3317b67173"),
    "app_data": UUID("3eb685db-65f9-4cf6-a03a-e3ef65729f3d"),
    "local_app_data": UUID("f1b32785-6fba-4fcf-9d55-7b8e7f157091"),
    "documents": UUID("fdd39ad0-238f-46af-adb4-6c85480369c7"),
    "saved_games": UUID("4c5c32ff-bb9d-43b0-b5b4-2d72e54eaaa4"),
    "public": UUID("dfdf76a2-c82a-4d63-906a-5644ac457385"),
    "windows": UUID("f38bf404-1d43-42f2-9305-67de0b28fc23"),
}


def _native_known_folder_lookup(name: str) -> Path:
    folder_id = _FOLDER_IDS[name]
    shell32: Any = ctypes.WinDLL("shell32", use_last_error=True)
    ole32: Any = ctypes.WinDLL("ole32", use_last_error=True)
    query: Any = shell32.SHGetKnownFolderPath
    query.argtypes = [
        ctypes.POINTER(_GUID),
        wintypes.DWORD,
        wintypes.HANDLE,
        ctypes.POINTER(ctypes.c_wchar_p),
    ]
    query.restype = ctypes.c_long
    free: Any = ole32.CoTaskMemFree
    free.argtypes = [ctypes.c_void_p]
    free.restype = None

    guid = _GUID.from_uuid(folder_id)
    result_path = ctypes.c_wchar_p()
    result = int(query(ctypes.byref(guid), 0, None, ctypes.byref(result_path)))
    if result != 0:
        unsigned_result = result & 0xFFFFFFFF
        raise OSError(f"SHGetKnownFolderPath({name}) failed: HRESULT 0x{unsigned_result:08X}")

    try:
        if not result_path.value:
            raise OSError(f"SHGetKnownFolderPath({name}) returned an empty path")
        return Path(result_path.value)
    finally:
        free(result_path)


class WindowsKnownFolderProvider:
    """Load the Windows folders used by portable save-path templates."""

    def __init__(
        self,
        *,
        folder_lookup: Callable[[str], Path] | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._folder_lookup = folder_lookup or _native_known_folder_lookup
        self._environ = os.environ if environ is None else environ

    def load(self) -> KnownFolders:
        try:
            home = self._folder_lookup("profile")
            app_data = self._folder_lookup("app_data")
            local_app_data = self._folder_lookup("local_app_data")
            documents = self._folder_lookup("documents")
            saved_games = self._folder_lookup("saved_games")
            public = self._folder_lookup("public")
            windows = self._folder_lookup("windows")
        except (KeyError, OSError, RuntimeError) as error:
            raise KnownFolderError(
                "known_folder_lookup_failed",
                "无法读取 Windows 已知文件夹。",
            ) from error

        program_data_text = self._environ.get("PROGRAMDATA", "").strip()
        if not program_data_text or not ntpath.isabs(program_data_text):
            raise KnownFolderError(
                "invalid_program_data",
                "PROGRAMDATA 未设置为绝对路径。",
            )

        return KnownFolders(
            home=home,
            app_data=app_data,
            local_app_data=local_app_data,
            local_app_data_low=local_app_data.parent / "LocalLow",
            documents=documents,
            saved_games=saved_games,
            program_data=Path(program_data_text),
            public=public,
            windows=windows,
        )
