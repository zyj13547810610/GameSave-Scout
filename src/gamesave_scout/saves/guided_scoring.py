"""Deterministic, explainable scoring for guided save changes."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from gamesave_scout.saves.guided_events import AggregatedFileChange
from gamesave_scout.saves.guided_models import GuidedDiscoveryDraft
from gamesave_scout.saves.guided_scanner import ScannedFileMetadata
from gamesave_scout.saves.templates import InvalidPathTemplate, PathTemplateResolver
from gamesave_scout.scanning.path_keys import is_same_or_child, windows_path_key

_NOISE_SEGMENTS = {
    "cache",
    "caches",
    "code cache",
    "crashdumps",
    "crashes",
    "crash reports",
    "gpu cache",
    "gpucache",
    "logs",
    "shadercache",
    "telemetry",
    "temp",
    "tmp",
}
_OTHER_PROGRAM_SEGMENTS = {
    "browser",
    "chrome",
    "discord",
    "edge",
    "firefox",
    "teams",
}
_SAVE_EXTENSIONS = {".sav", ".save"}
_SAVE_NAME_MARKERS = ("autosave", "profile", "quicksave", "save", "slot")


@dataclass(frozen=True, slots=True)
class GuidedScoringContext:
    resolver: PathTemplateResolver
    game_dir: Path
    static_path_keys: tuple[str, ...] = ()
    trusted_root_keys: tuple[str, ...] = ()
    existing_location_keys: tuple[str, ...] = ()
    overflowed_root_keys: tuple[str, ...] = ()
    truncated_root_keys: tuple[str, ...] = ()
    wall_time_offset_ns: int = 0
    max_candidates: int = 500
    max_results: int = 200
    max_representative_files: int = 8

    def with_evidence(
        self,
        *,
        static_path_keys: Sequence[str] | None = None,
        trusted_root_keys: Sequence[str] | None = None,
        existing_location_keys: Sequence[str] | None = None,
        overflowed_root_keys: Sequence[str] | None = None,
        truncated_root_keys: Sequence[str] | None = None,
        wall_time_offset_ns: int | None = None,
    ) -> GuidedScoringContext:
        return replace(
            self,
            static_path_keys=(
                self.static_path_keys
                if static_path_keys is None
                else tuple(static_path_keys)
            ),
            trusted_root_keys=(
                self.trusted_root_keys
                if trusted_root_keys is None
                else tuple(trusted_root_keys)
            ),
            existing_location_keys=(
                self.existing_location_keys
                if existing_location_keys is None
                else tuple(existing_location_keys)
            ),
            overflowed_root_keys=(
                self.overflowed_root_keys
                if overflowed_root_keys is None
                else tuple(overflowed_root_keys)
            ),
            truncated_root_keys=(
                self.truncated_root_keys
                if truncated_root_keys is None
                else tuple(truncated_root_keys)
            ),
            wall_time_offset_ns=(
                self.wall_time_offset_ns
                if wall_time_offset_ns is None
                else wall_time_offset_ns
            ),
        )


@dataclass(frozen=True, slots=True)
class GuidedScoringResult:
    discoveries: tuple[GuidedDiscoveryDraft, ...]
    filtered_counts: dict[str, int]


def score_guided_changes(
    *,
    changes: Sequence[AggregatedFileChange],
    save_mark_ns: int | None,
    context: GuidedScoringContext,
    scanned_files: Sequence[ScannedFileMetadata] = (),
) -> tuple[GuidedDiscoveryDraft, ...]:
    return score_guided_changes_with_summary(
        changes=changes,
        save_mark_ns=save_mark_ns,
        context=context,
        scanned_files=scanned_files,
    ).discoveries


def score_guided_changes_with_summary(
    *,
    changes: Sequence[AggregatedFileChange],
    save_mark_ns: int | None,
    context: GuidedScoringContext,
    scanned_files: Sequence[ScannedFileMetadata] = (),
) -> GuidedScoringResult:
    if context.max_candidates < 1 or context.max_results < 1:
        raise ValueError("Guided scoring limits must be positive.")
    filtered: defaultdict[str, int] = defaultdict(int)
    combined = tuple(changes) + tuple(
        _from_scanned_file(item, context.wall_time_offset_ns)
        for item in scanned_files
    )
    grouped: dict[str, list[AggregatedFileChange]] = defaultdict(list)
    for change in combined:
        if change.exists is False or set(change.operations) == {"deleted"}:
            filtered["deleted"] += 1
            continue
        path = Path(change.display_path)
        if _is_noise(path):
            filtered["noise"] += 1
            continue
        grouped[windows_path_key(path.parent)].append(change)

    drafts: list[GuidedDiscoveryDraft] = []
    for group_changes in grouped.values():
        draft = _score_group(group_changes, save_mark_ns, context, filtered)
        if draft is not None:
            drafts.append(draft)
    drafts.sort(key=lambda item: (-item.confidence, item.path_key))
    bounded = tuple(drafts[: context.max_candidates][: context.max_results])
    return GuidedScoringResult(bounded, dict(sorted(filtered.items())))


def _score_group(
    changes: Sequence[AggregatedFileChange],
    save_mark_ns: int | None,
    context: GuidedScoringContext,
    filtered: defaultdict[str, int],
) -> GuidedDiscoveryDraft | None:
    ordered = sorted(changes, key=lambda item: item.path_key)
    paths = [Path(change.display_path) for change in ordered]
    single_file_candidate = len(ordered) == 1 and _has_save_name(paths[0])
    candidate_path = paths[0] if single_file_candidate else paths[0].parent
    candidate_key = windows_path_key(candidate_path)
    if any(
        is_same_or_child(candidate_key, existing_key)
        for existing_key in context.existing_location_keys
    ):
        filtered["existing"] += 1
        return None
    try:
        candidate_template = context.resolver.collapse(candidate_path, context.game_dir)
    except InvalidPathTemplate:
        filtered["unportable"] += 1
        return None

    confidence = 0.10
    evidence = ["在本次引导会话中发生文件变化"]
    closest_delta_ns: int | None = None
    if save_mark_ns is None:
        evidence.append("没有保存标记，按整个会话变化分析")
    else:
        closest_delta_ns = min(
            (change.last_occurred_ns - save_mark_ns for change in ordered),
            key=abs,
        )
        absolute_delta_ns = abs(closest_delta_ns)
        if absolute_delta_ns <= 5_000_000_000:
            confidence += 0.55
            evidence.append("在保存标记前后 5 秒内发生变化")
        elif absolute_delta_ns <= 15_000_000_000:
            confidence += 0.30
            evidence.append("在保存标记前后 15 秒内发生变化")

    if len(ordered) >= 2:
        confidence += 0.15
        evidence.append("同一目录内有多个文件协调变化")
    path_keys = (candidate_key, *(change.path_key for change in ordered))
    if _matches_static_path(path_keys, context.static_path_keys):
        confidence += 0.20
        evidence.append("与当前游戏的静态存档规则一致")
    if any(
        is_same_or_child(candidate_key, trusted_root_key)
        for trusted_root_key in context.trusted_root_keys
    ):
        confidence += 0.10
        evidence.append("位于游戏目录、确认位置父目录或可信引擎结构")
    if any(_has_save_name(path) for path in paths):
        confidence += 0.05
        evidence.append("文件名具有存档特征")
    if any(_is_other_program_path(path) for path in paths):
        confidence -= 0.25
        evidence.append("位于其他程序的高频变化目录，已降权")

    root_keys = tuple(windows_path_key(change.root_path) for change in ordered)
    affected_by_overflow = _root_affected(root_keys, context.overflowed_root_keys)
    affected_by_truncation = _root_affected(root_keys, context.truncated_root_keys)
    confidence = round(max(0.0, min(1.0, confidence)), 2)
    preselected = (
        save_mark_ns is not None
        and not affected_by_overflow
        and not affected_by_truncation
        and confidence >= 0.85
    )
    representatives = tuple(
        change.display_path
        for change in sorted(
            ordered, key=lambda item: (-item.last_occurred_ns, item.path_key)
        )[: context.max_representative_files]
    )
    first_ns = min(change.first_occurred_ns for change in ordered)
    last_ns = max(change.last_occurred_ns for change in ordered)
    return GuidedDiscoveryDraft(
        candidate_template=candidate_template,
        display_path=str(candidate_path),
        path_key=candidate_key,
        kind="file" if single_file_candidate else "directory",
        confidence=confidence,
        evidence=tuple(evidence),
        representative_files=representatives,
        first_changed_at=_ns_to_utc(first_ns, context.wall_time_offset_ns),
        last_changed_at=_ns_to_utc(last_ns, context.wall_time_offset_ns),
        mark_offset_ms=(
            None if closest_delta_ns is None else round(closest_delta_ns / 1_000_000)
        ),
        affected_by_overflow=affected_by_overflow,
        affected_by_truncation=affected_by_truncation,
        preselected=preselected,
    )


def _from_scanned_file(
    item: ScannedFileMetadata, wall_time_offset_ns: int
) -> AggregatedFileChange:
    occurred_ns = max(item.created_ns, item.modified_ns) - wall_time_offset_ns
    return AggregatedFileChange(
        display_path=item.display_path,
        path_key=item.path_key,
        root_path=item.root_path,
        operations=("modified",),
        first_occurred_ns=occurred_ns,
        last_occurred_ns=occurred_ns,
        size=item.size,
        modified_ns=item.modified_ns,
        exists=True,
    )


def _matches_static_path(path_keys: Sequence[str], static_keys: Sequence[str]) -> bool:
    return any(
        is_same_or_child(path_key, static_key)
        or is_same_or_child(static_key, path_key)
        for path_key in path_keys
        for static_key in static_keys
    )


def _root_affected(root_keys: Sequence[str], affected_keys: Sequence[str]) -> bool:
    return any(
        is_same_or_child(root_key, affected_key)
        or is_same_or_child(affected_key, root_key)
        for root_key in root_keys
        for affected_key in affected_keys
    )


def _is_noise(path: Path) -> bool:
    return any(part.casefold() in _NOISE_SEGMENTS for part in path.parts[-4:])


def _is_other_program_path(path: Path) -> bool:
    return any(part.casefold() in _OTHER_PROGRAM_SEGMENTS for part in path.parts[-4:])


def _has_save_name(path: Path) -> bool:
    name = path.name.casefold()
    return path.suffix.casefold() in _SAVE_EXTENSIONS or any(
        marker in name for marker in _SAVE_NAME_MARKERS
    )


def _ns_to_utc(value: int, wall_time_offset_ns: int) -> str:
    wall_value = value + wall_time_offset_ns
    return datetime.fromtimestamp(wall_value / 1_000_000_000, UTC).isoformat(
        timespec="milliseconds"
    )
