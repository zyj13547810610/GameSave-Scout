from __future__ import annotations

from pathlib import Path

from gamesave_scout.saves.guided_events import GuidedChangeAggregator, RawFileChange
from gamesave_scout.saves.guided_scanner import BoundedMetadataScanner


def test_event_and_unique_path_limits_never_grow_unbounded(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    event_limited = GuidedChangeAggregator()
    repeated = root / "slot1.sav"
    for index in range(50_001):
        event_limited.record(
            RawFileChange("modified", repeated, None, index, root=root)
        )

    event_snapshot = event_limited.snapshot()
    assert event_snapshot.event_count == 50_000
    assert len(event_snapshot.changes) == 1
    assert event_snapshot.dropped_event_count == 1
    assert event_snapshot.overflowed_roots == (str(root),)

    path_limited = GuidedChangeAggregator()
    for index in range(20_001):
        path_limited.record(
            RawFileChange(
                "modified", root / f"slot-{index:05d}.sav", None, index, root=root
            )
        )

    path_snapshot = path_limited.snapshot()
    assert len(path_snapshot.changes) == 20_000
    assert path_snapshot.dropped_event_count == 1
    assert tuple(item.display_path for item in path_snapshot.changes[:2]) == (
        str(root / "slot-00000.sav"),
        str(root / "slot-00001.sav"),
    )


def test_metadata_scan_deadline_uses_injected_clock_without_waiting(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    for index in range(10):
        (root / f"slot-{index}.sav").write_bytes(b"slot")
    clock = _AdvancingClock()
    scanner = BoundedMetadataScanner(max_seconds=0.5, monotonic=clock)

    result = scanner.scan(root, started_ns=0, finished_ns=2**63 - 1)

    assert result.truncated_by == "deadline"
    assert result.entries_examined < 10
    assert clock.calls < 10


class _AdvancingClock:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> float:
        self.calls += 1
        return self.calls * 0.2
