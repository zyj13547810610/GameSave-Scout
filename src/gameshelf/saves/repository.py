"""Short-lived, read-only queries for saved locations."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, cast

from gameshelf.db.connection import ConnectionFactory
from gameshelf.saves.models import (
    SaveLocation,
    SaveLocationKind,
    SaveLocationSource,
)


class SaveLocationRepository:
    def __init__(self, factory: ConnectionFactory) -> None:
        self._factory = factory

    def list_for_game(self, game_id: str) -> tuple[SaveLocation, ...]:
        with self._factory.connect(readonly=True) as connection:
            rows = connection.execute(
                "SELECT * FROM save_locations WHERE game_id = ? ORDER BY rowid",
                (game_id,),
            ).fetchall()
        return tuple(save_location_from_row(row) for row in rows)

    def list_all(self) -> tuple[SaveLocation, ...]:
        with self._factory.connect(readonly=True) as connection:
            rows = connection.execute(
                "SELECT * FROM save_locations ORDER BY rowid"
            ).fetchall()
        return tuple(save_location_from_row(row) for row in rows)

    def get(self, location_id: str) -> SaveLocation | None:
        with self._factory.connect(readonly=True) as connection:
            row = connection.execute(
                "SELECT * FROM save_locations WHERE id = ?", (location_id,)
            ).fetchone()
        return None if row is None else save_location_from_row(row)


def save_location_from_row(row: sqlite3.Row) -> SaveLocation:
    return SaveLocation(
        id=str(row["id"]),
        game_id=str(row["game_id"]),
        kind=cast(SaveLocationKind, row["kind"]),
        path_template=str(row["path_template"]),
        display_path=str(row["display_path"]),
        path_key=str(row["path_key"]),
        source=cast(SaveLocationSource, row["source"]),
        confidence=float(row["confidence"]),
        evidence=_evidence(row["evidence_json"]),
        confirmed=bool(row["confirmed"]),
        enabled=bool(row["enabled"]),
        last_verified_at=row["last_verified_at"],
    )


def _evidence(value: str) -> tuple[str, ...]:
    loaded: Any = json.loads(value)
    if not isinstance(loaded, list) or not all(isinstance(item, str) for item in loaded):
        raise ValueError("Expected a JSON string array for save-location evidence.")
    return tuple(loaded)
