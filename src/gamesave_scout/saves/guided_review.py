"""Transactional acceptance and dismissal of guided save discoveries."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from typing import cast

from gamesave_scout.db.connection import ConnectionFactory
from gamesave_scout.db.writer import DbWriter
from gamesave_scout.saves.guided_repository import GuidedSaveRepository
from gamesave_scout.saves.location_persistence import upsert_confirmed_location
from gamesave_scout.saves.models import SaveLocation, SaveLocationKind, SaveLocationSuggestion
from gamesave_scout.saves.service import SaveLocationService


class GuidedReviewError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class GuidedSaveReviewService:
    def __init__(
        self,
        factory: ConnectionFactory,
        writer: DbWriter,
        repository: GuidedSaveRepository,
        save_locations: SaveLocationService,
    ) -> None:
        self._factory = factory
        self._writer = writer
        self._repository = repository
        self._save_locations = save_locations

    def accept(
        self,
        session_id: str,
        discovery_ids: Sequence[str],
        confirm_registry: bool,
    ) -> tuple[SaveLocation, ...]:
        unique_ids = tuple(dict.fromkeys(discovery_ids))
        if not unique_ids:
            raise GuidedReviewError(
                "guided_discovery_empty", "至少选择一个引导式存档候选。"
            )

        with self._factory.connect(readonly=True) as connection:
            game_id, rows = _validated_rows(connection, session_id, unique_ids)

        if any(row["kind"] == "registry" for row in rows) and not confirm_registry:
            raise GuidedReviewError(
                "registry_confirmation_required",
                "注册表候选需要额外确认后才能接受。",
            )
        prepared = tuple(
            self._save_locations.prepare_suggestion(
                game_id,
                SaveLocationSuggestion(
                    kind=cast(SaveLocationKind, row["kind"]),
                    path_template=str(row["candidate_template"]),
                    display_path=str(row["display_path"]),
                    source="dynamic",
                    confidence=float(row["confidence"]),
                    evidence=_string_tuple(row["evidence_json"]),
                    suggestion_id=str(row["id"]),
                    preselected=bool(row["preselected"]),
                ),
            )
            for row in rows
        )

        def operation(connection: sqlite3.Connection) -> tuple[SaveLocation, ...]:
            _validated_rows(connection, session_id, unique_ids)
            accepted: list[SaveLocation] = []
            for discovery_id, location_input in zip(unique_ids, prepared, strict=True):
                location = upsert_confirmed_location(connection, location_input)
                changed = connection.execute(
                    """
                    UPDATE save_discoveries
                    SET review_status = 'accepted', save_location_id = ?
                    WHERE id = ? AND detection_session_id = ?
                      AND review_status IN ('unreviewed', 'accepted')
                    """,
                    (location.id, discovery_id, session_id),
                ).rowcount
                if changed == 0:
                    raise GuidedReviewError(
                        "guided_discovery_invalid",
                        "引导式存档候选已经失效，请刷新后重试。",
                    )
                accepted.append(location)
            return tuple(accepted)

        return self._writer.submit(operation).result()

    def discard(self, session_id: str) -> int:
        return self._repository.discard(session_id)


def _validated_rows(
    connection: sqlite3.Connection,
    session_id: str,
    discovery_ids: Sequence[str],
) -> tuple[str, tuple[sqlite3.Row, ...]]:
    session = connection.execute(
        "SELECT game_id, status FROM save_detection_sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    if session is None:
        raise GuidedReviewError(
            "guided_session_not_found", "找不到引导式寻找会话。"
        )
    if session["status"] != "completed":
        raise GuidedReviewError(
            "guided_session_not_reviewable", "该引导式寻找会话尚不能审核。"
        )

    rows: list[sqlite3.Row] = []
    for discovery_id in discovery_ids:
        row = connection.execute(
            "SELECT * FROM save_discoveries WHERE id = ?", (discovery_id,)
        ).fetchone()
        if (
            row is None
            or row["detection_session_id"] != session_id
            or row["review_status"] not in ("unreviewed", "accepted")
        ):
            raise GuidedReviewError(
                "guided_discovery_invalid",
                "引导式存档候选已经失效，请刷新后重试。",
            )
        rows.append(row)
    return str(session["game_id"]), tuple(rows)


def _string_tuple(value: str) -> tuple[str, ...]:
    import json

    loaded = json.loads(value)
    if not isinstance(loaded, list) or not all(isinstance(item, str) for item in loaded):
        raise GuidedReviewError(
            "guided_discovery_invalid", "引导式存档候选数据无效。"
        )
    return tuple(loaded)
