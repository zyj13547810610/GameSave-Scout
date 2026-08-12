"""Immutable subset of the Ludusavi manifest used by GameShelf."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class ManifestCondition:
    os: str | None = None
    store: str | None = None


@dataclass(frozen=True, slots=True)
class ManifestLocationRule:
    path: str
    tags: frozenset[str]
    conditions: tuple[ManifestCondition, ...]


@dataclass(frozen=True, slots=True)
class ManifestGame:
    canonical_name: str
    files: tuple[ManifestLocationRule, ...]
    registry: tuple[ManifestLocationRule, ...]
    install_dirs: tuple[str, ...]
    alias: str | None


@dataclass(frozen=True, slots=True)
class LudusaviManifest:
    games: Mapping[str, ManifestGame]


type MatchLocationKind = Literal["glob", "registry"]
type MatchLocationCategory = Literal["save", "config", "other"]


@dataclass(frozen=True, slots=True)
class MatchedLocation:
    kind: MatchLocationKind
    path_template: str
    display_path: str
    category: MatchLocationCategory
    preselected: bool
    tags: frozenset[str]
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ManifestMatch:
    canonical_name: str
    confidence: float
    confirmed: bool
    matched_name: str
    evidence: tuple[str, ...]
    locations: tuple[MatchedLocation, ...]
