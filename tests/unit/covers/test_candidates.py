from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from gameshelf.covers.candidates import (
    CandidateFileRef,
    CoverCandidate,
    CoverCandidateSource,
    match_cover_title,
    merge_and_sort_candidates,
    normalize_cover_title,
)


def _candidate(
    candidate_id: str,
    *,
    source: CoverCandidateSource,
    sha256: str,
    evidence: tuple[str, ...] | None = None,
    match_kind: str = "manual",
    score: float = 100.0,
) -> CoverCandidate:
    source_labels = {
        "vndb": "VNDB",
        "clipboard": "剪贴板",
        "drop": "拖放",
        "shallow_scan": "游戏目录浅层扫描",
        "cover_directory": "现成封面目录",
    }
    label = source_labels[source]
    return CoverCandidate(
        id=candidate_id,
        game_id="game-1",
        source=source,
        source_label=label,
        display_name=f"{candidate_id}.png",
        width=600,
        height=900,
        sha256=sha256,
        match_kind=match_kind,  # type: ignore[arg-type]
        score=score,
        evidence=evidence or (label,),
        file_ref=CandidateFileRef(Path(f"C:/{candidate_id}.png"), False, sha256),
        preview_path=Path(f"C:/{candidate_id}.webp"),
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("  ＧＡＭＥ　ＮＡＭＥ  ", "game name"),
        ("Game.Name---Poster.JPG", "game name"),
        ("游戏名称_封面.png", "游戏名称"),
        ("Game (Deluxe) cover.webp", "game deluxe"),
        ("Discover.jpg", "discover"),
    ],
)
def test_normalize_cover_title(value: str, expected: str) -> None:
    assert normalize_cover_title(value) == expected


def test_match_kinds_are_distinct() -> None:
    assert match_cover_title("Game Name", ["Game Name"])[0] == "exact"
    assert match_cover_title("Game Name", ["ＧＡＭＥ-name 封面.png"])[0] == "normalized"
    kind, score, matched = match_cover_title("Game Name", ["Game Naming"])
    assert kind == "fuzzy"
    assert 0 < score < 100
    assert matched == "Game Naming"
    assert match_cover_title("Game Name", [])[0] == "manual"


def test_match_chooses_highest_scoring_name_deterministically() -> None:
    kind, score, matched = match_cover_title(
        "The House in Fata Morgana", ["unrelated", "House in Fata Morgana"]
    )

    assert kind == "fuzzy"
    assert score >= 80
    assert matched == "House in Fata Morgana"


def test_sources_sort_in_confirmed_priority_and_duplicate_hashes_merge() -> None:
    candidates = (
        _candidate("folder", source="cover_directory", sha256="a" * 64),
        _candidate("drop", source="drop", sha256="b" * 64),
        _candidate("vndb", source="vndb", sha256="a" * 64),
        _candidate("scan", source="shallow_scan", sha256="c" * 64),
    )

    merged = merge_and_sort_candidates(candidates)

    assert [item.source for item in merged] == ["vndb", "drop", "shallow_scan"]
    assert merged[0].evidence == ("VNDB", "现成封面目录")


def test_sort_uses_match_score_name_and_id_as_stable_tiebreakers() -> None:
    base = _candidate(
        "z", source="cover_directory", sha256="a" * 64, match_kind="fuzzy", score=80
    )
    candidates = (
        base,
        replace(base, id="b", display_name="Beta", sha256="b" * 64, score=90),
        replace(base, id="a", display_name="alpha", sha256="c" * 64, score=90),
        replace(base, id="0", display_name="alpha", sha256="d" * 64, score=90),
        replace(base, id="manual", sha256="e" * 64, match_kind="manual", score=1),
    )

    assert [item.id for item in merge_and_sort_candidates(candidates)] == [
        "manual",
        "0",
        "a",
        "b",
        "z",
    ]


def test_hash_deduplication_does_not_cross_game_boundaries() -> None:
    first = _candidate("first", source="vndb", sha256="a" * 64)
    second = replace(first, id="second", game_id="game-2")

    assert len(merge_and_sort_candidates((first, second))) == 2
