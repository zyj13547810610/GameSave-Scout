"""Read-only discovery of cover candidates from explicitly bounded directories."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal
from uuid import uuid4

from gamesave_scout.covers.candidate_images import StagedCandidateImage, stage_candidate_file
from gamesave_scout.covers.candidates import (
    MATCH_PRIORITY,
    CoverCandidate,
    CoverMatchKind,
    CoverProgress,
    match_cover_title,
)
from gamesave_scout.covers.image_pipeline import InvalidCoverImage
from gamesave_scout.library.models import Game

MAX_DISCOVERY_FILES = 5_000
MAX_DIRECTORY_CANDIDATES_PER_GAME = 100
DIRECTORY_MATCH_THRESHOLD = 80.0
_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp"})
_REPARSE_POINT = 0x400


@dataclass(frozen=True)
class LocalDiscoverySummary:
    candidates: tuple[CoverCandidate, ...]
    inspected: int
    skipped: int
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
                    source="shallow_scan",
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

    def match_cover_directory(
        self,
        games: Sequence[Game],
        directory: Path,
        session_root: Path,
        context: CoverProgress,
    ) -> Mapping[str, LocalDiscoverySummary]:
        paths, enumeration_truncated = _enumerate_images(
            directory,
            max_depth=0,
            context=context,
        )
        assigned: dict[str, list[tuple[Path, CoverMatchKind, float, str]]] = {
            game.id: [] for game in games
        }
        for path in paths:
            context.raise_if_cancelled()
            match = _best_game_match(path.stem, games)
            if match is None:
                continue
            game, kind, score, matched = match
            assigned[game.id].append((path, kind, score, matched))

        results: dict[str, LocalDiscoverySummary] = {}
        for game in games:
            matches = sorted(
                assigned[game.id],
                key=lambda item: (
                    MATCH_PRIORITY[item[1]],
                    -item[2],
                    item[0].name.casefold(),
                ),
            )
            game_truncated = len(matches) > MAX_DIRECTORY_CANDIDATES_PER_GAME
            candidates: list[CoverCandidate] = []
            warnings: list[str] = []
            skipped = 0
            selected = matches[:MAX_DIRECTORY_CANDIDATES_PER_GAME]
            for index, (path, kind, score, matched) in enumerate(selected, start=1):
                context.raise_if_cancelled()
                try:
                    candidate = _stage_local_candidate(
                        game,
                        path,
                        session_root,
                        source="cover_directory",
                        known_match=(kind, score, matched),
                    )
                except InvalidCoverImage:
                    skipped += 1
                    warnings.append(f"无法读取图片：{path.name}")
                else:
                    candidates.append(candidate)
                context.report(
                    index,
                    len(selected),
                    f"正在匹配 {game.title} 的封面",
                    details={"gameId": game.id},
                )
            results[game.id] = LocalDiscoverySummary(
                candidates=tuple(sorted(candidates, key=_local_sort_key)),
                inspected=len(selected),
                skipped=skipped,
                truncated=enumeration_truncated or game_truncated,
                warnings=tuple(warnings),
            )
        return results


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
    *,
    source: Literal["shallow_scan", "cover_directory"],
    known_match: tuple[CoverMatchKind, float, str] | None = None,
) -> CoverCandidate:
    kind, title_score, matched = known_match or _match_game(path.stem, game)
    candidate_id = uuid4().hex
    preview = session_root / "previews" / game.id / f"{candidate_id}.webp"
    staged = stage_candidate_file(path, preview)
    score = _image_score(staged, path, title_score)
    source_label = "游戏目录浅层扫描" if source == "shallow_scan" else "现成封面目录"
    match_label = {
        "exact": "精确匹配",
        "normalized": "规范化匹配",
        "fuzzy": "模糊匹配",
        "manual": "手动添加",
    }[kind]
    return CoverCandidate(
        id=candidate_id,
        game_id=game.id,
        source=source,
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


def _best_game_match(
    filename: str, games: Sequence[Game]
) -> tuple[Game, CoverMatchKind, float, str] | None:
    matches = [(*_match_game(filename, game), game) for game in games]
    if not matches:
        return None
    kind, score, matched, game = min(
        matches,
        key=lambda item: (
            MATCH_PRIORITY[item[0]],
            -item[1],
            item[3].title.casefold(),
            item[3].id,
        ),
    )
    if kind == "fuzzy" and score < DIRECTORY_MATCH_THRESHOLD:
        return None
    return game, kind, score, matched


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
    ratio = staged.width / staged.height
    aspect_score = max(0.0, 1.0 - abs(ratio - (2 / 3)) / (2 / 3)) * 15
    resolution_score = min((staged.width * staged.height) / 1_440_000, 1.0) * 15
    try:
        file_size = path.stat().st_size
    except OSError:
        file_size = 0
    size_score = min(file_size / (2 * 1024 * 1024), 1.0) * 5
    return round(title_score * 0.65 + aspect_score + resolution_score + size_score, 3)


def _local_sort_key(candidate: CoverCandidate) -> tuple[int, float, str, str]:
    return (
        MATCH_PRIORITY[candidate.match_kind],
        -candidate.score,
        candidate.display_name.casefold(),
        candidate.id,
    )
