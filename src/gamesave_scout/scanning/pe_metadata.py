"""Defensive PE header and version-resource inspection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pefile  # type: ignore[import-untyped]

type PeArchitecture = Literal["x86", "x64", "unknown"]


@dataclass(frozen=True)
class PeMetadata:
    product_name: str
    file_description: str
    company_name: str
    architecture: PeArchitecture


def read_pe_metadata(path: Path) -> PeMetadata:
    """Read metadata without loading or executing the target program."""
    empty = PeMetadata("", "", "", "unknown")
    pe: Any | None = None
    try:
        pe = pefile.PE(str(path), fast_load=True)
        architecture = _architecture(int(pe.FILE_HEADER.Machine))
        pe.parse_data_directories(
            directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]]
        )
        strings = _version_strings(getattr(pe, "FileInfo", []))
        return PeMetadata(
            product_name=strings.get("productname", ""),
            file_description=strings.get("filedescription", ""),
            company_name=strings.get("companyname", ""),
            architecture=architecture,
        )
    except (
        pefile.PEFormatError,
        OSError,
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
        UnicodeError,
    ):
        return empty
    finally:
        if pe is not None:
            pe.close()


def _architecture(machine: int) -> PeArchitecture:
    if machine == 0x014C:
        return "x86"
    if machine == 0x8664:
        return "x64"
    return "unknown"


def _version_strings(file_info: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in _flatten(file_info):
        if _decode(getattr(item, "Key", "")).casefold() != "stringfileinfo":
            continue
        for table in getattr(item, "StringTable", []):
            entries = getattr(table, "entries", {})
            for key, value in entries.items():
                result[_decode(key).casefold()] = _decode(value).strip("\x00 ")
    return result


def _flatten(values: Any) -> list[Any]:
    flattened: list[Any] = []
    for value in values or []:
        if isinstance(value, (list, tuple)):
            flattened.extend(_flatten(value))
        else:
            flattened.append(value)
    return flattened


def _decode(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)
