from pathlib import Path

from gameshelf.saves.guided_events import GuidedChangeAggregator, RawFileChange


def test_aggregator_merges_atomic_replace_into_final_path() -> None:
    aggregator = GuidedChangeAggregator(max_paths=20_000, max_events=50_000)
    aggregator.record(RawFileChange("created", Path(r"C:\Save\slot.tmp"), None, 10))
    aggregator.record(
        RawFileChange(
            "moved", Path(r"C:\Save\slot.tmp"), Path(r"C:\Save\slot.sav"), 11
        )
    )

    changes = aggregator.snapshot().changes

    assert [change.display_path for change in changes] == [r"C:\Save\slot.sav"]
    assert changes[0].operations == ("created", "moved")
    assert changes[0].first_occurred_ns == 10
    assert changes[0].last_occurred_ns == 11


def test_aggregator_caps_raw_events_and_marks_the_root_overflowed() -> None:
    aggregator = GuidedChangeAggregator(max_paths=20_000, max_events=50_000)
    change = RawFileChange(
        "modified",
        Path(r"C:\Save\slot.sav"),
        None,
        10,
        root=Path(r"C:\Save"),
    )

    for _ in range(50_001):
        aggregator.record(change)

    snapshot = aggregator.snapshot()
    assert snapshot.event_count == 50_000
    assert snapshot.dropped_event_count == 1
    assert snapshot.overflowed_roots == (r"C:\Save",)
    assert len(snapshot.changes) == 1


def test_aggregator_caps_distinct_paths_without_growing_the_container() -> None:
    aggregator = GuidedChangeAggregator(max_paths=20_000, max_events=50_000)
    root = Path(r"C:\Save")

    for index in range(20_001):
        aggregator.record(
            RawFileChange(
                "created",
                root / f"slot-{index}.sav",
                None,
                index,
                root=root,
            )
        )

    snapshot = aggregator.snapshot()
    assert snapshot.event_count == 20_001
    assert snapshot.dropped_event_count == 1
    assert snapshot.overflowed_roots == (r"C:\Save",)
    assert len(snapshot.changes) == 20_000


def test_aggregator_rejects_an_event_that_escapes_its_declared_root() -> None:
    aggregator = GuidedChangeAggregator(max_paths=10, max_events=10)

    aggregator.record(
        RawFileChange(
            "modified",
            Path(r"C:\Other\slot.sav"),
            None,
            10,
            root=Path(r"C:\Save"),
        )
    )

    snapshot = aggregator.snapshot()
    assert snapshot.changes == ()
    assert snapshot.dropped_event_count == 1
    assert snapshot.failed_roots == (r"C:\Save",)


def test_aggregator_snapshot_reports_explicit_overflow_and_failure_once() -> None:
    aggregator = GuidedChangeAggregator(max_paths=10, max_events=10)

    aggregator.mark_overflow(Path(r"C:\Save"))
    aggregator.mark_overflow(Path(r"c:\save"))
    aggregator.mark_failure(Path(r"D:\Games"))

    snapshot = aggregator.snapshot()
    assert snapshot.overflowed_roots == (r"C:\Save",)
    assert snapshot.failed_roots == (r"D:\Games",)
