"""Short-lived, read-only queries for scan roots and games."""

from __future__ import annotations

import json
import sqlite3
from types import MappingProxyType
from typing import Any, cast

from gameshelf.db.connection import ConnectionFactory
from gameshelf.engines.models import EngineEvidence
from gameshelf.library.models import (
    ExecutableArchitecture,
    Game,
    GameStatus,
    ScanMode,
    ScanRoot,
)


class LibraryRepository:
    def __init__(self, factory: ConnectionFactory) -> None:
        self._factory = factory

    @property
    def factory(self) -> ConnectionFactory:
        return self._factory

    def list_roots(self) -> tuple[ScanRoot, ...]:
        with self._factory.connect(readonly=True) as connection:
            rows = connection.execute(
                "SELECT * FROM scan_roots ORDER BY created_at, id"
            ).fetchall()
        return tuple(scan_root_from_row(row) for row in rows)

    def get_root(self, root_id: str) -> ScanRoot | None:
        with self._factory.connect(readonly=True) as connection:
            row = connection.execute(
                "SELECT * FROM scan_roots WHERE id = ?", (root_id,)
            ).fetchone()
        return None if row is None else scan_root_from_row(row)

    def list_games(self) -> tuple[Game, ...]:
        with self._factory.connect(readonly=True) as connection:
            rows = connection.execute(
                "SELECT * FROM games ORDER BY title COLLATE NOCASE, id"
            ).fetchall()
        return tuple(game_from_row(row) for row in rows)

    def get_game(self, game_id: str) -> Game | None:
        with self._factory.connect(readonly=True) as connection:
            row = connection.execute(
                "SELECT * FROM games WHERE id = ?", (game_id,)
            ).fetchone()
        return None if row is None else game_from_row(row)

    def get_game_by_install_path_key(self, path_key: str) -> Game | None:
        with self._factory.connect(readonly=True) as connection:
            row = connection.execute(
                "SELECT * FROM games WHERE install_path_key = ?", (path_key,)
            ).fetchone()
        return None if row is None else game_from_row(row)


def scan_root_from_row(row: sqlite3.Row) -> ScanRoot:
    return ScanRoot(
        id=str(row["id"]),
        display_path=str(row["display_path"]),
        path_key=str(row["path_key"]),
        enabled=bool(row["enabled"]),
        scan_mode=cast(ScanMode, row["scan_mode"]),
        max_depth=int(row["max_depth"]),
        exclusions=tuple(str(item) for item in _json_list(row["exclusions_json"])),
        last_scanned_at=row["last_scanned_at"],
        last_scan_status=str(row["last_scan_status"]),
        last_error=row["last_error"],
        created_at=str(row["created_at"]),
    )


def game_from_row(row: sqlite3.Row) -> Game:
    environment = _json_object(row["environment_json"])
    return Game(
        id=str(row["id"]),
        scan_root_id=row["scan_root_id"],
        relative_dir=row["relative_dir"],
        install_path_key=row["install_path_key"],
        title=str(row["title"]),
        detected_title=row["detected_title"],
        status=cast(GameStatus, row["status"]),
        detected_engine_id=row["detected_engine_id"],
        detected_engine_variant=row["detected_engine_variant"],
        engine_id=row["engine_id"],
        engine_variant=row["engine_variant"],
        engine_is_manual=bool(row["engine_is_manual"]),
        engine_confidence=(
            float(row["engine_confidence"])
            if row["engine_confidence"] is not None
            else None
        ),
        engine_evidence=_engine_evidence(row["engine_evidence_json"]),
        engine_rules_version=row["engine_rules_version"],
        main_exe_relpath=row["main_exe_relpath"],
        main_exe_is_manual=bool(row["main_exe_is_manual"]),
        working_dir_relpath=row["working_dir_relpath"],
        launch_args=tuple(str(item) for item in _json_list(row["launch_args_json"])),
        environment=MappingProxyType(
            {str(key): str(value) for key, value in environment.items()}
        ),
        exe_arch=cast(ExecutableArchitecture, row["exe_arch"]),
        cover_original_relpath=row["cover_original_relpath"],
        cover_thumb_relpath=row["cover_thumb_relpath"],
        cover_revision=int(row["cover_revision"]),
        last_launched_at=row["last_launched_at"],
        missing_since=row["missing_since"],
        version=row["version"],
        detected_version=row["detected_version"],
    )


def _json_list(value: str) -> list[Any]:
    loaded = json.loads(value)
    if not isinstance(loaded, list):
        raise ValueError("Expected a JSON array in the library database.")
    return loaded


def _json_object(value: str) -> dict[str, Any]:
    loaded = json.loads(value)
    if not isinstance(loaded, dict):
        raise ValueError("Expected a JSON object in the library database.")
    return loaded


def _engine_evidence(value: str) -> tuple[EngineEvidence, ...]:
    entries = _json_list(value)
    evidence: list[EngineEvidence] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Expected engine evidence objects in the library database.")
        evidence.append(
            EngineEvidence(
                code=str(entry["code"]),
                detail=str(entry["detail"]),
                weight=float(entry["weight"]),
                path=(str(entry["path"]) if entry.get("path") is not None else None),
            )
        )
    return tuple(evidence)
