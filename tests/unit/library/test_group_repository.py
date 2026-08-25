import sqlite3
from pathlib import Path

from gamesave_scout.db.connection import ConnectionFactory
from gamesave_scout.db.migrator import Migrator
from gamesave_scout.library.group_repository import GroupRepository


def test_list_groups_orders_stably_and_counts_memberships(tmp_path: Path) -> None:
    factory = ConnectionFactory(tmp_path / "library.db")
    Migrator(factory, tmp_path / "backups").migrate()
    with factory.connect() as connection:
        _insert_game(connection, "game-1")
        _insert_game(connection, "game-2")
        connection.executemany(
            """
            INSERT INTO game_groups(id, name, normalized_name, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'now')
            """,
            (
                ("group-b", "B", "b", "2026-08-19T01:00:00Z"),
                ("group-a", "A", "a", "2026-08-19T01:00:00Z"),
                ("group-c", "C", "c", "2026-08-19T02:00:00Z"),
            ),
        )
        connection.executemany(
            """
            INSERT INTO game_group_memberships(game_id, group_id, created_at)
            VALUES (?, ?, 'now')
            """,
            (
                ("game-1", "group-a"),
                ("game-2", "group-a"),
                ("game-2", "group-b"),
            ),
        )
        connection.commit()

    groups = GroupRepository(factory).list_groups()

    assert [(group.id, group.name, group.game_count) for group in groups] == [
        ("group-a", "A", 2),
        ("group-b", "B", 1),
        ("group-c", "C", 0),
    ]


def _insert_game(connection: sqlite3.Connection, game_id: str) -> None:
    connection.execute(
        """
        INSERT INTO games(id, title, status, added_at, updated_at)
        VALUES (?, ?, 'save_only', 'now', 'now')
        """,
        (game_id, game_id),
    )
