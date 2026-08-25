"""Strictly bounded binary and text reads for untrusted game files."""

from __future__ import annotations

import codecs
from pathlib import Path

MAX_BINARY_REGION = 64 * 1024
MAX_EDGE_TOTAL = 128 * 1024
MAX_TEXT_BYTES = 256 * 1024


class BoundedReadError(ValueError):
    """Raised when a detector requests more data than policy permits."""


def read_prefix(path: Path, limit: int = MAX_BINARY_REGION) -> bytes:
    _validate_binary_limit(limit)
    with path.open("rb") as stream:
        return stream.read(limit)


def read_suffix(path: Path, limit: int = MAX_BINARY_REGION) -> bytes:
    _validate_binary_limit(limit)
    with path.open("rb") as stream:
        stream.seek(0, 2)
        size = stream.tell()
        stream.seek(max(0, size - limit))
        return stream.read(limit)


def contains_in_edges(path: Path, needle: bytes, *, edge_bytes: int = 32 * 1024) -> bool:
    if edge_bytes * 2 > MAX_EDGE_TOTAL:
        raise BoundedReadError("Combined edge read exceeds 128 KiB.")
    return needle in read_prefix(path, edge_bytes) or needle in read_suffix(path, edge_bytes)


def read_text_limit(path: Path, limit: int = MAX_TEXT_BYTES) -> str:
    if not 0 < limit <= MAX_TEXT_BYTES:
        raise BoundedReadError("Text read exceeds 256 KiB.")
    with path.open("rb") as stream:
        payload = stream.read(limit + 1)
    if len(payload) > limit:
        payload = payload[:limit]
    if payload.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return payload.decode("utf-16", errors="replace")
    if payload.startswith(codecs.BOM_UTF8):
        return payload.decode("utf-8-sig", errors="replace")
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        return payload.decode("cp932", errors="replace")


def _validate_binary_limit(limit: int) -> None:
    if not 0 < limit <= MAX_BINARY_REGION:
        raise BoundedReadError("Binary read exceeds 64 KiB.")
