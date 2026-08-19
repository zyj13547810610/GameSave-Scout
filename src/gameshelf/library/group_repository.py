"""Read-only queries for custom game groups."""

import sqlite3

from gameshelf.db.connection import ConnectionFactory
from gameshelf.library.group_models import GameGroup


class GroupRepository:
    def __init__(self, factory: ConnectionFactory) -> None:
        self._factory = factory

    def list_groups(self) -> tuple[GameGroup, ...]:
        with self._factory.connect(readonly=True) as connection:
            rows = connection.execute(
                """
                SELECT
                    group_row.id,
                    group_row.name,
                    group_row.created_at,
                    group_row.updated_at,
                    COUNT(membership.game_id) AS game_count
                FROM game_groups AS group_row
                LEFT JOIN game_group_memberships AS membership
                    ON membership.group_id = group_row.id
                GROUP BY group_row.id
                ORDER BY group_row.created_at, group_row.id
                """
            ).fetchall()
        return tuple(game_group_from_row(row) for row in rows)


def game_group_from_row(row: sqlite3.Row) -> GameGroup:
    return GameGroup(
        id=str(row["id"]),
        name=str(row["name"]),
        game_count=int(row["game_count"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )
