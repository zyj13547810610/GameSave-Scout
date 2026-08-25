from dataclasses import FrozenInstanceError

import pytest

from gamesave_scout.db.connection import ConnectionFactory
from gamesave_scout.library.service import LibraryService


def test_repository_round_trips_immutable_root_and_game(
    library_service: LibraryService,
) -> None:
    root = library_service.add_root(
        r"D:\Games", "recursive", 3, ["Tools", "**/Cache"]
    )
    game = library_service.create_game_for_test(root.id, "group/game", "Alice")

    loaded_root = library_service.list_roots()[0]
    loaded_game = library_service.list_games()[0]

    assert loaded_root == root
    assert loaded_root.exclusions == ("Tools", "**/Cache")
    assert loaded_game == game
    assert loaded_game.launch_args == ()
    assert dict(loaded_game.environment) == {}
    with pytest.raises(FrozenInstanceError):
        loaded_root.enabled = False  # type: ignore[misc]


def test_get_game_returns_none_for_unknown_id(library_service: LibraryService) -> None:
    assert library_service.get_game("not-there") is None


def test_get_game_by_install_path_key_returns_matching_game(
    library_service: LibraryService,
) -> None:
    root = library_service.add_root(r"D:\Games", "children", 1, [])
    game = library_service.create_game_for_test(root.id, "Alice", "Alice")
    assert game.install_path_key is not None
    repository = library_service._repository  # noqa: SLF001

    assert repository.get_game_by_install_path_key(game.install_path_key) == game
    assert repository.get_game_by_install_path_key(r"d:\games\missing") is None


def test_repository_hydrates_group_ids_with_one_membership_query(
    library_service: LibraryService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = library_service.add_root(r"D:\Games", "children", 1, [])
    first = library_service.create_game_for_test(root.id, "Alice", "Alice")
    second = library_service.create_game_for_test(root.id, "Bob", "Bob")
    factory = library_service._repository.factory  # noqa: SLF001
    with factory.connect() as connection:
        connection.executemany(
            """
            INSERT INTO game_groups(id, name, normalized_name, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                ("group-later", "Later", "later", "2026-08-19T02:00:00Z", "now"),
                ("group-first", "First", "first", "2026-08-19T01:00:00Z", "now"),
            ),
        )
        connection.executemany(
            """
            INSERT INTO game_group_memberships(game_id, group_id, created_at)
            VALUES (?, ?, 'now')
            """,
            (
                (first.id, "group-later"),
                (first.id, "group-first"),
                (second.id, "group-first"),
            ),
        )
        connection.commit()

    statements: list[str] = []
    original_connect = ConnectionFactory.connect

    def traced_connect(
        self: ConnectionFactory, *, readonly: bool = False
    ):  # type: ignore[no-untyped-def]
        connection = original_connect(self, readonly=readonly)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(ConnectionFactory, "connect", traced_connect)

    loaded = library_service.list_games()
    loaded_first = library_service.get_game(first.id)

    assert loaded[0].group_ids == ("group-first", "group-later")
    assert loaded[1].group_ids == ("group-first",)
    assert loaded_first is not None
    assert loaded_first.group_ids == ("group-first", "group-later")
    list_queries = [
        statement
        for statement in statements
        if "game_group_memberships" in statement
        and "WHERE membership.game_id IN" in statement
    ]
    assert len(list_queries) == 2
