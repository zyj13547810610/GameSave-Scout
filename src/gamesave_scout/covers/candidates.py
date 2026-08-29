"""Immutable batch-cover candidates with deterministic matching and ordering."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, Protocol

from rapidfuzz import fuzz

type CoverCandidateSource = Literal[
    "vndb", "clipboard", "drop", "shallow_scan", "cover_directory"
]
type CoverMatchKind = Literal["exact", "normalized", "fuzzy", "manual"]
type CoverWizardQueueStatus = Literal[
    "pending", "ready", "adopted", "skipped", "failed"
]
type CoverProgressDetail = str | int | float | bool | None

SOURCE_PRIORITY: Mapping[CoverCandidateSource, int] = {
    "vndb": 0,
    "clipboard": 1,
    "drop": 1,
    "shallow_scan": 2,
    "cover_directory": 3,
}
MATCH_PRIORITY: Mapping[CoverMatchKind, int] = {
    "exact": 0,
    "normalized": 1,
    "manual": 2,
    "fuzzy": 3,
}

_IMAGE_SUFFIX = re.compile(r"\.(?:png|jpe?g|webp|bmp)$", re.IGNORECASE)
_DECORATION_WORDS = frozenset(
    {"cover", "poster", "front", "frontcover", "keyart", "artwork", "封面"}
)


class CoverProgress(Protocol):
    """Progress surface intentionally compatible with ``TaskContext``."""

    def report(
        self,
        completed: int,
        total: int | None,
        message: str,
        *,
        details: Mapping[str, CoverProgressDetail] | None = None,
    ) -> None: ...

    def raise_if_cancelled(self) -> None: ...


@dataclass(frozen=True)
class CandidateFileRef:
    path: Path
    temporary: bool
    expected_sha256: str


@dataclass(frozen=True)
class CoverCandidateUsage:
    game_id: str
    title: str


@dataclass(frozen=True)
class SharedCoverCandidate:
    id: str
    display_name: str
    width: int
    height: int
    sha256: str
    quality_score: float
    file_ref: CandidateFileRef
    preview_path: Path
    used_by_game_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class CoverCandidate:
    id: str
    game_id: str
    source: CoverCandidateSource
    source_label: str
    display_name: str
    width: int
    height: int
    sha256: str
    match_kind: CoverMatchKind
    score: float
    evidence: tuple[str, ...]
    file_ref: CandidateFileRef
    preview_path: Path
    vndb_id: str | None = None
    shared: bool = False
    used_by: tuple[CoverCandidateUsage, ...] = ()


@dataclass(frozen=True)
class CoverWizardQueueItem:
    game_id: str
    title: str
    initial_has_cover: bool
    version: str | None = None
    status: CoverWizardQueueStatus = "pending"
    candidate_count: int = 0
    error: str | None = None


@dataclass(frozen=True)
class CoverWizardSnapshot:
    id: str
    queue: tuple[CoverWizardQueueItem, ...]
    current_game_id: str | None
    include_existing: bool
    source_operation_active: bool


def normalize_cover_title(value: str) -> str:
    """Normalize a title or image filename without removing embedded words."""
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    normalized = _IMAGE_SUFFIX.sub("", normalized)
    characters = [
        character if character.isalnum() else " "
        for character in normalized
    ]
    words = "".join(characters).split()
    return " ".join(word for word in words if word not in _DECORATION_WORDS)


def match_cover_title(
    query: str, names: Sequence[str]
) -> tuple[CoverMatchKind, float, str]:
    """Return the strongest deterministic match against candidate names."""
    if not names:
        return "manual", 100.0, ""

    folded_query = query.strip().casefold()
    for name in names:
        if folded_query and name.strip().casefold() == folded_query:
            return "exact", 100.0, name

    normalized_query = normalize_cover_title(query)
    for name in names:
        if normalized_query and normalize_cover_title(name) == normalized_query:
            return "normalized", 100.0, name

    scored = [
        (float(fuzz.WRatio(normalized_query, normalize_cover_title(name))), index, name)
        for index, name in enumerate(names)
    ]
    score, _, matched = max(scored, key=lambda item: (item[0], -item[1]))
    return "fuzzy", score, matched


def merge_and_sort_candidates(
    candidates: Iterable[CoverCandidate],
) -> tuple[CoverCandidate, ...]:
    """Merge duplicate content per game and return a stable priority ordering."""
    groups: dict[tuple[str, str], list[CoverCandidate]] = {}
    for candidate in candidates:
        groups.setdefault((candidate.game_id, candidate.sha256), []).append(candidate)

    merged: list[CoverCandidate] = []
    for group in groups.values():
        ordered = sorted(group, key=_candidate_sort_key)
        primary = ordered[0]
        evidence: list[str] = []
        for candidate in ordered:
            for item in candidate.evidence:
                if item not in evidence:
                    evidence.append(item)
        merged.append(replace(primary, evidence=tuple(evidence)))
    return tuple(sorted(merged, key=_candidate_sort_key))


def _candidate_sort_key(candidate: CoverCandidate) -> tuple[int, int, float, str, str]:
    return (
        SOURCE_PRIORITY[candidate.source],
        MATCH_PRIORITY[candidate.match_kind],
        -candidate.score,
        candidate.display_name.casefold(),
        candidate.id,
    )
