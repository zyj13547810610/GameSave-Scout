"""Detect packaged runtimes that need bounded multi-path inspection."""

from __future__ import annotations

import stat
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from gamesave_scout.engines.base import DetectionContext
from gamesave_scout.engines.models import EngineEvidence, EngineMatch

_MAX_DEPTH = 5
_MAX_ENTRIES = 4096
_VERSION = "runtime-frameworks-2026.08.27"
_REPARSE_FLAG = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


@dataclass(frozen=True, slots=True)
class _IndexedFile:
    relative: str
    path: Path


class RuntimeFrameworkDetector:
    def cheap_probe(self, context: DetectionContext) -> bool:
        try:
            names = {item.name.casefold() for item in context.game_dir.iterdir()}
        except OSError:
            return False
        return bool(
            names
            & {
                "bin",
                "game",
                "content",
                "scripts",
                "monogame.framework.dll",
                "fna.dll",
                "microsoft.xna.framework.dll",
                "love.dll",
                "c2runtime.js",
                "index.html",
            }
        )

    def inspect(self, context: DetectionContext) -> EngineMatch | None:
        files = _index_files(context.game_dir)
        if not files:
            return None

        source2_info = _find_suffix(files, "gameinfo.gi")
        source2_runtime = _find_suffix(files, "engine2.dll")
        if source2_info and source2_runtime and _contains(source2_info.path, b"GameInfo"):
            return _match(
                "source2",
                0.96,
                "发现 Source 2 的 gameinfo.gi 与 engine2.dll",
                (source2_info, source2_runtime),
            )

        source_info = _find_suffix(files, "gameinfo.txt")
        source_runtime = _find_suffix(files, "engine.dll")
        if source_info and source_runtime and _contains(source_info.path, b"GameInfo"):
            return _match(
                "source",
                0.95,
                "发现 Source 的 gameinfo.txt 与 engine.dll",
                (source_info, source_runtime),
            )

        xnb = next(
            (
                item
                for item in files
                if item.relative.casefold().endswith(".xnb")
                and _starts_with(item.path, b"XNB")
            ),
            None,
        )
        if xnb is not None:
            monogame = _find_suffix(files, "monogame.framework.dll")
            if monogame is not None:
                return _match(
                    "monogame",
                    0.94,
                    "发现 MonoGame.Framework.dll 与 XNB 内容",
                    (monogame, xnb),
                )
            fna = _find_suffix(files, "fna.dll")
            fna3d = _find_suffix(files, "fna3d.dll")
            if fna is not None and fna3d is not None:
                return _match(
                    "fna",
                    0.95,
                    "发现 FNA、FNA3D 与 XNB 内容",
                    (fna, fna3d, xnb),
                )
            xna = next(
                (
                    item
                    for item in files
                    if item.path.name.casefold().startswith("microsoft.xna.framework")
                    and item.path.suffix.casefold() == ".dll"
                ),
                None,
            )
            if xna is not None:
                return _match(
                    "xna",
                    0.92,
                    "发现 Microsoft XNA Framework 与 XNB 内容",
                    (xna, xnb),
                )

        love = _find_suffix(files, "love.dll")
        sdl = _find_suffix(files, "sdl2.dll")
        openal = _find_suffix(files, "openal32.dll")
        if love and sdl and openal:
            return _match(
                "love",
                0.96,
                "发现 LÖVE 官方 Windows 运行时组合",
                (love, sdl, openal),
            )

        index = _find_suffix(files, "index.html")
        c2_runtime = _find_suffix(files, "c2runtime.js")
        c2_data = _find_suffix(files, "data.js")
        if index and c2_runtime and c2_data:
            return _match(
                "construct2",
                0.84,
                "发现 Construct 2 导出运行时组合",
                (index, c2_runtime, c2_data),
                experimental=True,
            )

        c3_runtime = _find_suffix(files, "scripts/c3runtime.js")
        c3_main = _find_suffix(files, "scripts/main.js")
        if index and c3_runtime and c3_main:
            return _match(
                "construct3",
                0.84,
                "发现 Construct 3 导出运行时组合",
                (index, c3_runtime, c3_main),
                experimental=True,
            )
        return None


def _index_files(root: Path) -> tuple[_IndexedFile, ...]:
    if _is_link_or_reparse(root):
        return ()
    result: list[_IndexedFile] = []
    stack: list[tuple[Path, int]] = [(root, 0)]
    examined_entries = 0
    while stack and examined_entries < _MAX_ENTRIES:
        directory, depth = stack.pop()
        try:
            for entry in directory.iterdir():
                if examined_entries >= _MAX_ENTRIES:
                    break
                examined_entries += 1
                try:
                    if _is_link_or_reparse(entry):
                        continue
                    if entry.is_file():
                        result.append(
                            _IndexedFile(entry.relative_to(root).as_posix(), entry)
                        )
                    elif depth < _MAX_DEPTH and entry.is_dir():
                        stack.append((entry, depth + 1))
                except OSError:
                    continue
        except OSError:
            continue
    return tuple(result)


def _is_link_or_reparse(path: Path) -> bool:
    try:
        info = path.stat(follow_symlinks=False)
    except OSError:
        return True
    return path.is_symlink() or bool(
        getattr(info, "st_file_attributes", 0) & _REPARSE_FLAG
    )


def _find_suffix(
    files: Iterable[_IndexedFile],
    suffix: str,
) -> _IndexedFile | None:
    normalized = suffix.casefold().replace("\\", "/")
    return next(
        (
            item
            for item in files
            if item.relative.casefold() == normalized
            or item.relative.casefold().endswith(f"/{normalized}")
        ),
        None,
    )


def _contains(path: Path, marker: bytes) -> bool:
    try:
        with path.open("rb") as stream:
            return marker in stream.read(64 * 1024)
    except OSError:
        return False


def _starts_with(path: Path, marker: bytes) -> bool:
    try:
        with path.open("rb") as stream:
            return stream.read(len(marker)) == marker
    except OSError:
        return False


def _match(
    engine_id: str,
    confidence: float,
    detail: str,
    files: tuple[_IndexedFile, ...],
    *,
    experimental: bool = False,
) -> EngineMatch:
    weight = confidence / len(files)
    evidence = tuple(
        EngineEvidence("runtime_layout", detail, weight, item.relative)
        for item in files
    )
    return EngineMatch(
        engine_id,
        None,
        confidence,
        evidence,
        _VERSION,
        experimental=experimental,
    )
