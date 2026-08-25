import pytest

from gamesave_scout.saves.batch_repository import BatchCandidateQuery


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"offset": -1}, "偏移"),
        ({"limit": 0}, "数量"),
        ({"limit": 501}, "数量"),
        ({"keyword": "x" * 161}, "关键词"),
        ({"status": "other"}, "状态"),
        ({"confidence": "certain"}, "可信度"),
        ({"source": "old"}, "来源"),
    ],
)
def test_candidate_query_rejects_unsafe_values(
    changes: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        BatchCandidateQuery(**changes)  # type: ignore[arg-type]


def test_candidate_query_normalizes_keyword() -> None:
    query = BatchCandidateQuery(keyword="  Alice  ")

    assert query.keyword == "Alice"
