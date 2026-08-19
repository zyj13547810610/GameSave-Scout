"""Apply a completed scan session to the visible library in one transaction."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import PurePosixPath
from uuid import uuid4

from gameshelf.library.models import Game, ScanRoot
from gameshelf.library.repository import games_from_rows, scan_root_from_row
from gameshelf.scanning.analysis_cache import (
    PendingAnalysisCache,
    delete_analysis_cache,
    upsert_analysis_cache,
)
from gameshelf.scanning.discovery import is_excluded


@dataclass(frozen=True)
class MoveSuggestion:
    existing_game_id: str
    candidate_relative_dir: str
    confidence: float
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class ReconcileResult:
    added: int
    updated: int
    missing: int
    games: tuple[Game, ...]
    move_suggestions: tuple[MoveSuggestion, ...]


def reconcile_session(
    connection: sqlite3.Connection,
    session_id: str,
    root: ScanRoot,
    scan_kind: str,
    *,
    quick_missing_game_ids: tuple[str, ...] = (),
) -> ReconcileResult:
    current_root = connection.execute(
        "SELECT * FROM scan_roots WHERE id = ?", (root.id,)
    ).fetchone()
    if current_root is None:
        raise LookupError("The scan root was removed before reconciliation.")
    root = scan_root_from_row(current_root)
    observations = connection.execute(
        """
        SELECT install_path_key, payload_json
        FROM scan_observations
        WHERE session_id = ?
        ORDER BY install_path_key
        """,
        (session_id,),
    ).fetchall()
    now = _utc_now()
    added = 0
    updated = 0
    suggestions: list[MoveSuggestion] = []
    observed_game_ids: list[str] = []

    for observation in observations:
        install_key = str(observation["install_path_key"])
        payload = json.loads(observation["payload_json"])
        if is_excluded(str(payload["relativeDir"]), root.exclusions):
            continue
        existing = connection.execute(
            "SELECT * FROM games WHERE install_path_key = ?", (install_key,)
        ).fetchone()
        if existing is None:
            suggestions.extend(_suggest_moves(connection, payload))
            game_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO games(
                    id, scan_root_id, relative_dir, install_path_key,
                    title, detected_title, version, detected_version, status,
                    detected_engine_id, detected_engine_variant,
                    engine_id, engine_variant, engine_confidence,
                    engine_evidence_json, engine_rules_version,
                    detected_main_exe_relpath, main_exe_relpath, exe_arch,
                    added_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, 'installed',
                    ?, ?, ?, ?, ?, json(?), ?,
                    ?, ?, ?, ?, ?
                )
                """,
                (
                    game_id,
                    root.id,
                    payload["relativeDir"],
                    install_key,
                    payload["title"],
                    payload["title"],
                    payload["version"],
                    payload["version"],
                    payload["detectedEngineId"],
                    payload["detectedEngineVariant"],
                    payload["detectedEngineId"],
                    payload["detectedEngineVariant"],
                    payload["engineConfidence"],
                    json.dumps(payload["engineEvidence"], ensure_ascii=False),
                    payload["engineRulesVersion"],
                    payload["mainExeRelpath"],
                    payload["mainExeRelpath"],
                    payload["exeArch"],
                    now,
                    now,
                ),
            )
            added += 1
        else:
            game_id = str(existing["id"])
            connection.execute(
                """
                UPDATE games
                SET scan_root_id = ?, relative_dir = ?, install_path_key = ?,
                    detected_title = ?,
                    title = CASE WHEN title_is_manual = 1 THEN title ELSE ? END,
                    detected_version = ?,
                    version = CASE WHEN version_is_manual = 1 THEN version ELSE ? END,
                    status = 'installed',
                    detected_engine_id = CASE WHEN ? THEN detected_engine_id ELSE ? END,
                    detected_engine_variant = CASE
                        WHEN ? THEN detected_engine_variant ELSE ? END,
                    engine_id = CASE
                        WHEN engine_is_manual = 1 OR ? THEN engine_id ELSE ? END,
                    engine_variant = CASE
                        WHEN engine_is_manual = 1 OR ? THEN engine_variant ELSE ? END,
                    engine_confidence = CASE
                        WHEN ? THEN engine_confidence ELSE ? END,
                    engine_evidence_json = CASE
                        WHEN ? THEN engine_evidence_json ELSE json(?) END,
                    engine_rules_version = CASE
                        WHEN ? THEN engine_rules_version ELSE ? END,
                    detected_main_exe_relpath = ?,
                    main_exe_relpath = CASE
                        WHEN main_exe_is_manual = 1 THEN main_exe_relpath ELSE ? END,
                    exe_arch = CASE
                        WHEN main_exe_is_manual = 1 THEN exe_arch ELSE ? END,
                    updated_at = ?, missing_since = NULL
                WHERE id = ?
                """,
                (
                    root.id,
                    payload["relativeDir"],
                    install_key,
                    payload["title"],
                    payload["title"],
                    payload["version"],
                    payload["version"],
                    payload["engineDetectionFailed"],
                    payload["detectedEngineId"],
                    payload["engineDetectionFailed"],
                    payload["detectedEngineVariant"],
                    payload["engineDetectionFailed"],
                    payload["detectedEngineId"],
                    payload["engineDetectionFailed"],
                    payload["detectedEngineVariant"],
                    payload["engineDetectionFailed"],
                    payload["engineConfidence"],
                    payload["engineDetectionFailed"],
                    json.dumps(payload["engineEvidence"], ensure_ascii=False),
                    payload["engineDetectionFailed"],
                    payload["engineRulesVersion"],
                    payload["mainExeRelpath"],
                    payload["mainExeRelpath"],
                    payload["exeArch"],
                    now,
                    game_id,
                ),
            )
            updated += 1
        pending_cache = _pending_analysis_cache(payload.get("analysisCache"))
        if pending_cache is None:
            delete_analysis_cache(connection, game_id)
        else:
            upsert_analysis_cache(connection, game_id, pending_cache, now)
        observed_game_ids.append(game_id)

    missing = 0
    if scan_kind == "full":
        missing = connection.execute(
            """
            UPDATE games
            SET status = 'missing', missing_since = COALESCE(missing_since, ?), updated_at = ?
            WHERE scan_root_id = ?
              AND install_path_key NOT IN (
                SELECT install_path_key FROM scan_observations WHERE session_id = ?
              )
              AND status = 'installed'
            """,
            (now, now, root.id, session_id),
        ).rowcount
    elif quick_missing_game_ids:
        for game_id in quick_missing_game_ids:
            missing += connection.execute(
                """
                UPDATE games
                SET status = 'missing', missing_since = COALESCE(missing_since, ?),
                    updated_at = ?
                WHERE id = ? AND scan_root_id = ? AND status = 'installed'
                """,
                (now, now, game_id, root.id),
            ).rowcount

    connection.execute(
        """
        UPDATE scan_roots
        SET last_scanned_at = ?, last_scan_status = 'completed', last_error = NULL
        WHERE id = ?
        """,
        (now, root.id),
    )
    counts = {
        "discovered": len(observations),
        "added": added,
        "updated": updated,
        "missing": missing,
    }
    scope = {
        "scanKind": scan_kind,
        "moveCandidates": [
            {
                "existingGameId": suggestion.existing_game_id,
                "candidateRelativeDir": suggestion.candidate_relative_dir,
            }
            for suggestion in suggestions
        ],
    }
    connection.execute(
        """
        UPDATE scan_sessions
        SET status = 'completed', finished_at = ?, counts_json = ?, scope_json = ?
        WHERE id = ?
        """,
        (
            now,
            json.dumps(counts, separators=(",", ":")),
            json.dumps(scope, separators=(",", ":")),
            session_id,
        ),
    )

    if observed_game_ids:
        placeholders = ", ".join("?" for _ in observed_game_ids)
        rows = connection.execute(
            f"SELECT * FROM games WHERE id IN ({placeholders})",  # noqa: S608
            observed_game_ids,
        ).fetchall()
        rows_by_id = {str(row["id"]): row for row in rows}
        ordered_rows = tuple(rows_by_id[game_id] for game_id in observed_game_ids)
        games = games_from_rows(connection, ordered_rows)
    else:
        games = ()
    connection.execute("DELETE FROM scan_observations WHERE session_id = ?", (session_id,))
    return ReconcileResult(
        added=added,
        updated=updated,
        missing=missing,
        games=games,
        move_suggestions=tuple(suggestions),
    )


def _suggest_moves(
    connection: sqlite3.Connection, payload: dict[str, object]
) -> list[MoveSuggestion]:
    title = str(payload["title"])
    executable = payload.get("mainExeRelpath")
    executable_stem = (
        PurePosixPath(str(executable)).stem.casefold() if executable is not None else ""
    )
    suggestions: list[MoveSuggestion] = []
    rows = connection.execute(
        "SELECT id, title, main_exe_relpath FROM games WHERE status = 'missing'"
    ).fetchall()
    for row in rows:
        title_score = SequenceMatcher(
            None, title.casefold(), str(row["title"]).casefold()
        ).ratio()
        old_executable = row["main_exe_relpath"]
        old_stem = (
            PurePosixPath(str(old_executable)).stem.casefold()
            if old_executable is not None
            else ""
        )
        exe_match = bool(executable_stem and executable_stem == old_stem)
        confidence = 0.7 * title_score + 0.3 * float(exe_match)
        if confidence < 0.75:
            continue
        evidence = ["similar_title"]
        if exe_match:
            evidence.append("same_executable_name")
        suggestions.append(
            MoveSuggestion(
                existing_game_id=str(row["id"]),
                candidate_relative_dir=str(payload["relativeDir"]),
                confidence=round(confidence, 3),
                evidence=tuple(evidence),
            )
        )
    return suggestions


def _pending_analysis_cache(value: object) -> PendingAnalysisCache | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Invalid analysis cache payload.")
    try:
        executable_relpath = value["executableRelpath"]
        file_size = value["fileSize"]
        modified_time_ns = value["modifiedTimeNs"]
        ranker_rules_version = value["rankerRulesVersion"]
        engine_rules_version = value["engineRulesVersion"]
    except KeyError as error:
        raise ValueError("Incomplete analysis cache payload.") from error
    if (
        not isinstance(executable_relpath, str)
        or not executable_relpath
        or type(file_size) is not int
        or file_size < 0
        or type(modified_time_ns) is not int
        or modified_time_ns < 0
        or not isinstance(ranker_rules_version, str)
        or not ranker_rules_version
        or not isinstance(engine_rules_version, str)
        or not engine_rules_version
    ):
        raise ValueError("Invalid analysis cache payload.")
    return PendingAnalysisCache(
        executable_relpath=executable_relpath,
        file_size=file_size,
        modified_time_ns=modified_time_ns,
        ranker_rules_version=ranker_rules_version,
        engine_rules_version=engine_rules_version,
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
