"""Bounded metadata-only fallback scans for failed or overflowed watch roots."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from gameshelf.saves.guided_scope import is_windows_reparse_point
from gameshelf.scanning.path_keys import is_same_or_child, windows_path_key

type ScanTruncationReason = Literal["depth", "entries", "deadline"]
type ReparsePointCheck = Callable[[Path], bool]


class InvalidMetadataScanRoot(ValueError):
    """Raised when an overflow scan root is unavailable or unsafe."""


@dataclass(frozen=True, slots=True)
class ScannedFileMetadata:
    display_path: str
    path_key: str
    root_path: str
    created_ns: int
    modified_ns: int
    size: int


@dataclass(frozen=True, slots=True)
class MetadataScanResult:
    root_path: str
    files: tuple[ScannedFileMetadata, ...]
    entries_examined: int
    inaccessible_entries: int
    skipped_reparse_points: int
    truncated_by: ScanTruncationReason | None


class BoundedMetadataScanner:
    def __init__(
        self,
        *,
        max_depth: int = 8,
        max_entries: int = 100_000,
        max_seconds: float = 5.0,
        monotonic: Callable[[], float] = time.monotonic,
        is_reparse_point: ReparsePointCheck = is_windows_reparse_point,
    ) -> None:
        if max_depth < 0 or max_entries < 1 or max_seconds <= 0:
            raise ValueError("Guided metadata scan limits are invalid.")
        self._max_depth = max_depth
        self._max_entries = max_entries
        self._max_seconds = max_seconds
        self._monotonic = monotonic
        self._is_reparse_point = is_reparse_point

    def scan(
        self, root: Path, *, started_ns: int, finished_ns: int
    ) -> MetadataScanResult:
        if started_ns > finished_ns:
            raise ValueError("The guided scan time window is inverted.")
        if not root.is_dir() or self._is_reparse_point(root):
            raise InvalidMetadataScanRoot(str(root))
        root_key = windows_path_key(root)
        deadline = self._monotonic() + self._max_seconds
        stack: list[tuple[Path, int]] = [(root, 0)]
        files: list[ScannedFileMetadata] = []
        entries_examined = 0
        inaccessible_entries = 0
        skipped_reparse_points = 0
        truncated_by: ScanTruncationReason | None = None
        stop = False

        while stack and not stop:
            directory, depth = stack.pop()
            try:
                iterator = os.scandir(directory)
            except OSError:
                inaccessible_entries += 1
                continue
            with iterator:
                while True:
                    if self._monotonic() >= deadline:
                        truncated_by = "deadline"
                        stop = True
                        break
                    if entries_examined >= self._max_entries:
                        truncated_by = "entries"
                        stop = True
                        break
                    try:
                        entry = next(iterator)
                    except StopIteration:
                        break
                    except OSError:
                        inaccessible_entries += 1
                        break
                    entries_examined += 1
                    path = Path(entry.path)
                    if not is_same_or_child(windows_path_key(path), root_key):
                        inaccessible_entries += 1
                        continue
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if self._is_reparse_point(path):
                                skipped_reparse_points += 1
                            elif depth + 1 <= self._max_depth:
                                stack.append((path, depth + 1))
                            else:
                                truncated_by = truncated_by or "depth"
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        metadata = entry.stat(follow_symlinks=False)
                    except OSError:
                        inaccessible_entries += 1
                        continue
                    if not _changed_in_window(metadata, started_ns, finished_ns):
                        continue
                    files.append(
                        ScannedFileMetadata(
                            display_path=str(path),
                            path_key=windows_path_key(path),
                            root_path=str(root),
                            created_ns=metadata.st_ctime_ns,
                            modified_ns=metadata.st_mtime_ns,
                            size=metadata.st_size,
                        )
                    )

        return MetadataScanResult(
            root_path=str(root),
            files=tuple(sorted(files, key=lambda item: item.path_key)),
            entries_examined=entries_examined,
            inaccessible_entries=inaccessible_entries,
            skipped_reparse_points=skipped_reparse_points,
            truncated_by=truncated_by,
        )


def _changed_in_window(metadata: os.stat_result, started_ns: int, finished_ns: int) -> bool:
    return (
        started_ns <= metadata.st_ctime_ns <= finished_ns
        or started_ns <= metadata.st_mtime_ns <= finished_ns
    )
