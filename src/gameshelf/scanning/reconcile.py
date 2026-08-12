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
from gameshelf.library.repository import game_from_row


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
) -> ReconcileResult:
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
                    title, detected_title, status,
                    detected_main_exe_relpath, main_exe_relpath, exe_arch,
                    added_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'installed', ?, ?, ?, ?, ?)
                """,
                (
                    game_id,
                    root.id,
                    payload["relativeDir"],
                    install_key,
                    payload["title"],
                    payload["title"],
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
                    status = 'installed',
                    detected_main_exe_relpath = ?,
                    main_exe_relpath = CASE
                        WHEN main_exe_is_manual = 1 THEN main_exe_relpath ELSE ? END,
                    exe_arch = ?, updated_at = ?, missing_since = NULL
                WHERE id = ?
                """,
                (
                    root.id,
                    payload["relativeDir"],
                    install_key,
                    payload["title"],
                    payload["title"],
                    payload["mainExeRelpath"],
                    payload["mainExeRelpath"],
                    payload["exeArch"],
                    now,
                    game_id,
                ),
            )
            updated += 1
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
    connection.execute(
        """
        UPDATE scan_sessions
        SET status = 'completed', finished_at = ?, counts_json = ?
        WHERE id = ?
        """,
        (now, json.dumps(counts, separators=(",", ":")), session_id),
    )

    games: list[Game] = []
    for game_id in observed_game_ids:
        row = connection.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
        assert row is not None
        games.append(game_from_row(row))
    connection.execute("DELETE FROM scan_observations WHERE session_id = ?", (session_id,))
    return ReconcileResult(
        added=added,
        updated=updated,
        missing=missing,
        games=tuple(games),
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


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
