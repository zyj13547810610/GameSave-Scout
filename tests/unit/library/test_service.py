import pytest

from gameshelf.library.service import InvalidRootConfiguration, LibraryService


def test_add_root_deduplicates_by_windows_key(
    library_service: LibraryService,
) -> None:
    first = library_service.add_root(r"D:\Games", "children", 1, [])
    second = library_service.add_root(r"d:/games/", "children", 1, [])

    assert first.id == second.id
    assert len(library_service.list_roots()) == 1


def test_remap_root_preserves_id_and_relative_game(
    library_service: LibraryService,
) -> None:
    root = library_service.add_root(r"D:\Games", "recursive", 2, ["tools"])
    game = library_service.create_game_for_test(root.id, "group/game", "Game")

    remapped = library_service.remap_root(root.id, r"E:\PortableGames")

    assert remapped.id == root.id
    assert library_service.get_game(game.id).relative_dir == "group/game"  # type: ignore[union-attr]


def test_remove_root_preserves_games_as_missing_records(
    library_service: LibraryService,
) -> None:
    root = library_service.add_root(r"D:\Games", "children", 1, [])
    game = library_service.create_game_for_test(root.id, "GameA", "GameA")

    library_service.remove_root(root.id)

    preserved = library_service.get_game(game.id)
    assert preserved is not None
    assert preserved.scan_root_id is None
    assert preserved.status == "missing"
    assert preserved.missing_since is not None


def test_update_root_normalizes_children_depth_and_keeps_identity(
    library_service: LibraryService,
) -> None:
    root = library_service.add_root(r"D:\Games", "recursive", 4, [])

    updated = library_service.update_root(
        root.id,
        enabled=False,
        scan_mode="children",
        max_depth=8,
        exclusions=["Extras\\*"],
    )

    assert updated.id == root.id
    assert updated.enabled is False
    assert updated.scan_mode == "children"
    assert updated.max_depth == 1
    assert updated.exclusions == ("Extras/*",)


@pytest.mark.parametrize("depth", [0, 9])
def test_recursive_depth_must_be_between_one_and_eight(
    library_service: LibraryService, depth: int
) -> None:
    with pytest.raises(InvalidRootConfiguration):
        library_service.add_root(r"D:\Games", "recursive", depth, [])


@pytest.mark.parametrize(
    "exclusion", [r"D:\Other", r"\\server\share", "../outside", "group/../outside"]
)
def test_exclusions_cannot_be_absolute_or_escape_parent(
    library_service: LibraryService, exclusion: str
) -> None:
    with pytest.raises(InvalidRootConfiguration):
        library_service.add_root(r"D:\Games", "children", 1, [exclusion])
