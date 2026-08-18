"""Persistent fingerprints for reusable game executable analysis."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from gameshelf.db.connection import ConnectionFactory


@dataclass(frozen=True)
class AnalysisCacheEntry:
    game_id: str
    executable_relpath: str
    file_size: int
    modified_time_ns: int
    ranker_rules_version: str
    engine_rules_version: str
    analyzed_at: str


@dataclass(frozen=True)
class PendingAnalysisCache:
    executable_relpath: str
    file_size: int
    modified_time_ns: int
    ranker_rules_version: str
    engine_rules_version: str


class AnalysisCacheRepository:
    """Read committed analysis fingerprints through short-lived connections."""

    def __init__(self, factory: ConnectionFactory) -> None:
        self._factory = factory

    def get(self, game_id: str) -> AnalysisCacheEntry | None:
        with self._factory.connect(readonly=True) as connection:
            row = connection.execute(
                """
                SELECT game_id, executable_relpath, file_size, modified_time_ns,
                       ranker_rules_version, engine_rules_version, analyzed_at
                FROM game_analysis_cache
                WHERE game_id = ?
                """,
                (game_id,),
            ).fetchone()
        if row is None:
            return None
        return AnalysisCacheEntry(
            game_id=str(row["game_id"]),
            executable_relpath=str(row["executable_relpath"]),
            file_size=int(row["file_size"]),
            modified_time_ns=int(row["modified_time_ns"]),
            ranker_rules_version=str(row["ranker_rules_version"]),
            engine_rules_version=str(row["engine_rules_version"]),
            analyzed_at=str(row["analyzed_at"]),
        )


def upsert_analysis_cache(
    connection: sqlite3.Connection,
    game_id: str,
    pending: PendingAnalysisCache,
    analyzed_at: str,
) -> None:
    """Write a fingerprint inside the caller's existing transaction."""

    connection.execute(
        """
        INSERT INTO game_analysis_cache(
            game_id, executable_relpath, file_size, modified_time_ns,
            ranker_rules_version, engine_rules_version, analyzed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(game_id) DO UPDATE SET
            executable_relpath = excluded.executable_relpath,
            file_size = excluded.file_size,
            modified_time_ns = excluded.modified_time_ns,
            ranker_rules_version = excluded.ranker_rules_version,
            engine_rules_version = excluded.engine_rules_version,
            analyzed_at = excluded.analyzed_at
        """,
        (
            game_id,
            pending.executable_relpath,
            pending.file_size,
            pending.modified_time_ns,
            pending.ranker_rules_version,
            pending.engine_rules_version,
            analyzed_at,
        ),
    )


def delete_analysis_cache(connection: sqlite3.Connection, game_id: str) -> None:
    """Delete one cache entry without committing the caller's transaction."""

    connection.execute("DELETE FROM game_analysis_cache WHERE game_id = ?", (game_id,))
