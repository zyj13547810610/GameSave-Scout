"""Immutable values shared by guided save discovery components."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type GuidedSessionStatus = Literal[
    "preparing",
    "monitoring",
    "settling",
    "completed",
    "cancelled",
    "failed",
    "interrupted",
]
type GuidedScopeSource = Literal[
    "game",
    "documents",
    "saved_games",
    "app_data",
    "local_app_data",
    "local_app_data_low",
    "program_data",
    "confirmed",
    "extra",
]
type GuidedDiscoveryKind = Literal["directory", "file", "registry"]
type GuidedReviewStatus = Literal["unreviewed", "accepted", "ignored"]


@dataclass(frozen=True, slots=True)
class GuidedScopeOption:
    id: str
    label: str
    display_path: str
    path_template: str
    source: GuidedScopeSource
    default_selected: bool
    available: bool
    unavailable_reason: str | None = None


@dataclass(frozen=True, slots=True)
class GuidedRegistryTarget:
    key: str
    source: str
    available: bool


@dataclass(frozen=True, slots=True)
class GuidedSavePreview:
    game_id: str
    game_title: str
    executable: str
    scopes: tuple[GuidedScopeOption, ...]
    registry_targets: tuple[GuidedRegistryTarget, ...]


@dataclass(frozen=True, slots=True)
class GuidedSaveSession:
    id: str
    game_id: str
    status: GuidedSessionStatus
    started_at: str
    monitoring_started_at: str | None
    save_marked_at: str | None
    finished_at: str | None
    root_pid: int | None
    approved_scopes: tuple[GuidedScopeOption, ...]
    unavailable_scopes: tuple[str, ...]
    overflowed_scopes: tuple[str, ...]
    truncated_scopes: tuple[str, ...]
    process_tracking_degraded: bool
    result_summary: dict[str, int]
    error_code: str | None
    error_summary: str | None


@dataclass(frozen=True, slots=True)
class GuidedSaveDiscovery:
    id: str
    detection_session_id: str
    candidate_template: str
    display_path: str
    path_key: str
    kind: GuidedDiscoveryKind
    confidence: float
    evidence: tuple[str, ...]
    representative_files: tuple[str, ...]
    first_changed_at: str | None
    last_changed_at: str | None
    mark_offset_ms: int | None
    affected_by_overflow: bool
    affected_by_truncation: bool
    preselected: bool
    review_status: GuidedReviewStatus
    save_location_id: str | None


@dataclass(frozen=True, slots=True)
class GuidedDiscoveryDraft:
    candidate_template: str
    display_path: str
    path_key: str
    kind: GuidedDiscoveryKind
    confidence: float
    evidence: tuple[str, ...]
    representative_files: tuple[str, ...]
    first_changed_at: str | None
    last_changed_at: str | None
    mark_offset_ms: int | None
    affected_by_overflow: bool
    affected_by_truncation: bool
    preselected: bool
