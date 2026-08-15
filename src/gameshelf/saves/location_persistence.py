"""Shared connection-local persistence for confirmed save locations."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from uuid import uuid4

from gameshelf.saves.models import (
    SaveLocation,
    SaveLocationKind,
    SaveLocationSource,
)
from gameshelf.saves.repository import save_location_from_row


@dataclass(frozen=True, slots=True)
class PreparedSaveLocation:
    game_id: str
    kind: SaveLocationKind
    path_template: str
    display_path: str
    path_key: str
    source: SaveLocationSource
    confidence: float
    evidence: tuple[str, ...]


def upsert_confirmed_location(
    connection: sqlite3.Connection,
    prepared: PreparedSaveLocation,
) -> SaveLocation:
    """Return an existing equivalent location or insert one in the caller transaction."""
    existing = connection.execute(
        """
        SELECT * FROM save_locations
        WHERE game_id = ? AND kind = ? AND path_key = ?
        """,
        (prepared.game_id, prepared.kind, prepared.path_key),
    ).fetchone()
    if existing is not None:
        return save_location_from_row(existing)

    location_id = str(uuid4())
    connection.execute(
        """
        INSERT INTO save_locations(
            id, game_id, kind, path_template, display_path, path_key,
            source, confidence, evidence_json, confirmed, enabled
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, json(?), 1, 1)
        """,
        (
            location_id,
            prepared.game_id,
            prepared.kind,
            prepared.path_template,
            prepared.display_path,
            prepared.path_key,
            prepared.source,
            prepared.confidence,
            json.dumps(prepared.evidence, ensure_ascii=False, separators=(",", ":")),
        ),
    )
    row = connection.execute(
        "SELECT * FROM save_locations WHERE id = ?", (location_id,)
    ).fetchone()
    assert row is not None
    return save_location_from_row(row)
