from dataclasses import FrozenInstanceError

import pytest

from gameshelf.library.service import LibraryService


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
