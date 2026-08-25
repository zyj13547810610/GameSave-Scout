"""Transactional persistence for guided save detection sessions."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from typing import Any, cast
from uuid import uuid4

from gamesave_scout.db.connection import ConnectionFactory
from gamesave_scout.db.writer import DbWriter
from gamesave_scout.saves.guided_models import (
    GuidedDiscoveryDraft,
    GuidedDiscoveryKind,
    GuidedReviewStatus,
    GuidedSaveDiscovery,
    GuidedSaveSession,
    GuidedScopeOption,
    GuidedScopeSource,
    GuidedSessionStatus,
)


class ActiveGuidedSessionError(RuntimeError):
    """Raised when another guided session already owns the active slot."""


class GuidedSessionNotFoundError(LookupError):
    """Raised when a guided session ID does not exist."""


class InvalidGuidedSessionState(RuntimeError):
    """Raised when a guided session cannot perform the requested transition."""


class GuidedSaveRepository:
    def __init__(self, factory: ConnectionFactory, writer: DbWriter) -> None:
        self._factory = factory
        self._writer = writer

    def create_session(
        self,
        session_id: str,
        game_id: str,
        started_at: str,
        approved_scopes: Sequence[GuidedScopeOption],
        unavailable_scopes: Sequence[str] = (),
    ) -> GuidedSaveSession:
        def operation(connection: sqlite3.Connection) -> sqlite3.Row:
            try:
                connection.execute(
                    """
                    INSERT INTO save_detection_sessions(
                        id, game_id, status, active_slot, started_at,
                        approved_scopes_json, unavailable_scopes_json
                    ) VALUES (?, ?, 'preparing', 1, ?, ?, ?)
                    """,
                    (
                        session_id,
                        game_id,
                        started_at,
                        _dump_scopes(approved_scopes),
                        _dump_strings(unavailable_scopes),
                    ),
                )
            except sqlite3.IntegrityError as error:
                if "save_detection_sessions.active_slot" in str(error):
                    raise ActiveGuidedSessionError(
                        "已有引导式存档检测会话正在运行。"
                    ) from error
                raise
            return _select_session(connection, session_id)

        return _session_from_row(self._writer.submit(operation).result())

    def set_monitoring(
        self,
        session_id: str,
        monitoring_started_at: str,
        *,
        root_pid: int,
        process_tracking_degraded: bool = False,
    ) -> GuidedSaveSession:
        return self._transition(
            session_id,
            expected=("preparing",),
            sql="""
                UPDATE save_detection_sessions
                SET status = 'monitoring', monitoring_started_at = ?, root_pid = ?,
                    process_tracking_degraded = ?
                WHERE id = ?
            """,
            parameters=(
                monitoring_started_at,
                root_pid,
                int(process_tracking_degraded),
                session_id,
            ),
        )

    def mark_settling(
        self, session_id: str, save_marked_at: str
    ) -> GuidedSaveSession:
        return self._transition(
            session_id,
            expected=("monitoring",),
            sql="""
                UPDATE save_detection_sessions
                SET status = 'settling', save_marked_at = ?
                WHERE id = ?
            """,
            parameters=(save_marked_at, session_id),
        )

    def begin_settling(self, session_id: str) -> GuidedSaveSession:
        return self._transition(
            session_id,
            expected=("monitoring",),
            sql="""
                UPDATE save_detection_sessions
                SET status = 'settling'
                WHERE id = ?
            """,
            parameters=(session_id,),
        )

    def set_process_tracking_degraded(self, session_id: str) -> GuidedSaveSession:
        return self._transition(
            session_id,
            expected=("monitoring", "settling"),
            sql="""
                UPDATE save_detection_sessions
                SET process_tracking_degraded = 1
                WHERE id = ?
            """,
            parameters=(session_id,),
        )

    def complete(
        self,
        session_id: str,
        finished_at: str,
        discoveries: Sequence[GuidedDiscoveryDraft],
        *,
        overflowed_scopes: Sequence[str] = (),
        truncated_scopes: Sequence[str] = (),
        result_summary: Mapping[str, int] | None = None,
    ) -> GuidedSaveSession:
        def operation(connection: sqlite3.Connection) -> sqlite3.Row:
            _require_state(connection, session_id, ("monitoring", "settling"))
            connection.execute(
                """
                DELETE FROM save_discoveries
                WHERE detection_session_id = ? AND review_status = 'unreviewed'
                """,
                (session_id,),
            )
            for draft in discoveries:
                connection.execute(
                    """
                    INSERT INTO save_discoveries(
                        id, detection_session_id, candidate_template, display_path,
                        path_key, kind, confidence, evidence_json,
                        representative_files_json, first_changed_at, last_changed_at,
                        mark_offset_ms, affected_by_overflow,
                        affected_by_truncation, preselected
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        session_id,
                        draft.candidate_template,
                        draft.display_path,
                        draft.path_key,
                        draft.kind,
                        draft.confidence,
                        _dump_strings(draft.evidence),
                        _dump_strings(draft.representative_files),
                        draft.first_changed_at,
                        draft.last_changed_at,
                        draft.mark_offset_ms,
                        int(draft.affected_by_overflow),
                        int(draft.affected_by_truncation),
                        int(draft.preselected),
                    ),
                )
            connection.execute(
                """
                UPDATE save_detection_sessions
                SET status = 'completed', active_slot = NULL, finished_at = ?,
                    overflowed_scopes_json = ?, truncated_scopes_json = ?,
                    result_summary_json = ?
                WHERE id = ?
                """,
                (
                    finished_at,
                    _dump_strings(overflowed_scopes),
                    _dump_strings(truncated_scopes),
                    _dump_summary(result_summary or {}),
                    session_id,
                ),
            )
            return _select_session(connection, session_id)

        return _session_from_row(self._writer.submit(operation).result())

    def fail(
        self,
        session_id: str,
        finished_at: str,
        error_code: str,
        error_summary: str,
    ) -> GuidedSaveSession:
        return self._finish_without_discoveries(
            session_id,
            status="failed",
            finished_at=finished_at,
            error_code=error_code,
            error_summary=error_summary,
        )

    def cancel(self, session_id: str, finished_at: str) -> GuidedSaveSession:
        return self._finish_without_discoveries(
            session_id,
            status="cancelled",
            finished_at=finished_at,
        )

    def recover_interrupted(self, finished_at: str) -> int:
        def operation(connection: sqlite3.Connection) -> int:
            cursor = connection.execute(
                """
                UPDATE save_detection_sessions
                SET status = 'interrupted', active_slot = NULL, finished_at = ?,
                    error_code = COALESCE(error_code, 'application_interrupted'),
                    error_summary = COALESCE(error_summary, '应用退出前会话未完成。')
                WHERE status IN ('preparing', 'monitoring', 'settling')
                  AND active_slot = 1
                """,
                (finished_at,),
            )
            return cursor.rowcount

        return self._writer.submit(operation).result()

    def active(self) -> GuidedSaveSession | None:
        with self._factory.connect(readonly=True) as connection:
            row = connection.execute(
                """
                SELECT * FROM save_detection_sessions
                WHERE active_slot = 1
                ORDER BY rowid DESC
                LIMIT 1
                """
            ).fetchone()
        return None if row is None else _session_from_row(row)

    def get_session(self, session_id: str) -> GuidedSaveSession | None:
        with self._factory.connect(readonly=True) as connection:
            row = connection.execute(
                "SELECT * FROM save_detection_sessions WHERE id = ?", (session_id,)
            ).fetchone()
        return None if row is None else _session_from_row(row)

    def latest_reviewable(self, game_id: str | None = None) -> GuidedSaveSession | None:
        parameters: tuple[str, ...] = () if game_id is None else (game_id,)
        game_filter = "" if game_id is None else "AND sessions.game_id = ?"
        with self._factory.connect(readonly=True) as connection:
            row = connection.execute(
                f"""
                SELECT sessions.*
                FROM save_detection_sessions AS sessions
                WHERE sessions.status = 'completed'
                  {game_filter}
                  AND EXISTS (
                    SELECT 1
                    FROM save_discoveries AS discoveries
                    WHERE discoveries.detection_session_id = sessions.id
                      AND discoveries.review_status = 'unreviewed'
                  )
                ORDER BY sessions.finished_at DESC, sessions.rowid DESC
                LIMIT 1
                """,
                parameters,
            ).fetchone()
        return None if row is None else _session_from_row(row)

    def list_discoveries(self, session_id: str) -> tuple[GuidedSaveDiscovery, ...]:
        with self._factory.connect(readonly=True) as connection:
            rows = connection.execute(
                """
                SELECT * FROM save_discoveries
                WHERE detection_session_id = ?
                ORDER BY confidence DESC, path_key, rowid
                """,
                (session_id,),
            ).fetchall()
        return tuple(_discovery_from_row(row) for row in rows)

    def discard(self, session_id: str) -> int:
        def operation(connection: sqlite3.Connection) -> int:
            _require_state(connection, session_id, ("completed",))
            cursor = connection.execute(
                """
                UPDATE save_discoveries
                SET review_status = 'ignored'
                WHERE detection_session_id = ? AND review_status = 'unreviewed'
                """,
                (session_id,),
            )
            return cursor.rowcount

        return self._writer.submit(operation).result()

    def _transition(
        self,
        session_id: str,
        *,
        expected: Sequence[GuidedSessionStatus],
        sql: str,
        parameters: tuple[object, ...],
    ) -> GuidedSaveSession:
        def operation(connection: sqlite3.Connection) -> sqlite3.Row:
            _require_state(connection, session_id, expected)
            connection.execute(sql, parameters)
            return _select_session(connection, session_id)

        return _session_from_row(self._writer.submit(operation).result())

    def _finish_without_discoveries(
        self,
        session_id: str,
        *,
        status: GuidedSessionStatus,
        finished_at: str,
        error_code: str | None = None,
        error_summary: str | None = None,
    ) -> GuidedSaveSession:
        def operation(connection: sqlite3.Connection) -> sqlite3.Row:
            _require_state(connection, session_id, ("preparing", "monitoring", "settling"))
            connection.execute(
                """
                UPDATE save_detection_sessions
                SET status = ?, active_slot = NULL, finished_at = ?,
                    error_code = ?, error_summary = ?
                WHERE id = ?
                """,
                (status, finished_at, error_code, error_summary, session_id),
            )
            return _select_session(connection, session_id)

        return _session_from_row(self._writer.submit(operation).result())


def _select_session(connection: sqlite3.Connection, session_id: str) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM save_detection_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if row is None:
        raise GuidedSessionNotFoundError(session_id)
    return cast(sqlite3.Row, row)


def _require_state(
    connection: sqlite3.Connection,
    session_id: str,
    expected: Sequence[GuidedSessionStatus],
) -> sqlite3.Row:
    row = _select_session(connection, session_id)
    if row["status"] not in expected:
        expected_text = ", ".join(expected)
        raise InvalidGuidedSessionState(
            f"会话 {session_id} 当前状态 {row['status']}，需要状态：{expected_text}。"
        )
    return row


def _session_from_row(row: sqlite3.Row) -> GuidedSaveSession:
    return GuidedSaveSession(
        id=str(row["id"]),
        game_id=str(row["game_id"]),
        status=cast(GuidedSessionStatus, row["status"]),
        started_at=str(row["started_at"]),
        monitoring_started_at=_optional_string(row["monitoring_started_at"]),
        save_marked_at=_optional_string(row["save_marked_at"]),
        finished_at=_optional_string(row["finished_at"]),
        root_pid=None if row["root_pid"] is None else int(row["root_pid"]),
        approved_scopes=_load_scopes(str(row["approved_scopes_json"])),
        unavailable_scopes=_load_strings(str(row["unavailable_scopes_json"])),
        overflowed_scopes=_load_strings(str(row["overflowed_scopes_json"])),
        truncated_scopes=_load_strings(str(row["truncated_scopes_json"])),
        process_tracking_degraded=bool(row["process_tracking_degraded"]),
        result_summary=_load_summary(str(row["result_summary_json"])),
        error_code=_optional_string(row["error_code"]),
        error_summary=_optional_string(row["error_summary"]),
    )


def _discovery_from_row(row: sqlite3.Row) -> GuidedSaveDiscovery:
    return GuidedSaveDiscovery(
        id=str(row["id"]),
        detection_session_id=str(row["detection_session_id"]),
        candidate_template=str(row["candidate_template"]),
        display_path=str(row["display_path"]),
        path_key=str(row["path_key"]),
        kind=cast(GuidedDiscoveryKind, row["kind"]),
        confidence=float(row["confidence"]),
        evidence=_load_strings(str(row["evidence_json"])),
        representative_files=_load_strings(str(row["representative_files_json"])),
        first_changed_at=_optional_string(row["first_changed_at"]),
        last_changed_at=_optional_string(row["last_changed_at"]),
        mark_offset_ms=(
            None if row["mark_offset_ms"] is None else int(row["mark_offset_ms"])
        ),
        affected_by_overflow=bool(row["affected_by_overflow"]),
        affected_by_truncation=bool(row["affected_by_truncation"]),
        preselected=bool(row["preselected"]),
        review_status=cast(GuidedReviewStatus, row["review_status"]),
        save_location_id=_optional_string(row["save_location_id"]),
    )


def _dump_scopes(scopes: Sequence[GuidedScopeOption]) -> str:
    return json.dumps(
        [asdict(scope) for scope in scopes], ensure_ascii=False, separators=(",", ":")
    )


def _dump_strings(values: Sequence[str]) -> str:
    return json.dumps(list(values), ensure_ascii=False, separators=(",", ":"))


def _dump_summary(summary: Mapping[str, int]) -> str:
    return json.dumps(dict(summary), ensure_ascii=False, separators=(",", ":"))


def _load_scopes(value: str) -> tuple[GuidedScopeOption, ...]:
    loaded: Any = json.loads(value)
    if not isinstance(loaded, list) or not all(isinstance(item, dict) for item in loaded):
        raise ValueError("Expected a JSON object array for guided scopes.")
    scopes: list[GuidedScopeOption] = []
    for raw in loaded:
        item = cast(dict[str, Any], raw)
        scopes.append(
            GuidedScopeOption(
                id=_required_string(item, "id"),
                label=_required_string(item, "label"),
                display_path=_required_string(item, "display_path"),
                path_template=_required_string(item, "path_template"),
                source=cast(GuidedScopeSource, _required_string(item, "source")),
                default_selected=_required_bool(item, "default_selected"),
                available=_required_bool(item, "available"),
                unavailable_reason=_optional_string(item.get("unavailable_reason")),
            )
        )
    return tuple(scopes)


def _load_strings(value: str) -> tuple[str, ...]:
    loaded: Any = json.loads(value)
    if not isinstance(loaded, list) or not all(isinstance(item, str) for item in loaded):
        raise ValueError("Expected a JSON string array.")
    return tuple(loaded)


def _load_summary(value: str) -> dict[str, int]:
    loaded: Any = json.loads(value)
    if not isinstance(loaded, dict) or not all(
        isinstance(key, str) and isinstance(item, int) and not isinstance(item, bool)
        for key, item in loaded.items()
    ):
        raise ValueError("Expected a JSON integer object for the guided result summary.")
    return cast(dict[str, int], loaded)


def _required_string(item: Mapping[str, object], key: str) -> str:
    value = item.get(key)
    if not isinstance(value, str):
        raise ValueError(f"Expected guided scope field {key} to be a string.")
    return value


def _required_bool(item: Mapping[str, object], key: str) -> bool:
    value = item.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"Expected guided scope field {key} to be a boolean.")
    return value


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Expected an optional string value.")
    return value
