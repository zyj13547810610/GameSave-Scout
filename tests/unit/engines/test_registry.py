from dataclasses import dataclass
from pathlib import Path

from gamesave_scout.engines.base import DetectionContext
from gamesave_scout.engines.models import EngineEvidence, EngineMatch
from gamesave_scout.engines.registry import DetectorRegistry


def test_registry_runs_inspection_only_after_cheap_probe(tmp_path: Path) -> None:
    no = RecordingDetector("no", probe=False, confidence=1.0)
    yes = RecordingDetector("yes", probe=True, confidence=0.9)

    outcome = DetectorRegistry([no, yes]).detect(tmp_path, None)

    assert no.inspections == 0
    assert yes.inspections == 1
    assert outcome.best is not None
    assert outcome.best.engine_id == "yes"


def test_close_scores_are_reported_as_ambiguous(tmp_path: Path) -> None:
    outcome = DetectorRegistry(
        [RecordingDetector("a", True, 0.82), RecordingDetector("b", True, 0.78)]
    ).detect(tmp_path, None)

    assert outcome.best is None
    assert outcome.ambiguous is True
    assert [item.engine_id for item in outcome.alternatives] == ["a", "b"]


def test_experimental_match_requires_higher_threshold(tmp_path: Path) -> None:
    outcome = DetectorRegistry(
        [RecordingDetector("legacy", True, 0.79, experimental=True)]
    ).detect(tmp_path, None)

    assert outcome.best is None
    assert outcome.alternatives == ()


def test_detector_exception_does_not_stop_other_detectors(tmp_path: Path) -> None:
    outcome = DetectorRegistry(
        [BrokenDetector(), RecordingDetector("safe", True, 0.88)]
    ).detect(tmp_path, None)

    assert outcome.best is not None
    assert outcome.best.engine_id == "safe"
    assert outcome.diagnostics


@dataclass
class RecordingDetector:
    engine_id: str
    probe: bool
    confidence: float
    experimental: bool = False
    inspections: int = 0

    def cheap_probe(self, context: DetectionContext) -> bool:
        return self.probe

    def inspect(self, context: DetectionContext) -> EngineMatch | None:
        self.inspections += 1
        return EngineMatch(
            self.engine_id,
            None,
            self.confidence,
            (EngineEvidence("test", "synthetic", self.confidence),),
            "test-1",
            self.experimental,
        )


class BrokenDetector:
    def cheap_probe(self, context: DetectionContext) -> bool:
        return True

    def inspect(self, context: DetectionContext) -> EngineMatch | None:
        raise OSError("planned detector failure")
