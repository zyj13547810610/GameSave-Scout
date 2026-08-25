"""Run cheap probes first and conservatively choose a detector result."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path

from gamesave_scout.engines.base import DetectionContext, EngineDetector
from gamesave_scout.engines.models import DetectionOutcome, EngineEvidence, EngineMatch

logger = logging.getLogger(__name__)


class DetectorRegistry:
    def __init__(self, detectors: Iterable[EngineDetector]) -> None:
        self._detectors = tuple(detectors)

    def detect(self, game_dir: Path, executable: Path | None) -> DetectionOutcome:
        context = DetectionContext(game_dir, executable)
        matches: list[EngineMatch] = []
        diagnostics: list[EngineEvidence] = []
        for detector in self._detectors:
            try:
                if not detector.cheap_probe(context):
                    continue
                match = detector.inspect(context)
                if match is not None:
                    threshold = 0.8 if match.experimental else 0.7
                    if match.confidence >= threshold:
                        matches.append(match)
            except Exception as error:
                logger.warning("Engine detector failed: %s", error)
                diagnostics.append(
                    EngineEvidence("detector_error", type(error).__name__, 0.0)
                )
        ranked = sorted(matches, key=lambda item: (-item.confidence, item.engine_id))[:3]
        ambiguous = len(ranked) > 1 and ranked[0].confidence - ranked[1].confidence < 0.08
        best = None if not ranked or ambiguous else ranked[0]
        alternatives = tuple(ranked if ambiguous else ranked[1:])
        return DetectionOutcome(best, alternatives, ambiguous, tuple(diagnostics))
