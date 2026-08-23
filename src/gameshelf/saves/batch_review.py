"""Transactional review commands for persisted batch save candidates."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

from gameshelf.db.connection import ConnectionFactory
from gameshelf.db.writer import DbWriter
from gameshelf.library.models import Game
from gameshelf.library.repository import game_from_row_with_groups
from gameshelf.saves.batch_repository import (
    BatchSaveRepository,
    InvalidBatchCandidateSelection,
)
from gameshelf.saves.location_persistence import (
    PreparedSaveLocation,
    upsert_confirmed_location_result,
)
from gameshelf.saves.models import SaveLocation, SaveLocationKind, SaveLocationSource

MAX_REVIEW_CANDIDATES = 500
_CONFIDENCE = {"high": 0.95, "medium": 0.72, "low": 0.45}


class BatchReviewError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class BatchAcceptResult:
    locations: tuple[SaveLocation, ...]
    recorded_count: int
    unchanged_count: int


@dataclass(frozen=True, slots=True)
class SaveOnlyDraft:
    title: str
    version: str | None
    engine_id: str | None
    group_ids: tuple[str, ...]
    candidate_ids: tuple[str, ...]
    confirm_registry: bool


class BatchSaveReviewService:
    def __init__(
        self,
        factory: ConnectionFactory,
        writer: DbWriter,
        repository: BatchSaveRepository,
        *,
        engine_ids_provider: Callable[[], Sequence[str]] | None = None,
        engine_ids: Sequence[str] | None = None,
        utc_now: Callable[[], str] | None = None,
    ) -> None:
        self._factory = factory
        self._writer = writer
        self._repository = repository
        if engine_ids_provider is not None and engine_ids is not None:
            raise ValueError("不能同时提供固定引擎 ID 和动态引擎 ID 提供者。")
        if engine_ids_provider is None and engine_ids is None:
            raise ValueError("必须提供引擎 ID 或引擎 ID 提供者。")
        self._engine_ids_provider = engine_ids_provider or (
            lambda: engine_ids or ()
        )
        self._utc_now = utc_now or (lambda: datetime.now(UTC).isoformat())

    def accept(
        self,
        candidate_ids: Sequence[str],
        *,
        confirm_registry: bool,
    ) -> BatchAcceptResult:
        unique_ids = _candidate_ids(candidate_ids)

        def operation(connection: sqlite3.Connection) -> BatchAcceptResult:
            rows = _candidate_rows(connection, unique_ids)
            targets: list[str] = []
            for row in rows:
                _require_reviewable(row, allowed_statuses={"pending"})
                target = row["review_game_id"] or row["suggested_game_id"]
                if target is None:
                    raise BatchReviewError(
                        "batch_candidate_target_required",
                        "至少一个候选尚未关联目标游戏。",
                    )
                targets.append(str(target))
            _require_games(connection, tuple(targets))
            _require_registry_confirmation(rows, confirm_registry)

            locations: list[SaveLocation] = []
            recorded_count = 0
            unchanged_count = 0
            for candidate_id, row, game_id in zip(
                unique_ids,
                rows,
                targets,
                strict=True,
            ):
                result = upsert_confirmed_location_result(
                    connection,
                    _prepared_location(row, game_id),
                )
                if result.created:
                    recorded_count += 1
                else:
                    unchanged_count += 1
                changed = connection.execute(
                    """
                    UPDATE save_scan_candidates
                    SET review_status = 'recorded', review_game_id = ?,
                        save_location_id = ?, updated_at = ?
                    WHERE id = ? AND review_status = 'pending'
                      AND availability = 'available'
                    """,
                    (
                        game_id,
                        result.location.id,
                        self._utc_now(),
                        candidate_id,
                    ),
                ).rowcount
                if changed != 1:
                    raise BatchReviewError(
                        "batch_candidate_stale",
                        "批量存档候选已经失效，请刷新后重试。",
                    )
                locations.append(result.location)
            return BatchAcceptResult(
                locations=tuple(locations),
                recorded_count=recorded_count,
                unchanged_count=unchanged_count,
            )

        return self._writer.submit(operation).result()

    def create_save_only(self, draft: SaveOnlyDraft) -> Game:
        engine_ids = frozenset(self._engine_ids_provider())
        title, version, group_ids, candidate_ids = self._validate_save_only(
            draft,
            engine_ids,
        )

        def operation(connection: sqlite3.Connection) -> Game:
            rows = _candidate_rows(connection, candidate_ids)
            for row in rows:
                _require_reviewable(row, allowed_statuses={"pending"})
            _require_registry_confirmation(rows, draft.confirm_registry)
            _require_groups(connection, group_ids)

            game_id = str(uuid4())
            now = self._utc_now()
            connection.execute(
                """
                INSERT INTO games(
                    id, title, title_is_manual, status,
                    engine_id, engine_is_manual,
                    version, version_is_manual,
                    added_at, updated_at
                ) VALUES (?, ?, 1, 'save_only', ?, ?, ?, 1, ?, ?)
                """,
                (
                    game_id,
                    title,
                    draft.engine_id,
                    int(draft.engine_id is not None),
                    version,
                    now,
                    now,
                ),
            )
            for group_id in group_ids:
                connection.execute(
                    """
                    INSERT INTO game_group_memberships(game_id, group_id, created_at)
                    VALUES (?, ?, ?)
                    """,
                    (game_id, group_id, now),
                )
            for candidate_id, row in zip(candidate_ids, rows, strict=True):
                result = upsert_confirmed_location_result(
                    connection,
                    _prepared_location(row, game_id),
                )
                changed = connection.execute(
                    """
                    UPDATE save_scan_candidates
                    SET review_status = 'save_only', review_game_id = ?,
                        save_location_id = ?, updated_at = ?
                    WHERE id = ? AND review_status = 'pending'
                      AND availability = 'available'
                    """,
                    (game_id, result.location.id, now, candidate_id),
                ).rowcount
                if changed != 1:
                    raise BatchReviewError(
                        "batch_candidate_stale",
                        "批量存档候选已经失效，请刷新后重试。",
                    )
            row = connection.execute(
                "SELECT * FROM games WHERE id = ?",
                (game_id,),
            ).fetchone()
            assert row is not None
            return game_from_row_with_groups(connection, row)

        return self._writer.submit(operation).result()

    def reassociate_many(
        self,
        candidate_ids: Sequence[str],
        game_id: str,
    ) -> int:
        unique_ids = _candidate_ids(candidate_ids)
        _identifier(game_id, "目标游戏")

        def operation(connection: sqlite3.Connection) -> int:
            _require_games(connection, (game_id,))
            rows = _candidate_rows(connection, unique_ids)
            for row in rows:
                _require_reviewable(row, allowed_statuses={"pending", "ignored"})
            now = self._utc_now()
            for candidate_id in unique_ids:
                connection.execute(
                    """
                    UPDATE save_scan_candidates
                    SET review_game_id = ?, review_status = 'pending', updated_at = ?
                    WHERE id = ?
                    """,
                    (game_id, now, candidate_id),
                )
            return len(unique_ids)

        return self._writer.submit(operation).result()

    def ignore(self, candidate_ids: Sequence[str]) -> int:
        return self._set_review_status(candidate_ids, "ignored")

    def restore(self, candidate_ids: Sequence[str]) -> int:
        return self._set_review_status(candidate_ids, "pending")

    def clear_unavailable(self, candidate_ids: Sequence[str]) -> int:
        try:
            return self._repository.clear_unavailable(candidate_ids)
        except InvalidBatchCandidateSelection as error:
            raise BatchReviewError(
                "batch_candidate_clear_invalid",
                str(error),
            ) from error

    def _set_review_status(
        self,
        candidate_ids: Sequence[str],
        status: str,
    ) -> int:
        unique_ids = _candidate_ids(candidate_ids)

        def operation(connection: sqlite3.Connection) -> int:
            rows = _candidate_rows(connection, unique_ids)
            for row in rows:
                _require_reviewable(row, allowed_statuses={"pending", "ignored"})
            now = self._utc_now()
            changed = 0
            for candidate_id, row in zip(unique_ids, rows, strict=True):
                if row["review_status"] == status:
                    continue
                changed += connection.execute(
                    """
                    UPDATE save_scan_candidates
                    SET review_status = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (status, now, candidate_id),
                ).rowcount
            return changed

        return self._writer.submit(operation).result()

    def _validate_save_only(
        self,
        draft: SaveOnlyDraft,
        engine_ids: frozenset[str],
    ) -> tuple[str, str | None, tuple[str, ...], tuple[str, ...]]:
        if not isinstance(draft.title, str) or "\x00" in draft.title:
            raise BatchReviewError(
                "save_only_title_invalid",
                "仅存档卡片标题无效。",
            )
        title = draft.title.strip()
        if not title:
            raise BatchReviewError(
                "save_only_title_invalid",
                "仅存档卡片标题不能为空。",
            )
        if draft.version is not None and (
            not isinstance(draft.version, str) or "\x00" in draft.version
        ):
            raise BatchReviewError(
                "save_only_version_invalid",
                "仅存档卡片版本无效。",
            )
        version = draft.version.strip() if draft.version else None
        version = version or None
        if draft.engine_id is not None and draft.engine_id not in engine_ids:
            raise BatchReviewError(
                "save_only_engine_invalid",
                "仅存档卡片引擎不受支持。",
            )
        group_ids = _identifiers(draft.group_ids, "分组", maximum=200, allow_empty=True)
        candidate_ids = _candidate_ids(draft.candidate_ids)
        if not isinstance(draft.confirm_registry, bool):
            raise BatchReviewError(
                "registry_confirmation_invalid",
                "注册表确认状态无效。",
            )
        return title, version, group_ids, candidate_ids


def _candidate_ids(values: Sequence[str]) -> tuple[str, ...]:
    try:
        return _identifiers(
            values,
            "批量存档候选",
            maximum=MAX_REVIEW_CANDIDATES,
            allow_empty=False,
        )
    except BatchReviewError as error:
        if not values:
            raise BatchReviewError(
                "batch_candidate_empty",
                "至少选择一个批量存档候选。",
            ) from error
        raise


def _identifiers(
    values: Sequence[str],
    label: str,
    *,
    maximum: int,
    allow_empty: bool,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise BatchReviewError("batch_selection_invalid", f"{label}列表无效。")
    result = tuple(dict.fromkeys(values))
    if (not allow_empty and not result) or len(result) > maximum:
        raise BatchReviewError(
            "batch_selection_invalid",
            f"{label}必须为 1 到 {maximum} 项。",
        )
    for value in result:
        _identifier(value, label)
    return result


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise BatchReviewError("batch_selection_invalid", f"{label} ID 无效。")
    return value


def _candidate_rows(
    connection: sqlite3.Connection,
    candidate_ids: tuple[str, ...],
) -> tuple[sqlite3.Row, ...]:
    placeholders = ",".join("?" for _ in candidate_ids)
    rows = connection.execute(
        f"""
        SELECT c.*, o.evidence_json, o.sources_json
        FROM save_scan_candidates AS c
        LEFT JOIN save_scan_observations AS o
          ON o.candidate_id = c.id AND o.session_id = c.latest_session_id
        WHERE c.id IN ({placeholders})
        """,  # noqa: S608
        candidate_ids,
    ).fetchall()
    by_id = {str(row["id"]): row for row in rows}
    missing = next((item for item in candidate_ids if item not in by_id), None)
    if missing is not None:
        raise BatchReviewError(
            "batch_candidate_not_found",
            "至少一个批量存档候选不存在。",
        )
    return tuple(by_id[item] for item in candidate_ids)


def _require_reviewable(
    row: sqlite3.Row,
    *,
    allowed_statuses: set[str],
) -> None:
    if row["availability"] != "available":
        raise BatchReviewError(
            "batch_candidate_unavailable",
            "至少一个批量存档候选当前不可用。",
        )
    if row["review_status"] not in allowed_statuses:
        raise BatchReviewError(
            "batch_candidate_processed",
            "至少一个批量存档候选已经处理，不能重复操作。",
        )


def _require_games(connection: sqlite3.Connection, game_ids: tuple[str, ...]) -> None:
    unique_ids = tuple(dict.fromkeys(game_ids))
    placeholders = ",".join("?" for _ in unique_ids)
    found = int(
        connection.execute(
            f"SELECT COUNT(*) FROM games WHERE id IN ({placeholders})",  # noqa: S608
            unique_ids,
        ).fetchone()[0]
    )
    if found != len(unique_ids):
        raise BatchReviewError(
            "batch_target_game_not_found",
            "至少一个目标游戏不存在。",
        )


def _require_groups(connection: sqlite3.Connection, group_ids: tuple[str, ...]) -> None:
    if not group_ids:
        return
    placeholders = ",".join("?" for _ in group_ids)
    found = int(
        connection.execute(
            f"SELECT COUNT(*) FROM game_groups WHERE id IN ({placeholders})",  # noqa: S608
            group_ids,
        ).fetchone()[0]
    )
    if found != len(group_ids):
        raise BatchReviewError(
            "save_only_group_not_found",
            "至少一个仅存档卡片分组不存在。",
        )


def _require_registry_confirmation(
    rows: Sequence[sqlite3.Row],
    confirmed: bool,
) -> None:
    if any(row["kind"] == "registry" for row in rows) and not confirmed:
        raise BatchReviewError(
            "registry_confirmation_required",
            "注册表候选需要额外确认后才能接受。",
        )


def _prepared_location(row: sqlite3.Row, game_id: str) -> PreparedSaveLocation:
    confidence = _CONFIDENCE.get(str(row["confidence"]))
    if confidence is None:
        raise BatchReviewError(
            "batch_candidate_invalid",
            "批量存档候选可信度无效。",
        )
    return PreparedSaveLocation(
        game_id=game_id,
        kind=cast(SaveLocationKind, row["kind"]),
        path_template=str(row["path_template"]),
        display_path=str(row["display_path"]),
        path_key=str(row["path_key"]),
        source=_accepted_location_source(row),
        confidence=confidence,
        evidence=_string_tuple(row["evidence_json"]),
    )


def _accepted_location_source(row: sqlite3.Row) -> SaveLocationSource:
    sources = _string_tuple(row["sources_json"], label="来源")
    return "engine" if "builtin" in sources else "legacy_scan"


def _string_tuple(value: object, *, label: str = "证据") -> tuple[str, ...]:
    if value is None:
        return ()
    try:
        loaded = json.loads(str(value))
    except json.JSONDecodeError as error:
        raise BatchReviewError(
            "batch_candidate_invalid",
            f"批量存档候选{label}无效。",
        ) from error
    if not isinstance(loaded, list) or not all(isinstance(item, str) for item in loaded):
        raise BatchReviewError(
            "batch_candidate_invalid",
            f"批量存档候选{label}无效。",
        )
    return tuple(loaded)
