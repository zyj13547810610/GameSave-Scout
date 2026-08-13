"""Rank executable files using only names, sizes, and parsed PE metadata."""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from gameshelf.scanning.pe_metadata import PeArchitecture, read_pe_metadata

_REJECTED_PREFIXES = (
    "unins",
    "uninstall",
    "setup",
    "install",
    "update",
    "updater",
    "crash",
    "report",
)
_REJECTED_DIRECTORIES = {
    "mods",
    "redist",
    "_commonredist",
    "runtime",
    "tools",
    "support",
}
_REJECTED_NORMALIZED_NAMES = {
    "unrealcefsubprocess",
    "delfile",
    "chromedriver",
    "textractor",
    "textractorcli",
}
_REJECTED_NORMALIZED_PREFIXES = ("unitycrashhandler", "crashpadhandler")
_AUXILIARY_PATH_PARTS = {"source", "debug", "obj", "_redist"}
_TITLE_ANNOTATION_PATTERN = re.compile(r"[\(\[\u3010\uff08]")
_REPARSE_FLAG = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


@dataclass(frozen=True)
class ExecutableCandidate:
    relative_path: str
    score: float
    architecture: PeArchitecture
    evidence: tuple[str, ...]


def is_potential_game_executable_name(name: str) -> bool:
    """Return whether a filename can represent a game executable."""
    path = Path(name)
    if path.suffix.casefold() != ".exe":
        return False
    stem = path.stem.casefold()
    if stem == "config" or stem.startswith(_REJECTED_PREFIXES):
        return False
    normalized = _normalize(path.stem)
    if normalized.startswith(_REJECTED_NORMALIZED_PREFIXES):
        return False
    if normalized in _REJECTED_NORMALIZED_NAMES:
        return False
    return not (
        normalized.startswith("easyanticheat") and normalized.endswith("setup")
    )


def rank_executables(game_dir: Path) -> tuple[ExecutableCandidate, ...]:
    candidates = [_rank(path, game_dir) for path in _find_executables(game_dir)]
    return tuple(
        sorted(
            candidates,
            key=lambda item: (-item.score, item.relative_path.casefold(), item.relative_path),
        )
    )


def _find_executables(game_dir: Path) -> tuple[Path, ...]:
    found: list[Path] = []
    for current, directories, files in os.walk(game_dir, followlinks=False):
        current_path = Path(current)
        directories[:] = sorted(
            (
                name
                for name in directories
                if name.casefold() not in _REJECTED_DIRECTORIES
                and not _is_link_or_reparse(current_path / name)
            ),
            key=lambda name: (name.casefold(), name),
        )
        for name in sorted(files, key=lambda value: (value.casefold(), value)):
            if not is_potential_game_executable_name(name):
                continue
            found.append(current_path / name)
    return tuple(found)


def _rank(path: Path, game_dir: Path) -> ExecutableCandidate:
    relative = path.relative_to(game_dir).as_posix()
    metadata = read_pe_metadata(path)
    evidence: list[str] = []
    score = 0.0

    if path.parent == game_dir:
        score += 30
        evidence.append("root_level")
    else:
        depth = len(path.relative_to(game_dir).parts) - 1
        score -= min(depth * 8, 32)
        evidence.append("nested_executable")

    parent_parts = {
        part.casefold() for part in path.relative_to(game_dir).parent.parts
    }
    if parent_parts & _AUXILIARY_PATH_PARTS:
        score -= 60
        evidence.append("auxiliary_directory")

    executable_name = _normalize(path.stem)
    directory_name = _normalize(game_dir.name)
    if executable_name and executable_name == directory_name:
        score += 45
        evidence.append("filename_matches_directory")
    elif _similarity(executable_name, directory_name) >= 0.8:
        score += 25
        evidence.append("filename_similar_to_directory")
    elif _shares_title_segment(path.stem, game_dir.name):
        score += 30
        evidence.append("filename_matches_title_segment")

    product_name = _normalize(metadata.product_name)
    description = _normalize(metadata.file_description)
    if product_name and _similarity(product_name, directory_name) >= 0.8:
        score += 35
        evidence.append("product_name_matches_directory")
    if description and _similarity(description, directory_name) >= 0.8:
        score += 15
        evidence.append("file_description_matches_directory")

    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    if size >= 10 * 1024 * 1024:
        score += 4
        evidence.append("large_executable")
    elif size >= 1024 * 1024:
        score += 2
        evidence.append("medium_executable")

    return ExecutableCandidate(relative, score, metadata.architecture, tuple(evidence))


def _is_link_or_reparse(path: Path) -> bool:
    try:
        info = path.stat(follow_symlinks=False)
        return path.is_symlink() or bool(
            getattr(info, "st_file_attributes", 0) & _REPARSE_FLAG
        )
    except OSError:
        return True


def _normalize(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _shares_title_segment(left: str, right: str) -> bool:
    left_variants = _title_variants(left)
    right_variants = _title_variants(right)
    return any(
        min(len(left_value), len(right_value)) >= 6
        and (left_value in right_value or right_value in left_value)
        for left_value in left_variants
        for right_value in right_variants
    )


def _title_variants(value: str) -> tuple[str, ...]:
    normalized = _normalize(value)
    annotation_free = _normalize(_TITLE_ANNOTATION_PATTERN.split(value, maxsplit=1)[0])
    return tuple(dict.fromkeys(part for part in (normalized, annotation_free) if part))


def _similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()
