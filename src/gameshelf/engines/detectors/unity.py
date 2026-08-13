"""Recognize Unity player layout without loading game assemblies."""

from __future__ import annotations

import stat
from pathlib import Path

from gameshelf.engines.base import DetectionContext
from gameshelf.engines.models import EngineEvidence, EngineMatch

_REPARSE_FLAG = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class UnityDetector:
    def cheap_probe(self, context: DetectionContext) -> bool:
        root = _runtime_root(context)
        return root is not None and _safe_regular_file(
            root / "UnityPlayer.dll", context.game_dir
        )

    def inspect(self, context: DetectionContext) -> EngineMatch | None:
        root = _runtime_root(context)
        if root is None or not _safe_regular_file(
            root / "UnityPlayer.dll", context.game_dir
        ):
            return None
        executable = context.executable
        executables = [executable] if executable is not None else tuple(root.glob("*.exe"))
        for candidate in executables:
            if (
                candidate is None
                or candidate.parent != root
                or not _safe_regular_file(candidate, context.game_dir)
            ):
                continue
            data = root / f"{candidate.stem}_Data"
            managers = data / "globalgamemanagers"
            if _safe_regular_file(managers, context.game_dir):
                return EngineMatch(
                    "unity",
                    None,
                    0.97,
                    (
                        EngineEvidence(
                            "unity_player",
                            "发现 UnityPlayer.dll",
                            0.42,
                            _relative(root / "UnityPlayer.dll", context.game_dir),
                        ),
                        EngineEvidence(
                            "unity_data",
                            "发现同名 _Data/globalgamemanagers",
                            0.55,
                            _relative(managers, context.game_dir),
                        ),
                    ),
                    "unity-2026.08.12",
                )
        return None


def _runtime_root(context: DetectionContext) -> Path | None:
    executable = context.executable
    if executable is None:
        return context.game_dir
    if not _safe_regular_file(executable, context.game_dir):
        return None
    return executable.parent


def _safe_regular_file(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
        info = path.stat(follow_symlinks=False)
        resolved_root = root.resolve(strict=True)
        resolved_path = path.resolve(strict=True)
    except (OSError, ValueError):
        return False
    if (
        not stat.S_ISREG(info.st_mode)
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


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()
