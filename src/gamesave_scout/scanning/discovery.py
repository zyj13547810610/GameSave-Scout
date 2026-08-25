"""Deterministically enumerate candidate game directories without opening executables."""

from __future__ import annotations

import fnmatch
import logging
import os
import stat
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

from gamesave_scout.bridge.tasks import TaskContext
from gamesave_scout.library.models import ScanRoot
from gamesave_scout.scanning.executable_ranker import is_potential_game_executable_name
from gamesave_scout.scanning.models import DirectoryCandidate
from gamesave_scout.scanning.path_keys import portable_relative

logger = logging.getLogger(__name__)
type DirectoryObserver = Callable[[Path, bool], None]


class RootUnavailableError(OSError):
    """Raised when the configured scan root cannot be opened at all."""


def enumerate_candidates(
    root: ScanRoot,
    context: TaskContext,
    on_directory: DirectoryObserver | None = None,
) -> Iterator[DirectoryCandidate]:
    """Yield candidates in stable path order while honoring cancellation."""
    root_path = Path(root.display_path)
    if root.scan_mode == "children":
        yield from _enumerate_children(root_path, root.exclusions, context, on_directory)
        return
    yield from _enumerate_recursive(
        root_path, root.max_depth, root.exclusions, context, on_directory
    )


def _enumerate_children(
    root_path: Path,
    exclusions: Sequence[str],
    context: TaskContext,
    on_directory: DirectoryObserver | None,
) -> Iterator[DirectoryCandidate]:
    entries = _read_entries(root_path, context, is_root=True, on_directory=on_directory)
    assert entries is not None
    for index, entry in enumerate(entries):
        if index % 64 == 0:
            context.raise_if_cancelled()
        relative = entry.name
        if is_excluded(relative, exclusions) or not _safe_directory(entry):
            continue
        if not _directory_is_accessible(Path(entry.path), context, on_directory):
            continue
        yield DirectoryCandidate(
            path=Path(entry.path),
            relative_dir=relative,
            depth=1,
            reason="direct_child",
        )


def _enumerate_recursive(
    root_path: Path,
    max_depth: int,
    exclusions: Sequence[str],
    context: TaskContext,
    on_directory: DirectoryObserver | None,
) -> Iterator[DirectoryCandidate]:
    def walk(directory: Path, depth: int, *, is_root: bool = False) -> Iterator[DirectoryCandidate]:
        entries = _read_entries(
            directory, context, is_root=is_root, on_directory=on_directory
        )
        if entries is None:
            return

        contains_game_executable = False
        child_directories: list[os.DirEntry[str]] = []
        for index, entry in enumerate(entries):
            if index % 64 == 0:
                context.raise_if_cancelled()
            if _safe_regular_game_executable(entry):
                contains_game_executable = True
            elif _safe_directory(entry):
                child_directories.append(entry)

        if depth > 0 and contains_game_executable:
            yield DirectoryCandidate(
                path=directory,
                relative_dir=portable_relative(directory, root_path),
                depth=depth,
                reason="generic_executable",
            )
            return
        if depth >= max_depth:
            return

        for entry in child_directories:
            context.raise_if_cancelled()
            relative = portable_relative(Path(entry.path), root_path)
            if is_excluded(relative, exclusions):
                continue
            yield from walk(Path(entry.path), depth + 1)

    yield from walk(root_path, 0, is_root=True)


def _read_entries(
    directory: Path,
    context: TaskContext,
    *,
    is_root: bool,
    on_directory: DirectoryObserver | None,
) -> list[os.DirEntry[str]] | None:
    context.raise_if_cancelled()
    try:
        with os.scandir(directory) as iterator:
            entries = sorted(iterator, key=lambda entry: (entry.name.casefold(), entry.name))
        if on_directory is not None:
            on_directory(directory, True)
        return entries
    except OSError as error:
        if on_directory is not None:
            on_directory(directory, False)
        if is_root:
            raise RootUnavailableError(f"Cannot open scan root: {directory}") from error
        logger.warning("Skipping inaccessible directory %s: %s", directory, error)
        return None


def _directory_is_accessible(
    directory: Path,
    context: TaskContext,
    on_directory: DirectoryObserver | None,
) -> bool:
    return (
        _read_entries(
            directory, context, is_root=False, on_directory=on_directory
        )
        is not None
    )


def _safe_directory(entry: os.DirEntry[str]) -> bool:
    try:
        return entry.is_dir(follow_symlinks=False) and not _is_link_or_reparse(entry)
    except OSError as error:
        logger.warning("Skipping inaccessible directory entry %s: %s", entry.path, error)
        return False


def _is_link_or_reparse(entry: os.DirEntry[str]) -> bool:
    if entry.is_symlink():
        return True
    attributes = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)


def _safe_regular_game_executable(entry: os.DirEntry[str]) -> bool:
    if not is_potential_game_executable_name(entry.name):
        return False
    try:
        return entry.is_file(follow_symlinks=False) and not entry.is_symlink()
    except OSError as error:
        logger.warning("Skipping inaccessible executable entry %s: %s", entry.path, error)
        return False


def is_excluded(relative_dir: str, exclusions: Sequence[str]) -> bool:
    value = relative_dir.replace("\\", "/").casefold()
    for exclusion in exclusions:
        pattern = exclusion.replace("\\", "/").casefold().rstrip("/")
        if value == pattern:
            return True
        if fnmatch.fnmatchcase(value, pattern):
            return True
        if not any(mark in pattern for mark in "*?[") and value.startswith(f"{pattern}/"):
            return True
    return False
