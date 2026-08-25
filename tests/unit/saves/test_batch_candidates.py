from pathlib import Path

import pytest

from gamesave_scout.saves.batch_candidates import (
    BatchCandidateAccumulator,
    candidate_path_key,
)
from gamesave_scout.saves.batch_models import (
    BatchScanScope,
    BatchScanSummary,
    RawBatchCandidate,
    RepresentativeFile,
)


def _candidate(
    path: str,
    *,
    kind: str = "directory",
    sources: tuple[str, ...] = ("bounded_scan",),
    evidence: tuple[str, ...] = ("发现存档文件",),
    representatives: tuple[RepresentativeFile, ...] = (),
    matched_file_count: int = 1,
) -> RawBatchCandidate:
    return RawBatchCandidate(
        scope_key="documents",
        kind=kind,  # type: ignore[arg-type]
        path_template=path,
        display_path=path,
        path_key=candidate_path_key(kind, path),  # type: ignore[arg-type]
        sources=sources,  # type: ignore[arg-type]
        evidence=evidence,
        representative_files=representatives,
        matched_file_count=matched_file_count,
        representatives_truncated=False,
    )


@pytest.mark.parametrize(
    ("kind", "first", "second"),
    [
        ("directory", r"D:\Saves\Game", "d:/saves/game/."),
        ("file", r"D:\Saves\Game\slot.sav", "d:/saves/game/SLOT.SAV"),
        ("glob", r"D:\Saves\Game\*.sav", "d:/saves/game/*.SAV"),
        (
            "registry",
            r"HKCU\Software\Studio\Game",
            r"HKEY_CURRENT_USER/software/studio/GAME",
        ),
    ],
)
def test_candidate_path_key_normalizes_supported_kinds(
    kind: str,
    first: str,
    second: str,
) -> None:
    assert candidate_path_key(kind, first) == candidate_path_key(kind, second)  # type: ignore[arg-type]


def test_accumulator_merges_duplicate_identity_in_first_seen_order() -> None:
    first_files = (
        RepresentativeFile("slot-00.sav", 10, 100),
        RepresentativeFile("slot-01.sav", 11, 101),
    )
    later_files = tuple(
        RepresentativeFile(f"slot-{index:02d}.sav", index + 10, index + 100)
        for index in range(1, 25)
    )
    accumulator = BatchCandidateAccumulator()

    accumulator.add(
        _candidate(
            r"D:\Saves\Game",
            sources=("engine", "bounded_scan"),
            evidence=("引擎规则命中", "发现存档文件"),
            representatives=first_files,
            matched_file_count=2,
        )
    )
    accumulator.add(
        _candidate(
            "d:/saves/game/.",
            sources=("bounded_scan", "ludusavi"),
            evidence=("发现存档文件", "Ludusavi 规则命中"),
            representatives=later_files,
            matched_file_count=25,
        )
    )

    snapshot = accumulator.snapshot()

    assert len(snapshot) == 1
    assert snapshot[0].display_path == r"D:\Saves\Game"
    assert snapshot[0].sources == ("engine", "bounded_scan", "ludusavi")
    assert snapshot[0].evidence == (
        "引擎规则命中",
        "发现存档文件",
        "Ludusavi 规则命中",
    )
    assert len(snapshot[0].representative_files) == 20
    assert snapshot[0].representative_files[:2] == first_files
    assert snapshot[0].matched_file_count == 25
    assert snapshot[0].representatives_truncated is True


def test_accumulator_keeps_different_kinds_for_the_same_path() -> None:
    accumulator = BatchCandidateAccumulator()
    accumulator.add(_candidate(r"D:\Saves\Game", kind="directory"))
    accumulator.add(_candidate(r"D:\Saves\Game", kind="glob"))

    assert [item.kind for item in accumulator.snapshot()] == ["directory", "glob"]


def test_accumulator_truncates_new_identities_after_hard_limit() -> None:
    accumulator = BatchCandidateAccumulator(max_candidates=10_000)

    for index in range(10_000):
        assert accumulator.add(_candidate(rf"D:\Saves\Game-{index}")) is True

    assert accumulator.add(_candidate(r"D:\Saves\Overflow")) is False
    assert len(accumulator.snapshot()) == 10_000
    assert accumulator.truncated is True


def test_batch_models_reject_negative_counts_and_invalid_depth() -> None:
    with pytest.raises(ValueError, match="深度"):
        BatchScanScope("documents", "文档", Path(r"C:\Users\Alice\Documents"), "standard", 0, None)

    with pytest.raises(ValueError, match="非负"):
        RepresentativeFile("slot.sav", -1, 1)

    with pytest.raises(ValueError, match="非负"):
        BatchScanSummary(
            session_id="session-1",
            status="completed",
            new_count=-1,
            pending_count=0,
            recorded_count=0,
            ignored_count=0,
            unavailable_count=0,
            group_count=0,
            inaccessible_scope_count=0,
            truncated_scope_count=0,
            total_entries=0,
            elapsed_seconds=0,
        )
