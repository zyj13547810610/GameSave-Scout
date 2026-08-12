"""Immutable engine-detection outcomes."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EngineEvidence:
    code: str
    detail: str
    weight: float
    path: str | None = None


@dataclass(frozen=True)
class EngineMatch:
    engine_id: str
    variant: str | None
    confidence: float
    evidence: tuple[EngineEvidence, ...]
    rule_version: str
    experimental: bool = False

    def __post_init__(self) -> None:
        if not 0 <= self.confidence <= 1:
            raise ValueError("Engine confidence must be between 0 and 1.")


@dataclass(frozen=True)
class DetectionOutcome:
    best: EngineMatch | None
    alternatives: tuple[EngineMatch, ...]
    ambiguous: bool
    diagnostics: tuple[EngineEvidence, ...] = ()
