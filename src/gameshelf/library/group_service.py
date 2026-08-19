"""Transactional commands for custom game groups."""

from __future__ import annotations

import sqlite3
import unicodedata
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from uuid import uuid4

from gameshelf.db.connection import ConnectionFactory
from gameshelf.db.writer import DbWriter
from gameshelf.library.group_models import (
    GameGroup,
    GroupMembershipMode,
    GroupMembershipUpdateResult,
)
from gameshelf.library.group_repository import GroupRepository, game_group_from_row
from gameshelf.library.models import Game
from gameshelf.library.repository import game_from_row_with_groups
from gameshelf.library.service import GameNotFoundError

MAX_GROUPS = 200
MAX_NAME_LENGTH = 40
MAX_BATCH_GAMES = 500


class InvalidGroupName(ValueError):
    """Raised when a group display name is empty, too long, or unsafe."""


class DuplicateGroupName(ValueError):
    """Raised when a normalized group name already exists."""


class GroupLimitReached(ValueError):
    """Raised when the library already contains the maximum group count."""


class GroupNotFoundError(LookupError):
    """Raised when a group command names an unknown group."""


class InvalidGroupMembership(ValueError):
    """Raised when a membership operation exceeds its safe boundary."""


class GroupService:
    def __init__(
        self,
        *,
        connection_factory: ConnectionFactory,
        writer: DbWriter,
        repository: GroupRepository,
    ) -> None:
        self._factory = connection_factory
        self._writer = writer
        self._repository = repository

    def list_groups(self) -> tuple[GameGroup, ...]:
        return self._repository.list_groups()

    def create_group(self, name: str) -> GameGroup:
        display_name, normalized_name = _validated_group_name(name)

        def operation(connection: sqlite3.Connection) -> GameGroup:
            count = int(
                connection.execute("SELECT COUNT(*) FROM game_groups").fetchone()[0]
            )
            if count >= MAX_GROUPS:
                raise GroupLimitReached(f"分组数量不能超过 {MAX_GROUPS} 个。")
            if _normalized_name_exists(connection, normalized_name):
                raise DuplicateGroupName("已经存在同名分组。")
            group_id = str(uuid4())
            now = _utc_now()
            connection.execute(
                """
                INSERT INTO game_groups(
                    id, name, normalized_name, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (group_id, display_name, normalized_name, now, now),
            )
            return GameGroup(group_id, display_name, 0, now, now)

        return self._submit_group_write(operation)

    def rename_group(self, group_id: str, name: str) -> GameGroup:
        display_name, normalized_name = _validated_group_name(name)

        def operation(connection: sqlite3.Connection) -> GameGroup:
            current = connection.execute(
                "SELECT * FROM game_groups WHERE id = ?", (group_id,)
            ).fetchone()
            if current is None:
                raise GroupNotFoundError(group_id)
            if _normalized_name_exists(
                connection,
                normalized_name,
                excluding_group_id=group_id,
            ):
                raise DuplicateGroupName("已经存在同名分组。")
            now = _utc_now()
            connection.execute(
                """
                UPDATE game_groups
                SET name = ?, normalized_name = ?, updated_at = ?
                WHERE id = ?
                """,
                (display_name, normalized_name, now, group_id),
            )
            return _read_group(connection, group_id)

        return self._submit_group_write(operation)

    def delete_group(self, group_id: str) -> None:
        def operation(connection: sqlite3.Connection) -> None:
            cursor = connection.execute(
                "DELETE FROM game_groups WHERE id = ?", (group_id,)
            )
            if cursor.rowcount == 0:
                raise GroupNotFoundError(group_id)

        self._writer.submit(operation).result()

    def set_game_groups(self, game_id: str, group_ids: Sequence[str]) -> Game:
        unique_group_ids = tuple(dict.fromkeys(group_ids))

        def operation(connection: sqlite3.Connection) -> Game:
            game_row = connection.execute(
                "SELECT * FROM games WHERE id = ?", (game_id,)
            ).fetchone()
            if game_row is None:
                raise GameNotFoundError(game_id)
            _require_group_ids(connection, unique_group_ids)
            connection.execute(
                "DELETE FROM game_group_memberships WHERE game_id = ?", (game_id,)
            )
            now = _utc_now()
            connection.executemany(
                """
                INSERT INTO game_group_memberships(game_id, group_id, created_at)
                VALUES (?, ?, ?)
                """,
                ((game_id, group_id, now) for group_id in unique_group_ids),
            )
            return game_from_row_with_groups(connection, game_row)

        return self._writer.submit(operation).result()

    def update_memberships(
        self,
        group_id: str,
        game_ids: Sequence[str],
        mode: GroupMembershipMode,
    ) -> GroupMembershipUpdateResult:
        if mode not in {"add", "remove"}:
            raise InvalidGroupMembership("不支持的分组关系操作。")
        if len(game_ids) > MAX_BATCH_GAMES:
            raise InvalidGroupMembership(
                f"一次最多处理 {MAX_BATCH_GAMES} 个游戏。"
            )
        unique_game_ids = tuple(dict.fromkeys(game_ids))

        def operation(connection: sqlite3.Connection) -> GroupMembershipUpdateResult:
            _require_group_ids(connection, (group_id,))
            _require_game_ids(connection, unique_game_ids)
            existing = _existing_memberships(
                connection,
                group_id,
                unique_game_ids,
            )
            now = _utc_now()
            if mode == "add":
                changed_ids = tuple(
                    game_id for game_id in unique_game_ids if game_id not in existing
                )
                connection.executemany(
                    """
                    INSERT INTO game_group_memberships(game_id, group_id, created_at)
                    VALUES (?, ?, ?)
                    """,
                    ((game_id, group_id, now) for game_id in changed_ids),
                )
                return GroupMembershipUpdateResult(
                    added_count=len(changed_ids),
                    removed_count=0,
                    unchanged_count=len(existing),
                )

            changed_ids = tuple(
                game_id for game_id in unique_game_ids if game_id in existing
            )
            connection.executemany(
                """
                DELETE FROM game_group_memberships
                WHERE game_id = ? AND group_id = ?
                """,
                ((game_id, group_id) for game_id in changed_ids),
            )
            return GroupMembershipUpdateResult(
                added_count=0,
                removed_count=len(changed_ids),
                unchanged_count=len(unique_game_ids) - len(changed_ids),
            )

        return self._writer.submit(operation).result()

    def _submit_group_write(
        self,
        operation: Callable[[sqlite3.Connection], GameGroup],
    ) -> GameGroup:
        try:
            return self._writer.submit(operation).result()
        except sqlite3.IntegrityError as error:
            if "game_groups.normalized_name" in str(error):
                raise DuplicateGroupName("已经存在同名分组。") from error
            raise


def _validated_group_name(value: str) -> tuple[str, str]:
    display_name = value.strip()
    if not 1 <= len(display_name) <= MAX_NAME_LENGTH:
        raise InvalidGroupName(f"分组名称长度必须为 1～{MAX_NAME_LENGTH} 个字符。")
    if any(
        unicodedata.category(character).startswith("C")
        for character in display_name
    ):
        raise InvalidGroupName("分组名称不能包含控制字符。")
    return display_name, unicodedata.normalize("NFKC", display_name).casefold()


def _normalized_name_exists(
    connection: sqlite3.Connection,
    normalized_name: str,
    *,
    excluding_group_id: str | None = None,
) -> bool:
    if excluding_group_id is None:
        row = connection.execute(
            "SELECT 1 FROM game_groups WHERE normalized_name = ? LIMIT 1",
            (normalized_name,),
        ).fetchone()
    else:
        row = connection.execute(
            """
            SELECT 1 FROM game_groups
            WHERE normalized_name = ? AND id != ? LIMIT 1
            """,
            (normalized_name, excluding_group_id),
        ).fetchone()
    return row is not None


def _read_group(connection: sqlite3.Connection, group_id: str) -> GameGroup:
    row = connection.execute(
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
        WHERE group_row.id = ?
        GROUP BY group_row.id
        """,
        (group_id,),
    ).fetchone()
    if row is None:
        raise GroupNotFoundError(group_id)
    return game_group_from_row(row)


def _require_group_ids(
    connection: sqlite3.Connection,
    group_ids: Sequence[str],
) -> None:
    if not group_ids:
        return
    placeholders = ", ".join("?" for _ in group_ids)
    rows = connection.execute(
        f"SELECT id FROM game_groups WHERE id IN ({placeholders})",  # noqa: S608
        tuple(group_ids),
    ).fetchall()
    found = {str(row["id"]) for row in rows}
    missing = next((group_id for group_id in group_ids if group_id not in found), None)
    if missing is not None:
        raise GroupNotFoundError(missing)


def _require_game_ids(
    connection: sqlite3.Connection,
    game_ids: Sequence[str],
) -> None:
    if not game_ids:
        return
    placeholders = ", ".join("?" for _ in game_ids)
    rows = connection.execute(
        f"SELECT id FROM games WHERE id IN ({placeholders})",  # noqa: S608
        tuple(game_ids),
    ).fetchall()
    found = {str(row["id"]) for row in rows}
    missing = next((game_id for game_id in game_ids if game_id not in found), None)
    if missing is not None:
        raise GameNotFoundError(missing)


def _existing_memberships(
    connection: sqlite3.Connection,
    group_id: str,
    game_ids: Sequence[str],
) -> set[str]:
    if not game_ids:
        return set()
    placeholders = ", ".join("?" for _ in game_ids)
    rows = connection.execute(
        f"""
        SELECT game_id FROM game_group_memberships
        WHERE group_id = ? AND game_id IN ({placeholders})
        """,  # noqa: S608
        (group_id, *game_ids),
    ).fetchall()
    return {str(row["game_id"]) for row in rows}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
