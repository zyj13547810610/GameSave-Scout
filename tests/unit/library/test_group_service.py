from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from gamesave_scout.db.connection import ConnectionFactory
from gamesave_scout.db.migrator import Migrator
from gamesave_scout.db.writer import DbWriter
from gamesave_scout.library.group_repository import GroupRepository
from gamesave_scout.library.group_service import (
    DuplicateGroupName,
    GroupLimitReached,
    GroupNotFoundError,
    GroupService,
    InvalidGroupMembership,
    InvalidGroupName,
)
from gamesave_scout.library.service import GameNotFoundError


@dataclass(frozen=True)
class GroupHarness:
    factory: ConnectionFactory
    service: GroupService

    def insert_game(self, game_id: str, status: str = "save_only") -> None:
        with self.factory.connect() as connection:
            if status == "installed":
                connection.execute(
                    """
                    INSERT OR IGNORE INTO scan_roots(
                        id, display_path, path_key, scan_mode, created_at
                    ) VALUES ('root-1', 'D:\\Games', 'd:\\games', 'children', 'now')
                    """
                )
            connection.execute(
                """
                INSERT INTO games(
                    id, scan_root_id, relative_dir, title, status, cover_original_relpath,
                    cover_thumb_relpath, added_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'covers/original/kept.jpg',
                    'covers/thumbs/kept.webp', 'now', 'now')
                """,
                (
                    game_id,
                    "root-1" if status == "installed" else None,
                    game_id if status == "installed" else None,
                    game_id,
                    status,
                ),
            )
            connection.commit()

    def memberships(self, game_id: str) -> tuple[str, ...]:
        with self.factory.connect(readonly=True) as connection:
            rows = connection.execute(
                """
                SELECT group_id FROM game_group_memberships
                WHERE game_id = ? ORDER BY group_id
                """,
                (game_id,),
            ).fetchall()
        return tuple(str(row["group_id"]) for row in rows)


@pytest.fixture
def group_harness(tmp_path: Path) -> Iterator[GroupHarness]:
    factory = ConnectionFactory(tmp_path / "library.db")
    Migrator(factory, tmp_path / "backups").migrate()
    writer = DbWriter(factory)
    writer.start()
    repository = GroupRepository(factory)
    harness = GroupHarness(
        factory,
        GroupService(
            connection_factory=factory,
            writer=writer,
            repository=repository,
        ),
    )
    try:
        yield harness
    finally:
        writer.close()


def test_create_group_trims_name_and_rejects_normalized_duplicate(
    group_harness: GroupHarness,
) -> None:
    created = group_harness.service.create_group("  RPG  ")

    assert created.name == "RPG"
    assert created.game_count == 0
    with pytest.raises(DuplicateGroupName):
        group_harness.service.create_group("ｒｐｇ")


@pytest.mark.parametrize("name", ["", "   ", "名称\n换行", "x" * 41])
def test_create_group_rejects_invalid_names(
    group_harness: GroupHarness,
    name: str,
) -> None:
    with pytest.raises(InvalidGroupName):
        group_harness.service.create_group(name)


def test_create_group_enforces_two_hundred_group_limit(
    group_harness: GroupHarness,
) -> None:
    with group_harness.factory.connect() as connection:
        connection.executemany(
            """
            INSERT INTO game_groups(id, name, normalized_name, created_at, updated_at)
            VALUES (?, ?, ?, 'now', 'now')
            """,
            ((f"group-{index}", f"Group {index}", f"group {index}") for index in range(200)),
        )
        connection.commit()

    with pytest.raises(GroupLimitReached):
        group_harness.service.create_group("One more")


def test_rename_and_delete_group_preserve_game_and_cover_fields(
    group_harness: GroupHarness,
) -> None:
    group_harness.insert_game("game-1")
    created = group_harness.service.create_group("RPG")
    group_harness.service.set_game_groups("game-1", (created.id,))

    renamed = group_harness.service.rename_group(created.id, "角色扮演")
    group_harness.service.delete_group(created.id)

    assert renamed.name == "角色扮演"
    with group_harness.factory.connect(readonly=True) as connection:
        game = connection.execute(
            """
            SELECT cover_original_relpath, cover_thumb_relpath
            FROM games WHERE id = 'game-1'
            """
        ).fetchone()
        membership_count = connection.execute(
            "SELECT COUNT(*) FROM game_group_memberships"
        ).fetchone()[0]
    assert tuple(game) == (
        "covers/original/kept.jpg",
        "covers/thumbs/kept.webp",
    )
    assert membership_count == 0


def test_rename_rejects_duplicate_and_unknown_groups(
    group_harness: GroupHarness,
) -> None:
    first = group_harness.service.create_group("RPG")
    second = group_harness.service.create_group("SLG")

    with pytest.raises(DuplicateGroupName):
        group_harness.service.rename_group(second.id, "rpg")
    with pytest.raises(GroupNotFoundError):
        group_harness.service.rename_group("missing", "Other")
    with pytest.raises(GroupNotFoundError):
        group_harness.service.delete_group("missing")
    assert group_harness.service.list_groups() == (first, second)


@pytest.mark.parametrize("status", ["installed", "missing", "save_only"])
def test_set_game_groups_replaces_deduplicated_memberships_for_every_status(
    group_harness: GroupHarness,
    status: str,
) -> None:
    group_harness.insert_game("game-1", status)
    first = group_harness.service.create_group("RPG")
    second = group_harness.service.create_group("SLG")

    updated = group_harness.service.set_game_groups(
        "game-1", (second.id, first.id, second.id)
    )

    assert updated.group_ids == (first.id, second.id)
    assert group_harness.memberships("game-1") == tuple(sorted((first.id, second.id)))
    assert [group.game_count for group in group_harness.service.list_groups()] == [1, 1]


def test_set_game_groups_rolls_back_when_game_or_group_is_missing(
    group_harness: GroupHarness,
) -> None:
    group_harness.insert_game("game-1")
    kept = group_harness.service.create_group("Kept")
    replacement = group_harness.service.create_group("Replacement")
    group_harness.service.set_game_groups("game-1", (kept.id,))

    with pytest.raises(GroupNotFoundError):
        group_harness.service.set_game_groups(
            "game-1", (replacement.id, "missing-group")
        )
    with pytest.raises(GameNotFoundError):
        group_harness.service.set_game_groups("missing-game", (replacement.id,))

    assert group_harness.memberships("game-1") == (kept.id,)


def test_batch_membership_updates_count_added_removed_and_unchanged(
    group_harness: GroupHarness,
) -> None:
    for game_id in ("game-1", "game-2", "game-3"):
        group_harness.insert_game(game_id)
    group = group_harness.service.create_group("RPG")
    group_harness.service.set_game_groups("game-1", (group.id,))

    added = group_harness.service.update_memberships(
        group.id,
        ("game-1", "game-2", "game-2"),
        "add",
    )
    removed = group_harness.service.update_memberships(
        group.id,
        ("game-1", "game-3", "game-3"),
        "remove",
    )

    assert (added.added_count, added.removed_count, added.unchanged_count) == (1, 0, 1)
    assert (removed.added_count, removed.removed_count, removed.unchanged_count) == (0, 1, 1)
    assert group_harness.memberships("game-1") == ()
    assert group_harness.memberships("game-2") == (group.id,)


def test_batch_membership_rejects_raw_input_over_five_hundred(
    group_harness: GroupHarness,
) -> None:
    group = group_harness.service.create_group("RPG")

    with pytest.raises(InvalidGroupMembership, match="500"):
        group_harness.service.update_memberships(
            group.id,
            tuple("game-1" for _ in range(501)),
            "add",
        )


def test_batch_membership_rolls_back_when_any_game_is_missing(
    group_harness: GroupHarness,
) -> None:
    group_harness.insert_game("game-1")
    group = group_harness.service.create_group("RPG")

    with pytest.raises(GameNotFoundError):
        group_harness.service.update_memberships(
            group.id,
            ("game-1", "missing-game"),
            "add",
        )

    assert group_harness.memberships("game-1") == ()


def test_batch_membership_rejects_unknown_mode(
    group_harness: GroupHarness,
) -> None:
    group = group_harness.service.create_group("RPG")

    with pytest.raises(InvalidGroupMembership):
        group_harness.service.update_memberships(
            group.id,
            (),
            "replace",  # type: ignore[arg-type]
        )
