"""Purely lexical Windows path normalization and safe relative expansion."""

from __future__ import annotations

import ntpath
import os
from pathlib import Path, PureWindowsPath


class PathTraversalError(ValueError):
    """Raised when a stored relative path could escape its declared root."""


def windows_path_key(path: str | Path) -> str:
    raw = os.fspath(path).replace("/", "\\")
    if raw.casefold().startswith("\\\\?\\unc\\"):
        raw = "\\\\" + raw[8:]
    elif raw.startswith("\\\\?\\"):
        raw = raw[4:]

    normalized = ntpath.normpath(raw)
    drive, tail = ntpath.splitdrive(normalized)
    rooted = tail.startswith("\\")
    components = [component.rstrip(" .") for component in tail.split("\\") if component]
    clean_tail = "\\".join(component for component in components if component)

    if rooted:
        clean_tail = f"\\{clean_tail}" if clean_tail else "\\"
    result = f"{drive}{clean_tail}"
    return result.casefold()


def is_same_or_child(path_key: str, root_key: str) -> bool:
    root = root_key.rstrip("\\")
    path = path_key.rstrip("\\")
    return path == root or path.startswith(f"{root}\\")


def portable_relative(path: Path, root: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise PathTraversalError(f"路径不在指定根目录内：{path}") from error
    if any(part == ".." for part in relative.parts):
        raise PathTraversalError(f"相对路径试图离开指定根目录：{relative}")
    return relative.as_posix()


def expand_relative(root: Path, relative: str) -> Path:
    windows_relative = relative.replace("/", "\\")
    drive, _ = ntpath.splitdrive(windows_relative)
    if drive or ntpath.isabs(windows_relative):
        raise PathTraversalError(f"只允许相对路径：{relative}")

    parts = PureWindowsPath(windows_relative).parts
    if any(part in {"..", "\\", "/"} for part in parts):
        raise PathTraversalError(f"相对路径试图离开指定根目录：{relative}")

    candidate = root.joinpath(*parts)
    if not is_same_or_child(windows_path_key(candidate), windows_path_key(root)):
        raise PathTraversalError(f"展开后的路径不在指定根目录内：{relative}")
    return candidate
