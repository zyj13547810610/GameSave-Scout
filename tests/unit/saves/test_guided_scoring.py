from __future__ import annotations

from pathlib import Path

import pytest

from gameshelf.platform.windows.known_folders import KnownFolders
from gameshelf.saves.guided_events import AggregatedFileChange
from gameshelf.saves.guided_scanner import ScannedFileMetadata
from gameshelf.saves.guided_scoring import (
    GuidedScoringContext,
    score_guided_changes,
    score_guided_changes_with_summary,
)
from gameshelf.saves.templates import PathTemplateResolver
from gameshelf.scanning.path_keys import windows_path_key

MARK_NS = 10_000_000_000


def test_save_mark_and_coordinated_files_filter_cache_and_preselect_real_save(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    save_dir = context.folders.local_app_data_low / "Studio" / "Game"
    cache_dir = context.folders.local_app_data / "Browser" / "Cache"

    drafts = score_guided_changes(
        changes=(
            _change(save_dir / "slot1.sav", MARK_NS - 100_000_000),
            _change(save_dir / "meta.dat", MARK_NS - 50_000_000),
            _change(cache_dir / "entry.bin", MARK_NS),
        ),
        save_mark_ns=MARK_NS,
        context=context.scoring,
    )

    assert drafts[0].display_path == str(save_dir)
    assert drafts[0].confidence >= 0.85
    assert drafts[0].preselected is True
    assert all("Browser\\Cache" not in item.display_path for item in drafts)


def test_static_and_trusted_roots_add_explainable_evidence(tmp_path: Path) -> None:
    context = _context(tmp_path)
    save_dir = context.game_dir / "Saves"
    save_key = windows_path_key(save_dir)
    scoring = context.scoring.with_evidence(
        static_path_keys=(save_key,), trusted_root_keys=(windows_path_key(context.game_dir),)
    )

    drafts = score_guided_changes(
        changes=(_change(save_dir / "profile.sav", MARK_NS + 500_000_000),),
        save_mark_ns=MARK_NS,
        context=scoring,
    )

    assert drafts[0].confidence == 1.0
    assert "与当前游戏的静态存档规则一致" in drafts[0].evidence
    assert "位于游戏目录、确认位置父目录或可信引擎结构" in drafts[0].evidence


def test_event_timestamps_are_converted_from_monotonic_to_utc(tmp_path: Path) -> None:
    context = _context(tmp_path)
    wall_offset_ns = 1_700_000_000_000_000_000
    scoring = context.scoring.with_evidence(
        wall_time_offset_ns=wall_offset_ns,
    )

    draft = score_guided_changes(
        changes=(_change(context.game_dir / "slot1.sav", MARK_NS),),
        save_mark_ns=MARK_NS,
        context=scoring,
    )[0]

    assert draft.first_changed_at == "2023-11-14T22:13:30.000+00:00"


def test_scanned_wall_clock_metadata_is_compared_in_monotonic_time(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    save_file = context.game_dir / "Saves" / "slot1.sav"
    wall_offset_ns = 1_700_000_000_000_000_000
    scoring = context.scoring.with_evidence(
        wall_time_offset_ns=wall_offset_ns,
    )
    changed_wall_ns = wall_offset_ns + MARK_NS + 500_000_000

    draft = score_guided_changes(
        changes=(),
        scanned_files=(
            ScannedFileMetadata(
                display_path=str(save_file),
                path_key=windows_path_key(save_file),
                root_path=str(context.game_dir),
                created_ns=changed_wall_ns,
                modified_ns=changed_wall_ns,
                size=128,
            ),
        ),
        save_mark_ns=MARK_NS,
        context=scoring,
    )[0]

    assert draft.mark_offset_ms == 500
    assert "在保存标记前后 5 秒内发生变化" in draft.evidence
    assert draft.first_changed_at == "2023-11-14T22:13:30.500+00:00"


@pytest.mark.parametrize(
    ("mark_offset_ns", "expected_confidence", "expected_time_evidence"),
    (
        (-5_000_000_000, 0.70, "在保存标记前后 5 秒内发生变化"),
        (-15_000_000_000, 0.45, "在保存标记前后 15 秒内发生变化"),
        (-15_000_000_001, 0.15, None),
    ),
)
def test_save_mark_time_weight_uses_five_and_fifteen_second_boundaries(
    tmp_path: Path,
    mark_offset_ns: int,
    expected_confidence: float,
    expected_time_evidence: str | None,
) -> None:
    context = _context(tmp_path)
    save_mark_ns = 20_000_000_000

    draft = score_guided_changes(
        changes=(
            _change(context.game_dir / "slot1.sav", save_mark_ns + mark_offset_ns),
        ),
        save_mark_ns=save_mark_ns,
        context=context.scoring,
    )[0]

    assert draft.confidence == expected_confidence
    time_evidence = tuple(
        item for item in draft.evidence if item.startswith("在保存标记前后")
    )
    assert time_evidence == (
        () if expected_time_evidence is None else (expected_time_evidence,)
    )


def test_missing_mark_keeps_candidates_unselected(tmp_path: Path) -> None:
    context = _context(tmp_path)
    save_dir = context.folders.documents / "Alice"

    drafts = score_guided_changes(
        changes=(
            _change(save_dir / "slot1.sav", MARK_NS),
            _change(save_dir / "slot2.sav", MARK_NS + 10),
        ),
        save_mark_ns=None,
        context=context.scoring,
    )

    assert drafts
    assert drafts[0].preselected is False
    assert drafts[0].mark_offset_ms is None
    assert "没有保存标记，按整个会话变化分析" in drafts[0].evidence


def test_overflow_and_truncation_are_persisted_and_disable_preselection(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    save_dir = context.folders.local_app_data_low / "Studio" / "Game"
    root_key = windows_path_key(context.folders.local_app_data_low)
    scoring = context.scoring.with_evidence(
        overflowed_root_keys=(root_key,), truncated_root_keys=(root_key,)
    )

    drafts = score_guided_changes(
        changes=(
            _change(
                save_dir / "slot1.sav",
                MARK_NS,
                root=context.folders.local_app_data_low,
            ),
            _change(
                save_dir / "slot2.sav",
                MARK_NS + 1,
                root=context.folders.local_app_data_low,
            ),
        ),
        save_mark_ns=MARK_NS,
        context=scoring,
    )

    assert drafts[0].confidence >= 0.85
    assert drafts[0].affected_by_overflow is True
    assert drafts[0].affected_by_truncation is True
    assert drafts[0].preselected is False


def test_existing_location_is_not_returned_as_a_new_candidate(tmp_path: Path) -> None:
    context = _context(tmp_path)
    save_dir = context.folders.saved_games / "Alice"
    scoring = context.scoring.with_evidence(
        existing_location_keys=(windows_path_key(save_dir),)
    )

    drafts = score_guided_changes(
        changes=(_change(save_dir / "slot1.sav", MARK_NS),),
        save_mark_ns=MARK_NS,
        context=scoring,
    )

    assert drafts == ()


def test_unportable_change_is_counted_but_not_returned(tmp_path: Path) -> None:
    context = _context(tmp_path)
    outside = tmp_path / "Outside" / "slot1.sav"

    result = score_guided_changes_with_summary(
        changes=(_change(outside, MARK_NS),),
        save_mark_ns=MARK_NS,
        context=context.scoring,
    )

    assert result.discoveries == ()
    assert result.filtered_counts == {"unportable": 1}


def test_scoring_limits_results_and_representative_files_deterministically(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    changes: list[AggregatedFileChange] = []
    for directory_index in range(210):
        directory = context.folders.documents / f"Game-{directory_index:03d}"
        for file_index in range(2):
            changes.append(
                _change(
                    directory / f"slot-{file_index}.sav",
                    MARK_NS + directory_index,
                )
            )
    representative_dir = context.folders.documents / "Game-000-Representative"
    changes.extend(
        _change(representative_dir / f"slot-{index:02d}.sav", MARK_NS + index)
        for index in range(12)
    )

    drafts = score_guided_changes(
        changes=tuple(changes),
        save_mark_ns=MARK_NS,
        context=context.scoring,
    )

    assert len(drafts) == 200
    assert drafts == tuple(sorted(drafts, key=lambda item: (-item.confidence, item.path_key)))
    representative = next(
        item for item in drafts if item.display_path == str(representative_dir)
    )
    assert len(representative.representative_files) == 8


class ScoringHarness:
    def __init__(
        self,
        folders: KnownFolders,
        game_dir: Path,
        scoring: GuidedScoringContext,
    ) -> None:
        self.folders = folders
        self.game_dir = game_dir
        self.scoring = scoring


def _context(tmp_path: Path) -> ScoringHarness:
    home = tmp_path / "Profile"
    folders = KnownFolders(
        home=home,
        app_data=home / "AppData" / "Roaming",
        local_app_data=home / "AppData" / "Local",
        local_app_data_low=home / "AppData" / "LocalLow",
        documents=home / "Documents",
        saved_games=home / "Saved Games",
        program_data=tmp_path / "ProgramData",
        public=tmp_path / "Public",
        windows=tmp_path / "Windows",
    )
    game_dir = tmp_path / "Games" / "Alice"
    resolver = PathTemplateResolver(folders)
    return ScoringHarness(
        folders,
        game_dir,
        GuidedScoringContext(resolver=resolver, game_dir=game_dir),
    )


def _change(
    path: Path,
    occurred_ns: int,
    *,
    root: Path | None = None,
) -> AggregatedFileChange:
    return AggregatedFileChange(
        display_path=str(path),
        path_key=windows_path_key(path),
        root_path=str(root or path.parents[2]),
        operations=("modified",),
        first_occurred_ns=occurred_ns,
        last_occurred_ns=occurred_ns,
        size=128,
        modified_ns=occurred_ns,
        exists=True,
    )
