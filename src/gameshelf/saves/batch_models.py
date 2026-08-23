"""Immutable domain values for batch save discovery."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

type BatchCandidateKind = Literal["directory", "file", "glob", "registry"]
type BatchCandidateSource = Literal[
    "recorded",
    "user",
    "builtin",
    "ludusavi",
    "engine",
    "bounded_scan",
    "registry",
]
type BatchClassification = Literal["installed", "missing", "unknown"]
type BatchConfidence = Literal["high", "medium", "low"]
type BatchReviewStatus = Literal["pending", "recorded", "ignored", "save_only"]
type BatchAvailability = Literal["available", "unavailable", "unknown"]
type BatchScopeSource = Literal["standard", "custom"]
type BatchScanSessionStatus = Literal[
    "completed",
    "cancelled",
    "failed",
    "interrupted",
    "unavailable",
]


@dataclass(frozen=True, slots=True)
class BatchScanScope:
    key: str
    label: str
    root: Path
    source: BatchScopeSource
    max_depth: int
    custom_root_id: str | None

    def __post_init__(self) -> None:
        if self.max_depth < 1:
            raise ValueError("批量存档扫描深度必须大于零。")
        if self.source == "custom" and not self.custom_root_id:
            raise ValueError("自定义批量存档范围必须包含目录 ID。")
        if self.source == "standard" and self.custom_root_id is not None:
            raise ValueError("标准批量存档范围不能包含自定义目录 ID。")


@dataclass(frozen=True, slots=True)
class RepresentativeFile:
    name: str
    size: int
    modified_time_ns: int

    def __post_init__(self) -> None:
        if self.size < 0 or self.modified_time_ns < 0:
            raise ValueError("代表文件的大小和修改时间必须为非负数。")


@dataclass(frozen=True, slots=True)
class RawBatchCandidate:
    scope_key: str
    kind: BatchCandidateKind
    path_template: str
    display_path: str
    path_key: str
    sources: tuple[BatchCandidateSource, ...]
    evidence: tuple[str, ...]
    representative_files: tuple[RepresentativeFile, ...]
    matched_file_count: int
    representatives_truncated: bool

    def __post_init__(self) -> None:
        if self.matched_file_count < 0:
            raise ValueError("候选匹配文件数必须为非负数。")


@dataclass(frozen=True, slots=True)
class CandidateAlternative:
    title: str
    reason: str
    game_id: str | None


@dataclass(frozen=True, slots=True)
class MatchedBatchCandidate(RawBatchCandidate):
    classification: BatchClassification
    confidence: BatchConfidence
    suggested_game_id: str | None
    suggested_title: str | None
    external_product_id: str | None
    engine_id: str | None
    strong_group_key: str | None
    alternatives: tuple[CandidateAlternative, ...]


@dataclass(frozen=True, slots=True)
class BatchScanSummary:
    session_id: str
    status: BatchScanSessionStatus
    new_count: int
    pending_count: int
    recorded_count: int
    ignored_count: int
    unavailable_count: int
    group_count: int
    inaccessible_scope_count: int
    truncated_scope_count: int
    total_entries: int
    elapsed_seconds: float

    def __post_init__(self) -> None:
        counts = (
            self.new_count,
            self.pending_count,
            self.recorded_count,
            self.ignored_count,
            self.unavailable_count,
            self.group_count,
            self.inaccessible_scope_count,
            self.truncated_scope_count,
            self.total_entries,
        )
        if any(value < 0 for value in counts) or self.elapsed_seconds < 0:
            raise ValueError("批量存档扫描摘要计数和耗时必须为非负数。")
