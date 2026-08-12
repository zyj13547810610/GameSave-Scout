"""Compose the bounded engine detectors used by library scans."""

from __future__ import annotations

from pathlib import Path

from gameshelf.engines.base import EngineDetector
from gameshelf.engines.detectors.creator_engines import CreatorEngineDetector
from gameshelf.engines.detectors.renpy import RenPyDetector
from gameshelf.engines.detectors.rpg_maker import RpgMakerDetector
from gameshelf.engines.detectors.unity import UnityDetector
from gameshelf.engines.detectors.wolf import WolfRpgDetector
from gameshelf.engines.models import DetectionOutcome
from gameshelf.engines.registry import DetectorRegistry
from gameshelf.engines.rule_detector import RuleDetector
from gameshelf.engines.rule_schema import load_engine_rules


class EngineDetectionService:
    def __init__(self, registry: DetectorRegistry) -> None:
        self._registry = registry

    @classmethod
    def from_rules_file(cls, rules_file: Path) -> EngineDetectionService:
        rules = load_engine_rules(rules_file)
        detectors: tuple[EngineDetector, ...] = (
            RpgMakerDetector(),
            RenPyDetector(),
            UnityDetector(),
            WolfRpgDetector(),
            CreatorEngineDetector(),
            *(RuleDetector(rule) for rule in rules),
        )
        return cls(DetectorRegistry(detectors))

    def detect(self, game_dir: Path, executable: Path | None) -> DetectionOutcome:
        return self._registry.detect(game_dir, executable)
