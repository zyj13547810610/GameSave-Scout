import sqlite3
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from gameshelf.db.connection import ConnectionFactory
from gameshelf.db.migrator import Migrator
from gameshelf.saves.repository import SaveLocationRepository


def test_repository_round_trips_immutable_save_location(tmp_path: Path) -> None:
    factory = ConnectionFactory(tmp_path / "data" / "library.db")
    Migrator(factory, tmp_path / "backups").migrate()
    with factory.connect() as connection:
        _insert_game(connection)
        connection.execute(
            """
            INSERT INTO save_locations(
                id, game_id, kind, path_template, display_path, path_key,
                source, confidence, evidence_json, confirmed, enabled
            ) VALUES (
                'save-1', 'game-1', 'directory', '<home>\\Saves',
                'C:\\Users\\Alice\\Saves', 'c:\\users\\alice\\saves',
                'manual', 1.0, json('["用户手动添加"]'), 1, 1
            )
            """
        )

    repository = SaveLocationRepository(factory)
    loaded = repository.list_for_game("game-1")[0]

    assert loaded.path_template == r"<home>\Saves"
    assert loaded.evidence == ("用户手动添加",)
    assert loaded.exists is None
    assert repository.list_all() == (loaded,)
    with pytest.raises(FrozenInstanceError):
        loaded.enabled = False  # type: ignore[misc]


def test_repository_returns_none_for_unknown_location(tmp_path: Path) -> None:
    factory = ConnectionFactory(tmp_path / "data" / "library.db")
    Migrator(factory, tmp_path / "backups").migrate()

    assert SaveLocationRepository(factory).get("missing") is None


def _insert_game(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT INTO games(id, title, status, added_at, updated_at)
        VALUES ('game-1', 'Alice', 'save_only', '2026-08-12T00:00:00+00:00',
                '2026-08-12T00:00:00+00:00')
        """
    )
