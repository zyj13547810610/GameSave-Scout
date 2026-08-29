"""Read-only discovery of cover candidates from explicitly bounded directories."""

from __future__ import annotations

import os
import stat
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from uuid import uuid4

from gamesave_scout.covers.candidate_images import StagedCandidateImage, stage_candidate_file
from gamesave_scout.covers.candidates import (
    MATCH_PRIORITY,
    CoverCandidate,
    CoverMatchKind,
    CoverProgress,
    SharedCoverCandidate,
    match_cover_title,
)
from gamesave_scout.covers.image_pipeline import InvalidCoverImage
from gamesave_scout.library.models import Game

MAX_DISCOVERY_FILES = 5_000
MAX_SHARED_DIRECTORY_CANDIDATES = 1_000
_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp"})
_REPARSE_POINT = 0x400


@dataclass(frozen=True)
class LocalDiscoverySummary:
    candidates: tuple[CoverCandidate, ...]
    inspected: int
    skipped: int
    truncated: bool
    warnings: tuple[str, ...]


class InvalidCoverDirectory(ValueError):
    """Raised when the explicitly selected cover directory cannot be read."""


@dataclass(frozen=True)
class DirectoryImportSummary:
    candidates: tuple[SharedCoverCandidate, ...]
    inspected: int
    duplicates: int
    invalid: int
    truncated: bool
    warnings: tuple[str, ...]


class LocalCoverDiscovery:
    def scan_game_directory(
        self,
        game: Game,
        install_directory: Path,
        session_root: Path,
        limit: int,
        depth: int,
        context: CoverProgress,
    ) -> LocalDiscoverySummary:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("游戏目录封面候选数量必须为 1 到 100。")
        if type(depth) is not int or not 1 <= depth <= 3:
            raise ValueError("游戏目录封面扫描层数必须为 1 到 3。")
        paths, enumeration_truncated = _enumerate_images(
            install_directory,
            max_depth=depth - 1,
            context=context,
        )
        candidates: list[CoverCandidate] = []
        warnings: list[str] = []
        inspected = 0
        skipped = 0
        for index, path in enumerate(paths, start=1):
            context.raise_if_cancelled()
            inspected += 1
            try:
                candidate = _stage_local_candidate(
                    game,
                    path,
                    session_root,
                )
            except InvalidCoverImage:
                skipped += 1
                warnings.append(f"无法读取图片：{path.name}")
            else:
                candidates.append(candidate)
            context.report(index, len(paths), f"正在检查 {path.name}")

        ordered = sorted(candidates, key=_local_sort_key)
        truncated = enumeration_truncated or len(ordered) > limit
        return LocalDiscoverySummary(
            candidates=tuple(ordered[:limit]),
            inspected=inspected,
            skipped=skipped,
            truncated=truncated,
            warnings=tuple(warnings),
        )

    def import_cover_directory(
        self,
        directory: Path,
        session_root: Path,
        known_sha256s: frozenset[str],
        capacity: int,
        context: CoverProgress,
    ) -> DirectoryImportSummary:
        if type(capacity) is not int or capacity < 0:
            raise ValueError("共享封面候选剩余容量必须是非负整数。")
        _validate_cover_directory(directory)
        paths, enumeration_truncated = _enumerate_cover_directory(directory, context)
        candidates: list[SharedCoverCandidate] = []
        warnings: list[str] = []
        encountered_sha256s = set(known_sha256s)
        inspected = 0
        duplicates = 0
        invalid = 0
        truncated = enumeration_truncated
        try:
            for index, path in enumerate(paths, start=1):
                context.raise_if_cancelled()
                inspected += 1
                candidate_id = uuid4().hex
                preview = session_root / "shared-previews" / f"{candidate_id}.webp"
                try:
                    staged = stage_candidate_file(path, preview)
                except InvalidCoverImage:
                    invalid += 1
                    warnings.append(f"无法读取图片：{path.name}")
                else:
                    if staged.sha256 in encountered_sha256s:
                        duplicates += 1
                        with suppress(OSError):
                            staged.preview_path.unlink(missing_ok=True)
                    elif len(candidates) >= capacity:
                        encountered_sha256s.add(staged.sha256)
                        truncated = True
                        with suppress(OSError):
                            staged.preview_path.unlink(missing_ok=True)
                    else:
                        encountered_sha256s.add(staged.sha256)
                        candidates.append(
                            SharedCoverCandidate(
                                id=candidate_id,
                                display_name=path.name,
                                width=staged.width,
                                height=staged.height,
                                sha256=staged.sha256,
                                quality_score=_image_quality_score(staged, path),
                                file_ref=staged.file_ref,
                                preview_path=staged.preview_path,
                            )
                        )
                context.report(index, len(paths), f"正在导入 {path.name}")
        except BaseException:
            for candidate in candidates:
                with suppress(OSError):
                    candidate.preview_path.unlink(missing_ok=True)
            raise

        return DirectoryImportSummary(
            candidates=tuple(candidates),
            inspected=inspected,
            duplicates=duplicates,
            invalid=invalid,
            truncated=truncated,
            warnings=tuple(warnings),
        )


def _validate_cover_directory(directory: Path) -> None:
    try:
        metadata = directory.lstat()
    except OSError as error:
        raise InvalidCoverDirectory(
            "所选封面目录不存在或不是目录。"
        ) from error
    attributes = getattr(metadata, "st_file_attributes", 0)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or directory.is_symlink()
        or bool(attributes & _REPARSE_POINT)
    ):
        raise InvalidCoverDirectory("所选封面目录不存在或不是目录。")


def _enumerate_cover_directory(
    directory: Path,
    context: CoverProgress,
) -> tuple[list[Path], bool]:
    context.raise_if_cancelled()
    try:
        with os.scandir(directory) as iterator:
            entries = sorted(iterator, key=lambda item: item.name.casefold())
    except OSError as error:
        raise InvalidCoverDirectory("无法读取所选封面目录。") from error
    paths: list[Path] = []
    for entry in entries:
        context.raise_if_cancelled()
        if _is_regular_image(entry):
            paths.append(Path(entry.path))
            if len(paths) >= MAX_DISCOVERY_FILES:
                return paths, True
    return paths, False


def _enumerate_images(
    directory: Path,
    *,
    max_depth: int,
    context: CoverProgress,
) -> tuple[list[Path], bool]:
    paths: list[Path] = []
    current_directories = [directory]
    for current_depth in range(max_depth + 1):
        next_directories: list[Path] = []
        for current in current_directories:
            context.raise_if_cancelled()
            try:
                entries = sorted(
                    os.scandir(current),
                    key=lambda item: item.name.casefold(),
                )
            except OSError:
                continue
            for entry in entries:
                context.raise_if_cancelled()
                if _is_regular_image(entry):
                    paths.append(Path(entry.path))
                elif current_depth < max_depth and _is_safe_directory(entry):
                    next_directories.append(Path(entry.path))
                if len(paths) >= MAX_DISCOVERY_FILES:
                    return paths, True
        current_directories = sorted(
            next_directories,
            key=lambda path: path.as_posix().casefold(),
        )
    return paths, False


def _is_regular_image(entry: os.DirEntry[str]) -> bool:
    try:
        return (
            entry.is_file(follow_symlinks=False)
            and not _is_reparse_point(entry)
            and Path(entry.name).suffix.casefold() in _IMAGE_SUFFIXES
        )
    except OSError:
        return False


def _is_safe_directory(entry: os.DirEntry[str]) -> bool:
    try:
        return entry.is_dir(follow_symlinks=False) and not _is_reparse_point(entry)
    except OSError:
        return False


def _is_reparse_point(entry: os.DirEntry[str]) -> bool:
    try:
        attributes = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
        return bool(attributes & _REPARSE_POINT)
    except OSError:
        return True


def _stage_local_candidate(
    game: Game,
    path: Path,
    session_root: Path,
) -> CoverCandidate:
    kind, title_score, matched = _match_game(path.stem, game)
    candidate_id = uuid4().hex
    preview = session_root / "previews" / game.id / f"{candidate_id}.webp"
    staged = stage_candidate_file(path, preview)
    score = _image_score(staged, path, title_score)
    source_label = "游戏目录浅层扫描"
    match_label = {
        "exact": "精确匹配",
        "normalized": "规范化匹配",
        "fuzzy": "模糊匹配",
        "manual": "手动添加",
    }[kind]
    return CoverCandidate(
        id=candidate_id,
        game_id=game.id,
        source="shallow_scan",
        source_label=source_label,
        display_name=path.name,
        width=staged.width,
        height=staged.height,
        sha256=staged.sha256,
        match_kind=kind,
        score=score,
        evidence=(source_label, f"{match_label}：{matched or path.stem}"),
        file_ref=staged.file_ref,
        preview_path=staged.preview_path,
    )


def _match_game(filename: str, game: Game) -> tuple[CoverMatchKind, float, str]:
    aliases = [game.title]
    if game.relative_dir:
        leaf = PurePosixPath(game.relative_dir.replace("\\", "/")).name
        if leaf and leaf.casefold() != game.title.casefold():
            aliases.append(leaf)
    matches = [match_cover_title(alias, (filename,)) for alias in aliases]
    return min(
        matches,
        key=lambda item: (MATCH_PRIORITY[item[0]], -item[1], item[2].casefold()),
    )


def _image_score(staged: StagedCandidateImage, path: Path, title_score: float) -> float:
    return round(title_score * 0.65 + _image_quality_score(staged, path), 3)


def _image_quality_score(staged: StagedCandidateImage, path: Path) -> float:
    ratio = staged.width / staged.height
    aspect_score = max(0.0, 1.0 - abs(ratio - (2 / 3)) / (2 / 3)) * 15
    resolution_score = min((staged.width * staged.height) / 1_440_000, 1.0) * 15
    try:
        file_size = path.stat().st_size
    except OSError:
        file_size = 0
    size_score = min(file_size / (2 * 1024 * 1024), 1.0) * 5
    return round(aspect_score + resolution_score + size_score, 3)


def _local_sort_key(candidate: CoverCandidate) -> tuple[int, float, str, str]:
    return (
        MATCH_PRIORITY[candidate.match_kind],
        -candidate.score,
        candidate.display_name.casefold(),
        candidate.id,
    )
