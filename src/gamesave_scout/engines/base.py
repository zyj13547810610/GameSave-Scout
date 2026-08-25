"""Detector protocol and shared read-only context."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from gamesave_scout.engines.models import EngineMatch


@dataclass(frozen=True)
class DetectionContext:
    game_dir: Path
    executable: Path | None


class EngineDetector(Protocol):
    def cheap_probe(self, context: DetectionContext) -> bool: ...

    def inspect(self, context: DetectionContext) -> EngineMatch | None: ...
