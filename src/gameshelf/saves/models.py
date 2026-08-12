"""Immutable values exposed by the save-location boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type SaveLocationKind = Literal["directory", "file", "glob", "registry"]
type SaveLocationSource = Literal[
    "manual", "dynamic", "ludusavi", "engine", "legacy_scan"
]


@dataclass(frozen=True, slots=True)
class SaveLocation:
    id: str
    game_id: str
    kind: SaveLocationKind
    path_template: str
    display_path: str
    path_key: str
    source: SaveLocationSource
    confidence: float
    evidence: tuple[str, ...]
    confirmed: bool
    enabled: bool
    last_verified_at: str | None
    exists: bool | None = None
    match_count: int | None = None
    matches_truncated: bool = False


@dataclass(frozen=True, slots=True)
class SaveLocationSuggestion:
    kind: SaveLocationKind
    path_template: str
    display_path: str
    source: SaveLocationSource
    confidence: float
    evidence: tuple[str, ...]

