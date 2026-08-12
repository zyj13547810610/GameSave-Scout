"""Cancellable two-phase game-library scans."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from gameshelf.bridge.tasks import TaskCancelled, TaskContext
from gameshelf.db.writer import DbWriter
from gameshelf.engines.models import DetectionOutcome, EngineEvidence
from gameshelf.engines.service import EngineDetectionService
from gameshelf.library.models import Game, ScanRoot
from gameshelf.library.repository import LibraryRepository, game_from_row
from gameshelf.library.service import RootNotFoundError
from gameshelf.scanning.discovery import RootUnavailableError, enumerate_candidates
from gameshelf.scanning.executable_ranker import rank_executables
from gameshelf.scanning.models import DirectoryCandidate
from gameshelf.scanning.path_keys import is_same_or_child, windows_path_key
from gameshelf.scanning.reconcile import MoveSuggestion, reconcile_session

type ScanKind = Literal["quick", "full"]
type ScanStatus = Literal["completed", "cancelled", "failed", "unavailable"]


@dataclass(frozen=True)
class ScanSummary:
    session_id: str
    status: ScanStatus
    discovered: int
    added: int
    updated: int
    missing: int
    warnings: int
    move_suggestions: tuple[MoveSuggestion, ...]
    games: tuple[Game, ...] = ()


class ScanService:
    def __init__(
        self,
        repository: LibraryRepository,
        writer: DbWriter,
        engine_detection: EngineDetectionService | None = None,
    ) -> None:
        self._repository = repository
        self._writer = writer
        self._engine_detection = engine_detection

    def scan_root(
        self, root_id: str, scan_kind: ScanKind, context: TaskContext
    ) -> ScanSummary:
        if scan_kind not in {"quick", "full"}:
            raise ValueError(f"Unknown scan kind: {scan_kind}")
        root = self._repository.get_root(root_id)
        if root is None:
            raise RootNotFoundError(root_id)
        session_id = self._create_session(root_id, scan_kind)
        discovered = 0
        warnings = 0
        batch: list[tuple[str, str]] = []
        try:
            context.raise_if_cancelled()
            for candidate in self._candidates(root, scan_kind, context):
                context.raise_if_cancelled()
                install_key = windows_path_key(candidate.path)
                if self._owning_root_id(install_key) != root.id:
                    continue
                ranked = rank_executables(candidate.path)
                recommendation = ranked[0] if ranked else None
                executable = (
                    candidate.path.joinpath(*recommendation.relative_path.split("/"))
                    if recommendation is not None
                    else None
                )
                detection = (
                    self._engine_detection.detect(candidate.path, executable)
                    if self._engine_detection is not None
                    else DetectionOutcome(None, (), False)
                )
                warnings += len(detection.diagnostics)
                payload = {
                    "relativeDir": candidate.relative_dir,
                    "title": candidate.path.name,
                    "mainExeRelpath": (
                        recommendation.relative_path if recommendation is not None else None
                    ),
                    "exeArch": (
                        recommendation.architecture if recommendation is not None else "unknown"
                    ),
                    **_engine_payload(detection),
                }
                batch.append(
                    (
                        install_key,
                        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    )
                )
                discovered += 1
                context.report(discovered, None, f"Scanning {candidate.relative_dir}")
                if len(batch) == 200:
                    self._stage_batch(session_id, batch)
                    batch.clear()
            if batch:
                self._stage_batch(session_id, batch)
            context.raise_if_cancelled()
        except RootUnavailableError as error:
            self._finish_without_reconcile(session_id, root.id, "unavailable", str(error))
            return _empty_summary(session_id, "unavailable", discovered)
        except TaskCancelled:
            self._finish_without_reconcile(session_id, root.id, "cancelled", "Scan cancelled.")
            raise
        except Exception as error:
            self._finish_without_reconcile(session_id, root.id, "failed", str(error))
            raise

        result = self._writer.submit(
            lambda connection: reconcile_session(connection, session_id, root, scan_kind)
        ).result()
        return ScanSummary(
            session_id=session_id,
            status="completed",
            discovered=discovered,
            added=result.added,
            updated=result.updated,
            missing=result.missing,
            warnings=warnings,
            move_suggestions=result.move_suggestions,
            games=result.games,
        )

    def confirm_move(
        self,
        session_id: str,
        existing_game_id: str,
        candidate_relative_dir: str,
    ) -> Game:
        def operation(connection: sqlite3.Connection) -> Game:
            session = connection.execute(
                "SELECT root_id, status, scope_json FROM scan_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if session is None or session["status"] != "completed":
                raise ConfirmMoveError("The referenced scan session is not complete.")
            scope = json.loads(session["scope_json"])
            expected = {
                "existingGameId": existing_game_id,
                "candidateRelativeDir": candidate_relative_dir,
            }
            if expected not in scope.get("moveCandidates", []):
                raise ConfirmMoveError("The move was not suggested by this scan session.")
            existing = connection.execute(
                "SELECT * FROM games WHERE id = ? AND status = 'missing'",
                (existing_game_id,),
            ).fetchone()
            if existing is None:
                raise ConfirmMoveError("The original game is no longer missing.")
            candidate = connection.execute(
                """
                SELECT * FROM games
                WHERE scan_root_id = ? AND relative_dir = ? AND status = 'installed'
                """,
                (session["root_id"], candidate_relative_dir),
            ).fetchone()
            if candidate is None or candidate["id"] == existing_game_id:
                raise ConfirmMoveError("The suggested target is no longer available.")

            candidate_evidence = json.loads(candidate["engine_evidence_json"])
            evidence_codes = {
                str(item.get("code"))
                for item in candidate_evidence
                if isinstance(item, dict)
            }
            detection_failed = (
                candidate["detected_engine_id"] is None
                and "detector_error" in evidence_codes
                and not any(code.startswith("candidate:") for code in evidence_codes)
            )
            connection.execute("DELETE FROM games WHERE id = ?", (candidate["id"],))
            now = _utc_now()
            connection.execute(
                """
                UPDATE games
                SET scan_root_id = ?, relative_dir = ?, install_path_key = ?,
                    status = 'installed', missing_since = NULL,
                    detected_title = ?, detected_main_exe_relpath = ?,
                    main_exe_relpath = CASE WHEN main_exe_is_manual = 1
                        THEN main_exe_relpath ELSE ? END,
                    detected_engine_id = CASE
                        WHEN ? THEN detected_engine_id ELSE ? END,
                    detected_engine_variant = CASE
                        WHEN ? THEN detected_engine_variant ELSE ? END,
                    engine_id = CASE
                        WHEN engine_is_manual = 1 OR ? THEN engine_id ELSE ? END,
                    engine_variant = CASE
                        WHEN engine_is_manual = 1 OR ? THEN engine_variant ELSE ? END,
                    engine_confidence = CASE
                        WHEN ? THEN engine_confidence ELSE ? END,
                    engine_evidence_json = CASE
                        WHEN ? THEN engine_evidence_json ELSE ? END,
                    engine_rules_version = CASE
                        WHEN ? THEN engine_rules_version ELSE ? END,
                    exe_arch = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    candidate["scan_root_id"],
                    candidate["relative_dir"],
                    candidate["install_path_key"],
                    candidate["detected_title"],
                    candidate["detected_main_exe_relpath"],
                    candidate["main_exe_relpath"],
                    detection_failed,
                    candidate["detected_engine_id"],
                    detection_failed,
                    candidate["detected_engine_variant"],
                    detection_failed,
                    candidate["detected_engine_id"],
                    detection_failed,
                    candidate["detected_engine_variant"],
                    detection_failed,
                    candidate["engine_confidence"],
                    detection_failed,
                    candidate["engine_evidence_json"],
                    detection_failed,
                    candidate["engine_rules_version"],
                    candidate["exe_arch"],
                    now,
                    existing_game_id,
                ),
            )
            row = connection.execute(
                "SELECT * FROM games WHERE id = ?", (existing_game_id,)
            ).fetchone()
            assert row is not None
            return game_from_row(row)

        return self._writer.submit(operation).result()

    def _candidates(
        self, root: ScanRoot, scan_kind: ScanKind, context: TaskContext
    ) -> Iterator[DirectoryCandidate]:
        if scan_kind == "quick" and root.scan_mode == "recursive":
            for game in self._repository.list_games():
                if game.scan_root_id != root.id or game.relative_dir is None:
                    continue
                context.raise_if_cancelled()
                path = Path(root.display_path).joinpath(*game.relative_dir.split("/"))
                if not path.is_dir():
                    continue
                yield DirectoryCandidate(
                    path=path,
                    relative_dir=game.relative_dir,
                    depth=len(game.relative_dir.split("/")),
                    reason="direct_child",
                )
            return
        yield from enumerate_candidates(root, context)

    def _owning_root_id(self, install_key: str) -> str | None:
        eligible = [
            root
            for root in self._repository.list_roots()
            if root.enabled and is_same_or_child(install_key, root.path_key)
        ]
        if not eligible:
            return None
        return max(eligible, key=lambda root: len(root.path_key)).id

    def _create_session(self, root_id: str, scan_kind: ScanKind) -> str:
        session_id = str(uuid4())
        started_at = _utc_now()
        scope = json.dumps({"scanKind": scan_kind}, separators=(",", ":"))
        self._writer.submit(
            lambda connection: connection.execute(
                """
                INSERT INTO scan_sessions(id, root_id, kind, status, started_at, scope_json)
                VALUES (?, ?, 'library', 'running', ?, ?)
                """,
                (session_id, root_id, started_at, scope),
            ).rowcount
        ).result()
        return session_id

    def _stage_batch(self, session_id: str, batch: list[tuple[str, str]]) -> None:
        staged = tuple(batch)

        def operation(connection: sqlite3.Connection) -> None:
            connection.executemany(
                """
                INSERT INTO scan_observations(session_id, install_path_key, payload_json)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id, install_path_key)
                DO UPDATE SET payload_json = excluded.payload_json
                """,
                ((session_id, path_key, payload) for path_key, payload in staged),
            )

        self._writer.submit(operation).result()

    def _finish_without_reconcile(
        self,
        session_id: str,
        root_id: str,
        status: ScanStatus,
        error_summary: str,
    ) -> None:
        finished_at = _utc_now()

        def operation(connection: sqlite3.Connection) -> None:
            connection.execute(
                "DELETE FROM scan_observations WHERE session_id = ?", (session_id,)
            )
            connection.execute(
                """
                UPDATE scan_sessions
                SET status = ?, finished_at = ?, error_summary = ?
                WHERE id = ?
                """,
                (status, finished_at, error_summary, session_id),
            )
            connection.execute(
                """
                UPDATE scan_roots
                SET last_scan_status = ?, last_error = ?
                WHERE id = ?
                """,
                (status, error_summary, root_id),
            )

        self._writer.submit(operation).result()


def _empty_summary(
    session_id: str, status: ScanStatus, discovered: int
) -> ScanSummary:
    return ScanSummary(session_id, status, discovered, 0, 0, 0, 0, ())


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _engine_payload(outcome: DetectionOutcome) -> dict[str, object]:
    match = outcome.best
    evidence: tuple[EngineEvidence, ...]
    if match is not None:
        evidence = match.evidence
    elif outcome.ambiguous:
        evidence = tuple(
            EngineEvidence(
                code=f"candidate:{candidate.engine_id}",
                detail=candidate.variant or candidate.engine_id,
                weight=candidate.confidence,
            )
            for candidate in outcome.alternatives
        )
    else:
        evidence = ()
    evidence_json = [
        {
            "code": item.code,
            "detail": item.detail,
            "path": item.path,
            "weight": item.weight,
        }
        for item in (*evidence, *outcome.diagnostics)
    ]
    return {
        "engineDetectionFailed": bool(outcome.diagnostics)
        and match is None
        and not outcome.ambiguous,
        "detectedEngineId": match.engine_id if match is not None else None,
        "detectedEngineVariant": match.variant if match is not None else None,
        "engineConfidence": (
            match.confidence
            if match is not None
            else max(
                (candidate.confidence for candidate in outcome.alternatives),
                default=None,
            )
        ),
        "engineEvidence": evidence_json,
        "engineRulesVersion": (
            match.rule_version
            if match is not None
            else ",".join(
                dict.fromkeys(candidate.rule_version for candidate in outcome.alternatives)
            )
            or None
        ),
    }


class ConfirmMoveError(ValueError):
    """Raised when a move suggestion is stale or cannot be verified."""
