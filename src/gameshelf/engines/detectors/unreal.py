"""Recognize Unreal packaged runtime layouts without loading engine binaries."""

from __future__ import annotations

import stat
from pathlib import Path

from gameshelf.engines.base import DetectionContext
from gameshelf.engines.models import EngineEvidence, EngineMatch
from gameshelf.scanning.pe_metadata import read_pe_metadata

_REPARSE_FLAG = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_VERSION = "unreal-2026.08.13"


class UnrealDetector:
    def cheap_probe(self, context: DetectionContext) -> bool:
        return _runtime_root(context) is not None

    def inspect(self, context: DetectionContext) -> EngineMatch | None:
        executable = context.executable
        runtime_root = _runtime_root(context)
        if executable is None or runtime_root is None:
            return None
        if _normalize(executable.stem) == "unrealcefsubprocess":
            return None

        entry_code: str | None = None
        entry_detail: str | None = None
        metadata = read_pe_metadata(executable)
        metadata_text = " ".join(
            (metadata.product_name, metadata.file_description)
        ).casefold()
        if executable.parent == runtime_root and "bootstrappackagedgame" in metadata_text:
            entry_code = "unreal_bootstrap"
            entry_detail = "发现 BootstrapPackagedGame 启动器"
        elif _is_shipping_executable(executable, runtime_root):
            entry_code = "unreal_shipping"
            entry_detail = "发现项目 Binaries 下的 Shipping 程序"
        if entry_code is None or entry_detail is None:
            return None

        return EngineMatch(
            "unreal",
            None,
            0.97,
            (
                EngineEvidence(
                    "unreal_runtime_layout",
                    "发现 Engine/Binaries 与项目 Binaries 运行时结构",
                    0.52,
                    _relative(runtime_root, context.game_dir),
                ),
                EngineEvidence(
                    entry_code,
                    entry_detail,
                    0.45,
                    _relative(executable, context.game_dir),
                ),
            ),
            _VERSION,
        )


def _runtime_root(context: DetectionContext) -> Path | None:
    executable = context.executable
    if executable is None or not _safe_regular_file(executable, context.game_dir):
        return None
    current = executable.parent
    while True:
        if _has_runtime_layout(current, context.game_dir):
            return current
        if current == context.game_dir:
            return None
        current = current.parent


def _has_runtime_layout(directory: Path, game_dir: Path) -> bool:
    if not _safe_directory(directory / "Engine" / "Binaries", game_dir):
        return False
    try:
        return any(
            child.name.casefold() != "engine"
            and _safe_directory(child, game_dir)
            and _safe_directory(child / "Binaries", game_dir)
            for child in directory.iterdir()
        )
    except OSError:
        return False


def _is_shipping_executable(executable: Path, runtime_root: Path) -> bool:
    relative = executable.relative_to(runtime_root)
    return (
        len(relative.parts) >= 4
        and relative.parts[0].casefold() != "engine"
        and relative.parts[1].casefold() == "binaries"
        and executable.stem.casefold().endswith("-win64-shipping")
    )


def _safe_regular_file(path: Path, root: Path) -> bool:
    return _safe_path(path, root, regular=True)


def _safe_directory(path: Path, root: Path) -> bool:
    return _safe_path(path, root, regular=False)


def _safe_path(path: Path, root: Path, *, regular: bool) -> bool:
    try:
        relative = path.relative_to(root)
        info = path.stat(follow_symlinks=False)
        resolved_root = root.resolve(strict=True)
        resolved_path = path.resolve(strict=True)
    except (OSError, ValueError):
        return False
    expected_type = stat.S_ISREG(info.st_mode) if regular else stat.S_ISDIR(info.st_mode)
    if (
        not expected_type
        or path.is_symlink()
        or bool(getattr(info, "st_file_attributes", 0) & _REPARSE_FLAG)
        or not resolved_path.is_relative_to(resolved_root)
    ):
        return False
    current = root
    for part in relative.parts[:-1]:
        current /= part
        if _is_link_or_reparse(current):
            return False
    return True


def _is_link_or_reparse(path: Path) -> bool:
    try:
        info = path.stat(follow_symlinks=False)
    except OSError:
        return True
    return path.is_symlink() or bool(
        getattr(info, "st_file_attributes", 0) & _REPARSE_FLAG
    )


def _normalize(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _relative(path: Path, root: Path) -> str:
    relative = path.relative_to(root).as_posix()
    return relative or "."
