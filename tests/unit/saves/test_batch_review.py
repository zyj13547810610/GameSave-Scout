from pathlib import Path

import pytest

from gameshelf.db.connection import ConnectionFactory
from gameshelf.saves.batch_review import (
    BatchReviewError,
    BatchSaveReviewService,
    SaveOnlyDraft,
)


class _Writer:
    def submit(self, _operation: object) -> object:
        raise AssertionError("输入校验失败时不得提交数据库事务")


class _Repository:
    def clear_unavailable(self, _candidate_ids: object) -> int:
        raise AssertionError("输入校验失败时不得访问仓储")


def _service(tmp_path: Path) -> BatchSaveReviewService:
    return BatchSaveReviewService(
        ConnectionFactory(tmp_path / "missing.db"),
        _Writer(),  # type: ignore[arg-type]
        _Repository(),  # type: ignore[arg-type]
        engine_ids=("unity",),
    )


def test_accept_rejects_empty_or_oversized_selection(tmp_path: Path) -> None:
    service = _service(tmp_path)

    with pytest.raises(BatchReviewError, match="至少选择"):
        service.accept((), confirm_registry=False)
    with pytest.raises(BatchReviewError, match="500"):
        service.accept(tuple(str(index) for index in range(501)), confirm_registry=False)


@pytest.mark.parametrize(
    ("draft", "message"),
    [
        (SaveOnlyDraft("  ", None, None, (), ("one",), False), "标题"),
        (SaveOnlyDraft("Game", None, "other", (), ("one",), False), "引擎"),
        (SaveOnlyDraft("Game\x00", None, None, (), ("one",), False), "标题"),
    ],
)
def test_create_save_only_validates_draft_before_writing(
    tmp_path: Path,
    draft: SaveOnlyDraft,
    message: str,
) -> None:
    with pytest.raises(BatchReviewError, match=message):
        _service(tmp_path).create_save_only(draft)
