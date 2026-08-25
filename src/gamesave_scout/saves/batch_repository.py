"""Transactional persistence for batch save discovery sessions and candidates."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, cast
from uuid import uuid4

from gamesave_scout.db.connection import ConnectionFactory
from gamesave_scout.db.writer import DbWriter
from gamesave_scout.saves.batch_candidates import candidate_path_key
from gamesave_scout.saves.batch_models import (
    BatchAvailability,
    BatchCandidateKind,
    BatchCandidateSource,
    BatchClassification,
    BatchConfidence,
    BatchReviewStatus,
    BatchScanSessionStatus,
    CandidateAlternative,
    MatchedBatchCandidate,
    RepresentativeFile,
)
from gamesave_scout.saves.batch_scanner import BatchScopeResult

if TYPE_CHECKING:
    from gamesave_scout.saves.batch_service import BatchScanRequest

type BatchCandidateStatusFilter = Literal[
    "all",
    "pending",
    "installed",
    "missing",
    "unknown",
    "recorded",
    "ignored",
    "unavailable",
]
type BatchConfidenceFilter = Literal["all", "high", "medium", "low"]
type BatchSourceFilter = Literal[
    "all",
    "recorded",
    "user",
    "builtin",
    "ludusavi",
    "engine",
    "bounded_scan",
    "registry",
]
type BatchObservedSource = BatchCandidateSource | Literal["custom"]

_VALID_STATUS_FILTERS = frozenset(
    {
        "all",
        "pending",
        "installed",
        "missing",
        "unknown",
        "recorded",
        "ignored",
        "unavailable",
    }
)
_VALID_CONFIDENCE_FILTERS = frozenset({"all", "high", "medium", "low"})
_VALID_SOURCE_FILTERS = frozenset(
    {
        "all",
        "recorded",
        "user",
        "builtin",
        "ludusavi",
        "engine",
        "bounded_scan",
        "registry",
    }
)
_FINISHED_STATUSES = frozenset({"completed", "cancelled", "failed", "unavailable", "interrupted"})


class BatchSessionNotFoundError(LookupError):
    """Raised when a batch save discovery session does not exist."""


class InvalidBatchSessionState(RuntimeError):
    """Raised when a batch session cannot perform a requested transition."""


class InvalidBatchCandidateSelection(ValueError):
    """Raised when a destructive candidate-history selection is unsafe."""


@dataclass(frozen=True, slots=True)
class BatchCandidateQuery:
    status: BatchCandidateStatusFilter = "all"
    keyword: str = ""
    confidence: BatchConfidenceFilter = "all"
    source: BatchSourceFilter = "all"
    offset: int = 0
    limit: int = 100

    def __post_init__(self) -> None:
        if self.status not in _VALID_STATUS_FILTERS:
            raise ValueError("批量存档候选状态筛选无效。")
        if self.confidence not in _VALID_CONFIDENCE_FILTERS:
            raise ValueError("批量存档候选可信度筛选无效。")
        if self.source not in _VALID_SOURCE_FILTERS:
            raise ValueError("批量存档候选来源筛选无效。")
        if type(self.offset) is not int or self.offset < 0:
            raise ValueError("批量存档候选查询偏移必须为非负整数。")
        if type(self.limit) is not int or not 1 <= self.limit <= 500:
            raise ValueError("批量存档候选查询数量必须为 1 到 500。")
        if not isinstance(self.keyword, str) or "\x00" in self.keyword:
            raise ValueError("批量存档候选查询关键词无效。")
        normalized_keyword = self.keyword.strip()
        if len(normalized_keyword) > 160:
            raise ValueError("批量存档候选查询关键词最多 160 个字符。")
        object.__setattr__(self, "keyword", normalized_keyword)


@dataclass(frozen=True, slots=True)
class PersistedBatchCandidate:
    id: str
    scope_key: str
    kind: BatchCandidateKind
    path_template: str
    display_path: str
    path_key: str
    availability: BatchAvailability
    classification: BatchClassification
    confidence: BatchConfidence
    suggested_game_id: str | None
    suggested_title: str | None
    external_product_id: str | None
    engine_id: str | None
    strong_group_key: str | None
    review_game_id: str | None
    review_status: BatchReviewStatus
    save_location_id: str | None
    latest_session_id: str | None
    first_seen_at: str
    last_seen_at: str
    updated_at: str
    sources: tuple[BatchObservedSource, ...]
    evidence: tuple[str, ...]
    representative_files: tuple[RepresentativeFile, ...]
    matched_file_count: int
    representatives_truncated: bool
    alternatives: tuple[CandidateAlternative, ...]


@dataclass(frozen=True, slots=True)
class BatchCandidatePage:
    items: tuple[PersistedBatchCandidate, ...]
    total: int


class BatchSaveRepository:
    def __init__(
        self,
        factory: ConnectionFactory,
        writer: DbWriter,
        *,
        utc_now: Callable[[], str] | None = None,
    ) -> None:
        self._factory = factory
        self._writer = writer
        self._utc_now = utc_now or (lambda: datetime.now(UTC).isoformat())

    def start_session(
        self,
        request: BatchScanRequest,
        rules_version: str,
    ) -> str:
        session_id = str(uuid4())
        started_at = self._utc_now()
        scope_json = _dump_json(_initial_scopes(request))

        def operation(connection: sqlite3.Connection) -> None:
            connection.execute(
                """
                INSERT INTO scan_sessions(
                    id, root_id, kind, status, started_at,
                    scope_json, counts_json, rules_version
                ) VALUES (?, NULL, 'save_discovery', 'running', ?, ?, '{}', ?)
                """,
                (session_id, started_at, scope_json, rules_version),
            )

        self._writer.submit(operation).result()
        return session_id

    def record_candidates(
        self,
        session_id: str,
        scope_results: Sequence[BatchScopeResult],
        candidates: Sequence[MatchedBatchCandidate],
    ) -> tuple[str, ...]:
        observed_at = self._utc_now()

        def operation(connection: sqlite3.Connection) -> tuple[str, ...]:
            session = _require_running_session(connection, session_id)
            scopes = _load_scope_json(session["scope_json"])
            scopes.update(_scope_payload(scope_results))
            connection.execute(
                "UPDATE scan_sessions SET scope_json = ? WHERE id = ?",
                (_dump_json(scopes), session_id),
            )

            candidate_ids: list[str] = []
            for candidate in candidates:
                path_key = candidate_path_key(candidate.kind, candidate.path_key)
                row = connection.execute(
                    """
                    SELECT id
                    FROM save_scan_candidates
                    WHERE kind = ? AND path_key = ?
                    """,
                    (candidate.kind, path_key),
                ).fetchone()
                if row is None:
                    candidate_id = str(uuid4())
                    recorded = _recorded_location(
                        connection,
                        candidate.kind,
                        path_key,
                    )
                    review_status: BatchReviewStatus = (
                        "recorded" if recorded is not None else "pending"
                    )
                    review_game_id = None if recorded is None else recorded["game_id"]
                    save_location_id = None if recorded is None else recorded["id"]
                    connection.execute(
                        """
                        INSERT INTO save_scan_candidates(
                            id, scope_key, kind, path_template, display_path,
                            path_key, availability, classification, confidence,
                            suggested_game_id, suggested_title, external_product_id,
                            engine_id, strong_group_key, review_game_id,
                            review_status, save_location_id, latest_session_id,
                            first_seen_at, last_seen_at, updated_at
                        ) VALUES (
                            ?, ?, ?, ?, ?, ?, 'available', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                        )
                        """,
                        (
                            candidate_id,
                            candidate.scope_key,
                            candidate.kind,
                            candidate.path_template,
                            candidate.display_path,
                            path_key,
                            candidate.classification,
                            candidate.confidence,
                            candidate.suggested_game_id,
                            candidate.suggested_title,
                            candidate.external_product_id,
                            candidate.engine_id,
                            candidate.strong_group_key,
                            review_game_id,
                            review_status,
                            save_location_id,
                            session_id,
                            observed_at,
                            observed_at,
                            observed_at,
                        ),
                    )
                else:
                    candidate_id = cast(str, row["id"])
                    connection.execute(
                        """
                        UPDATE save_scan_candidates
                        SET scope_key = ?, path_template = ?, display_path = ?,
                            availability = 'available', classification = ?,
                            confidence = ?, suggested_game_id = ?,
                            suggested_title = ?, external_product_id = ?,
                            engine_id = ?, strong_group_key = ?,
                            latest_session_id = ?, last_seen_at = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            candidate.scope_key,
                            candidate.path_template,
                            candidate.display_path,
                            candidate.classification,
                            candidate.confidence,
                            candidate.suggested_game_id,
                            candidate.suggested_title,
                            candidate.external_product_id,
                            candidate.engine_id,
                            candidate.strong_group_key,
                            session_id,
                            observed_at,
                            observed_at,
                            candidate_id,
                        ),
                    )
                _upsert_observation(connection, session_id, candidate_id, candidate)
                candidate_ids.append(candidate_id)
            return tuple(candidate_ids)

        return self._writer.submit(operation).result()

    def update_rules_version(self, session_id: str, rules_version: str) -> None:
        if not isinstance(rules_version, str) or not rules_version or "\x00" in rules_version:
            raise ValueError("批量存档规则版本无效。")

        def operation(connection: sqlite3.Connection) -> None:
            _require_running_session(connection, session_id)
            connection.execute(
                "UPDATE scan_sessions SET rules_version = ? WHERE id = ?",
                (rules_version, session_id),
            )

        self._writer.submit(operation).result()

    def finish_session(
        self,
        session_id: str,
        *,
        status: BatchScanSessionStatus,
        scope_results: Sequence[BatchScopeResult] = (),
        counts: Mapping[str, int] | None = None,
        error_summary: str | None = None,
    ) -> int:
        if status not in _FINISHED_STATUSES:
            raise ValueError("批量存档扫描结束状态无效。")
        if counts is not None and any(
            not isinstance(key, str) or type(value) is not int or value < 0
            for key, value in counts.items()
        ):
            raise ValueError("批量存档扫描计数无效。")
        finished_at = self._utc_now()

        def operation(connection: sqlite3.Connection) -> int:
            session = _require_running_session(connection, session_id)
            scopes = _load_scope_json(session["scope_json"])
            scopes.update(_scope_payload(scope_results))
            unavailable_count = 0
            if status == "completed":
                complete_scope_keys = tuple(
                    key
                    for key, value in scopes.items()
                    if value.get("status") == "completed" and value.get("truncated") is False
                )
                for scope_key in complete_scope_keys:
                    cursor = connection.execute(
                        """
                        UPDATE save_scan_candidates
                        SET availability = 'unavailable', updated_at = ?
                        WHERE scope_key = ?
                          AND latest_session_id IS NOT ?
                          AND last_seen_at < ?
                          AND availability != 'unavailable'
                        """,
                        (finished_at, scope_key, session_id, session["started_at"]),
                    )
                    unavailable_count += cursor.rowcount
            connection.execute(
                """
                UPDATE scan_sessions
                SET status = ?, finished_at = ?, scope_json = ?,
                    counts_json = ?, error_summary = ?
                WHERE id = ?
                """,
                (
                    status,
                    finished_at,
                    _dump_json(scopes),
                    _dump_json(dict(counts or {})),
                    error_summary,
                    session_id,
                ),
            )
            return unavailable_count

        return self._writer.submit(operation).result()

    def recover_interrupted(self) -> int:
        finished_at = self._utc_now()

        def operation(connection: sqlite3.Connection) -> int:
            cursor = connection.execute(
                """
                UPDATE scan_sessions
                SET status = 'interrupted', finished_at = ?,
                    error_summary = COALESCE(
                        error_summary,
                        '应用退出前批量存档扫描未完成。'
                    )
                WHERE kind = 'save_discovery' AND status = 'running'
                """,
                (finished_at,),
            )
            return cursor.rowcount

        return self._writer.submit(operation).result()

    def session_counts(self, session_id: str) -> dict[str, int]:
        with self._factory.connect(readonly=True) as connection:
            session = connection.execute(
                """
                SELECT started_at
                FROM scan_sessions
                WHERE id = ? AND kind = 'save_discovery'
                """,
                (session_id,),
            ).fetchone()
            if session is None:
                raise BatchSessionNotFoundError(session_id)
            row = connection.execute(
                """
                SELECT
                    COUNT(*) AS observed,
                    SUM(CASE WHEN c.first_seen_at >= ? THEN 1 ELSE 0 END) AS new_count,
                    SUM(CASE WHEN c.review_status = 'pending' THEN 1 ELSE 0 END) AS pending_count,
                    SUM(CASE WHEN c.review_status = 'recorded' THEN 1 ELSE 0 END) AS recorded_count,
                    SUM(CASE WHEN c.review_status = 'ignored' THEN 1 ELSE 0 END) AS ignored_count,
                    SUM(CASE WHEN c.availability = 'unavailable' THEN 1 ELSE 0 END)
                        AS unavailable_count
                FROM save_scan_observations AS o
                JOIN save_scan_candidates AS c ON c.id = o.candidate_id
                WHERE o.session_id = ?
                """,
                (session["started_at"], session_id),
            ).fetchone()
        assert row is not None
        return {
            "observed": int(row["observed"] or 0),
            "new": int(row["new_count"] or 0),
            "pending": int(row["pending_count"] or 0),
            "recorded": int(row["recorded_count"] or 0),
            "ignored": int(row["ignored_count"] or 0),
            "unavailable": int(row["unavailable_count"] or 0),
        }

    def list_candidates(self, query: BatchCandidateQuery) -> BatchCandidatePage:
        where_sql, parameters = _query_filters(query)
        with self._factory.connect(readonly=True) as connection:
            total = cast(
                int,
                connection.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM save_scan_candidates AS c
                    LEFT JOIN save_scan_observations AS o
                      ON o.candidate_id = c.id
                     AND o.session_id = c.latest_session_id
                    {where_sql}
                    """,
                    parameters,
                ).fetchone()[0],
            )
            rows = connection.execute(
                f"""
                {_CANDIDATE_SELECT}
                {where_sql}
                ORDER BY {_CANDIDATE_ORDER}
                LIMIT ? OFFSET ?
                """,
                (*parameters, query.limit, query.offset),
            ).fetchall()
        return BatchCandidatePage(
            items=tuple(_candidate_from_row(row) for row in rows),
            total=total,
        )

    def get_candidate(self, candidate_id: str) -> PersistedBatchCandidate | None:
        if not isinstance(candidate_id, str) or not candidate_id or "\x00" in candidate_id:
            raise ValueError("批量存档候选 ID 无效。")
        with self._factory.connect(readonly=True) as connection:
            row = connection.execute(
                f"""
                {_CANDIDATE_SELECT}
                WHERE c.id = ?
                """,
                (candidate_id,),
            ).fetchone()
        return None if row is None else _candidate_from_row(row)

    def selectable_ids(
        self,
        query: BatchCandidateQuery,
        *,
        limit: int = 500,
    ) -> tuple[str, ...]:
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("批量选择候选数量必须为 1 到 500。")
        where_sql, parameters = _query_filters(query)
        eligibility = """
            c.review_status = 'pending'
            AND c.availability = 'available'
            AND (
                c.review_game_id IS NOT NULL
                OR (c.confidence = 'high' AND c.suggested_game_id IS NOT NULL)
            )
        """
        conjunction = "WHERE" if not where_sql else "AND"
        with self._factory.connect(readonly=True) as connection:
            rows = connection.execute(
                f"""
                SELECT c.id
                FROM save_scan_candidates AS c
                LEFT JOIN save_scan_observations AS o
                  ON o.candidate_id = c.id
                 AND o.session_id = c.latest_session_id
                {where_sql}
                {conjunction} {eligibility}
                ORDER BY {_CANDIDATE_ORDER}
                LIMIT ?
                """,
                (*parameters, limit),
            ).fetchall()
        return tuple(cast(str, row["id"]) for row in rows)

    def clear_unavailable(self, candidate_ids: Sequence[str]) -> int:
        normalized_ids = _candidate_ids(candidate_ids)

        def operation(connection: sqlite3.Connection) -> int:
            placeholders = ",".join("?" for _ in normalized_ids)
            rows = connection.execute(
                f"""
                SELECT id, availability, save_location_id
                FROM save_scan_candidates
                WHERE id IN ({placeholders})
                """,
                normalized_ids,
            ).fetchall()
            if len(rows) != len(normalized_ids):
                raise InvalidBatchCandidateSelection("部分批量存档候选不存在。")
            if any(
                row["availability"] != "unavailable" or row["save_location_id"] is not None
                for row in rows
            ):
                raise InvalidBatchCandidateSelection("只能清除未关联正式存档位置的不可用候选历史。")
            cursor = connection.execute(
                f"DELETE FROM save_scan_candidates WHERE id IN ({placeholders})",
                normalized_ids,
            )
            return cursor.rowcount

        return self._writer.submit(operation).result()


_CANDIDATE_SELECT = """
    SELECT c.*,
           o.sources_json,
           o.evidence_json,
           o.representative_files_json,
           o.alternatives_json,
           o.matched_file_count,
           o.representatives_truncated
    FROM save_scan_candidates AS c
    LEFT JOIN save_scan_observations AS o
      ON o.candidate_id = c.id
     AND o.session_id = c.latest_session_id
"""

_CANDIDATE_ORDER = """
    CASE
        WHEN c.availability = 'unavailable' THEN 5
        WHEN c.review_status = 'pending' AND c.confidence = 'high' THEN 0
        WHEN c.review_status = 'pending' AND c.classification = 'installed' THEN 1
        WHEN c.review_status = 'pending'
         AND c.classification IN ('missing', 'unknown') THEN 2
        WHEN c.review_status = 'pending' THEN 1
        WHEN c.review_status IN ('recorded', 'save_only') THEN 3
        WHEN c.review_status = 'ignored' THEN 4
        ELSE 2
    END,
    c.last_seen_at DESC,
    c.id
"""


def _query_filters(query: BatchCandidateQuery) -> tuple[str, tuple[object, ...]]:
    clauses: list[str] = []
    parameters: list[object] = []
    if query.status == "pending":
        clauses.append("c.review_status = 'pending' AND c.availability != 'unavailable'")
    elif query.status in {"installed", "missing", "unknown"}:
        clauses.append("c.classification = ? AND c.availability != 'unavailable'")
        parameters.append(query.status)
    elif query.status in {"recorded", "ignored"}:
        clauses.append("c.review_status = ?")
        parameters.append(query.status)
    elif query.status == "unavailable":
        clauses.append("c.availability = 'unavailable'")

    if query.keyword:
        clauses.append(
            """
            instr(
                lower(
                    c.display_path || ' ' ||
                    coalesce(c.suggested_title, '') || ' ' ||
                    coalesce(c.external_product_id, '')
                ),
                lower(?)
            ) > 0
            """
        )
        parameters.append(query.keyword)
    if query.confidence != "all":
        clauses.append("c.confidence = ?")
        parameters.append(query.confidence)
    if query.source != "all":
        clauses.append("EXISTS (SELECT 1 FROM json_each(o.sources_json) WHERE value = ?)")
        parameters.append(query.source)
    return (
        "" if not clauses else f"WHERE {' AND '.join(f'({item})' for item in clauses)}",
        tuple(parameters),
    )


def _candidate_from_row(row: sqlite3.Row) -> PersistedBatchCandidate:
    sources = _load_string_tuple(row["sources_json"])
    evidence = _load_string_tuple(row["evidence_json"])
    representative_values = _load_json_list(row["representative_files_json"])
    alternative_values = _load_json_list(row["alternatives_json"])
    representatives = tuple(
        RepresentativeFile(
            name=_required_string(value, "name"),
            size=_required_int(value, "size"),
            modified_time_ns=_required_int(value, "modified_time_ns"),
        )
        for value in representative_values
    )
    alternatives = tuple(
        CandidateAlternative(
            title=_required_string(value, "title"),
            reason=_required_string(value, "reason"),
            game_id=_optional_string(value, "game_id"),
        )
        for value in alternative_values
    )
    return PersistedBatchCandidate(
        id=cast(str, row["id"]),
        scope_key=cast(str, row["scope_key"]),
        kind=cast(BatchCandidateKind, row["kind"]),
        path_template=cast(str, row["path_template"]),
        display_path=cast(str, row["display_path"]),
        path_key=cast(str, row["path_key"]),
        availability=cast(BatchAvailability, row["availability"]),
        classification=cast(BatchClassification, row["classification"]),
        confidence=cast(BatchConfidence, row["confidence"]),
        suggested_game_id=cast(str | None, row["suggested_game_id"]),
        suggested_title=cast(str | None, row["suggested_title"]),
        external_product_id=cast(str | None, row["external_product_id"]),
        engine_id=cast(str | None, row["engine_id"]),
        strong_group_key=cast(str | None, row["strong_group_key"]),
        review_game_id=cast(str | None, row["review_game_id"]),
        review_status=cast(BatchReviewStatus, row["review_status"]),
        save_location_id=cast(str | None, row["save_location_id"]),
        latest_session_id=cast(str | None, row["latest_session_id"]),
        first_seen_at=cast(str, row["first_seen_at"]),
        last_seen_at=cast(str, row["last_seen_at"]),
        updated_at=cast(str, row["updated_at"]),
        sources=cast(tuple[BatchObservedSource, ...], sources),
        evidence=evidence,
        representative_files=representatives,
        matched_file_count=int(row["matched_file_count"] or 0),
        representatives_truncated=bool(row["representatives_truncated"] or 0),
        alternatives=alternatives,
    )


def _upsert_observation(
    connection: sqlite3.Connection,
    session_id: str,
    candidate_id: str,
    candidate: MatchedBatchCandidate,
) -> None:
    connection.execute(
        """
        INSERT INTO save_scan_observations(
            session_id, candidate_id, sources_json, evidence_json,
            representative_files_json, alternatives_json,
            matched_file_count, representatives_truncated
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_id, candidate_id) DO UPDATE SET
            sources_json = excluded.sources_json,
            evidence_json = excluded.evidence_json,
            representative_files_json = excluded.representative_files_json,
            alternatives_json = excluded.alternatives_json,
            matched_file_count = excluded.matched_file_count,
            representatives_truncated = excluded.representatives_truncated
        """,
        (
            session_id,
            candidate_id,
            _dump_json(candidate.sources),
            _dump_json(candidate.evidence),
            _dump_json(tuple(asdict(value) for value in candidate.representative_files)),
            _dump_json(tuple(asdict(value) for value in candidate.alternatives)),
            candidate.matched_file_count,
            int(candidate.representatives_truncated),
        ),
    )


def _recorded_location(
    connection: sqlite3.Connection,
    kind: BatchCandidateKind,
    path_key: str,
) -> sqlite3.Row | None:
    rows = connection.execute(
        """
        SELECT id, game_id
        FROM save_locations
        WHERE kind = ? AND path_key = ?
        ORDER BY id
        LIMIT 2
        """,
        (kind, path_key),
    ).fetchall()
    return rows[0] if len(rows) == 1 else None


def _require_running_session(
    connection: sqlite3.Connection,
    session_id: str,
) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT *
        FROM scan_sessions
        WHERE id = ? AND kind = 'save_discovery'
        """,
        (session_id,),
    ).fetchone()
    if row is None:
        raise BatchSessionNotFoundError(session_id)
    if row["status"] != "running":
        raise InvalidBatchSessionState("批量存档扫描会话已经结束。")
    return cast(sqlite3.Row, row)


def _initial_scopes(request: BatchScanRequest) -> dict[str, dict[str, object]]:
    standard_ids = _request_ids(request.standard_scope_ids, "标准范围")
    custom_ids = _request_ids(request.custom_root_ids, "自定义目录")
    keys = (*standard_ids, *(f"custom:{root_id}" for root_id in custom_ids))
    return {
        key: {"status": "pending", "truncated": False, "entries": 0} for key in dict.fromkeys(keys)
    }


def _request_ids(values: object, label: str) -> tuple[str, ...]:
    if not isinstance(values, tuple) or not all(
        isinstance(value, str) and value and "\x00" not in value for value in values
    ):
        raise ValueError(f"批量存档扫描{label}无效。")
    return values


def _candidate_ids(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise InvalidBatchCandidateSelection("批量存档候选 ID 列表无效。")
    result = tuple(dict.fromkeys(values))
    if not 1 <= len(result) <= 500 or any(
        not isinstance(value, str) or not value or "\x00" in value for value in result
    ):
        raise InvalidBatchCandidateSelection("批量存档候选 ID 必须为 1 到 500 项。")
    return result


def _scope_payload(
    scope_results: Sequence[BatchScopeResult],
) -> dict[str, dict[str, object]]:
    return {
        result.scope_key: {
            "status": result.status,
            "truncated": result.truncated,
            "entries": result.entries,
        }
        for result in scope_results
    }


def _load_scope_json(value: object) -> dict[str, dict[str, object]]:
    try:
        parsed = json.loads(cast(str, value))
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError("批量存档扫描范围数据损坏。") from error
    if not isinstance(parsed, dict):
        raise ValueError("批量存档扫描范围数据损坏。")
    result: dict[str, dict[str, object]] = {}
    for key, item in parsed.items():
        if not isinstance(key, str) or not isinstance(item, dict):
            raise ValueError("批量存档扫描范围数据损坏。")
        result[key] = item
    return result


def _dump_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _load_json_list(value: object) -> list[dict[str, object]]:
    if value is None:
        return []
    try:
        parsed = json.loads(cast(str, value))
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError("批量存档候选观察数据损坏。") from error
    if not isinstance(parsed, list) or not all(isinstance(item, dict) for item in parsed):
        raise ValueError("批量存档候选观察数据损坏。")
    return cast(list[dict[str, object]], parsed)


def _load_string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    try:
        parsed = json.loads(cast(str, value))
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError("批量存档候选观察数据损坏。") from error
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise ValueError("批量存档候选观察数据损坏。")
    return tuple(parsed)


def _required_string(value: dict[str, object], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str):
        raise ValueError("批量存档候选观察数据损坏。")
    return result


def _optional_string(value: dict[str, object], key: str) -> str | None:
    result = value.get(key)
    if result is not None and not isinstance(result, str):
        raise ValueError("批量存档候选观察数据损坏。")
    return result


def _required_int(value: dict[str, object], key: str) -> int:
    result = value.get(key)
    if type(result) is not int:
        raise ValueError("批量存档候选观察数据损坏。")
    return result
