import sqlite3
from pathlib import Path

import pytest

from gameshelf.library.models import GameRemovalRequest
from gameshelf.library.service import (
    GameNotFoundError,
    InvalidGameConfiguration,
    InvalidGameRemoval,
    InvalidRootConfiguration,
    LibraryService,
)
from gameshelf.scanning.pe_metadata import PeMetadata


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


def test_remove_installed_game_adds_exact_root_exclusion_and_deletes_record(
    library_service: LibraryService,
) -> None:
    root = library_service.add_root(r"D:\Games", "recursive", 3, ["Tools"])
    game = library_service.create_game_for_test(root.id, "Group/GameA", "GameA")

    updated_root = library_service.remove_game_and_exclude(game.id)

    assert updated_root.exclusions == ("Tools", "Group/GameA")
    assert library_service.get_game(game.id) is None


def test_remove_installed_game_does_not_duplicate_existing_exclusion(
    library_service: LibraryService,
) -> None:
    root = library_service.add_root(r"D:\Games", "children", 1, ["GameA"])
    game = library_service.create_game_for_test(root.id, "GameA", "GameA")

    updated_root = library_service.remove_game_and_exclude(game.id)

    assert updated_root.exclusions == ("GameA",)


def test_delete_missing_game_removes_only_missing_record(
    library_service: LibraryService,
) -> None:
    root = library_service.add_root(r"D:\Games", "children", 1, [])
    missing = library_service.create_game_for_test(root.id, "Missing", "Missing")
    installed = library_service.create_game_for_test(root.id, "Installed", "Installed")
    library_service.remove_root(root.id)

    library_service.delete_missing_game(missing.id)

    assert library_service.get_game(missing.id) is None
    assert library_service.get_game(installed.id) is not None


def test_delete_missing_game_rejects_installed_record(
    library_service: LibraryService,
) -> None:
    root = library_service.add_root(r"D:\Games", "children", 1, [])
    game = library_service.create_game_for_test(root.id, "GameA", "GameA")

    with pytest.raises(ValueError, match="missing"):
        library_service.delete_missing_game(game.id)


def test_batch_remove_mixes_statuses_merges_roots_and_captures_managed_covers(
    library_service: LibraryService,
) -> None:
    first_root = library_service.add_root(r"D:\Games", "recursive", 3, ["Tools"])
    second_root = library_service.add_root(r"E:\Games", "children", 1, [])
    missing_root = library_service.add_root(r"F:\OldGames", "children", 1, [])
    first = library_service.create_game_for_test(first_root.id, "Group/GameA", "GameA")
    second = library_service.create_game_for_test(second_root.id, "GameB", "GameB")
    missing = library_service.create_game_for_test(missing_root.id, "GameC", "GameC")

    def seed_related_rows(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            UPDATE games
            SET cover_original_relpath = 'covers/original/a.png',
                cover_thumb_relpath = 'covers/thumbs/a.webp'
            WHERE id = ?
            """,
            (first.id,),
        )
        connection.execute(
            """
            UPDATE games
            SET cover_original_relpath = 'covers/original/c.png',
                cover_thumb_relpath = 'covers/thumbs/c.webp'
            WHERE id = ?
            """,
            (missing.id,),
        )
        connection.execute(
            """
            INSERT INTO save_locations (
                id, game_id, kind, path_template, display_path, path_key,
                source, confidence, confirmed, enabled
            ) VALUES ('save-c', ?, 'directory', 'C:/save', 'C:/save', 'c:/save',
                      'manual', 1, 1, 1)
            """,
            (missing.id,),
        )

    library_service._writer.submit(seed_related_rows).result()  # noqa: SLF001
    library_service.remove_root(missing_root.id)

    result = library_service.remove_games(
        (
            GameRemovalRequest(first.id, "installed"),
            GameRemovalRequest(missing.id, "missing"),
            GameRemovalRequest(second.id, "installed"),
            GameRemovalRequest(first.id, "installed"),
        )
    )

    assert result.installed_count == 2
    assert result.missing_count == 1
    assert set(result.updated_root_ids) == {first_root.id, second_root.id}
    assert set(result.managed_cover_relpaths) == {
        "covers/original/a.png",
        "covers/thumbs/a.webp",
        "covers/original/c.png",
        "covers/thumbs/c.webp",
    }
    assert library_service.get_game(first.id) is None
    assert library_service.get_game(second.id) is None
    assert library_service.get_game(missing.id) is None
    roots = {root.id: root for root in library_service.list_roots()}
    assert roots[first_root.id].exclusions == ("Tools", "Group/GameA")
    assert roots[second_root.id].exclusions == ("GameB",)
    with library_service._repository.factory.connect(readonly=True) as connection:  # noqa: SLF001
        assert connection.execute(
            "SELECT 1 FROM save_locations WHERE id = 'save-c'"
        ).fetchone() is None


def test_batch_remove_rolls_back_every_record_when_any_game_is_unknown(
    library_service: LibraryService,
) -> None:
    root = library_service.add_root(r"D:\Games", "children", 1, [])
    game = library_service.create_game_for_test(root.id, "GameA", "GameA")

    with pytest.raises(GameNotFoundError):
        library_service.remove_games(
            (
                GameRemovalRequest(game.id, "installed"),
                GameRemovalRequest("unknown", "missing"),
            )
        )

    assert library_service.get_game(game.id) is not None
    assert library_service.list_roots()[0].exclusions == ()


def test_batch_remove_rolls_back_when_expected_status_changed(
    library_service: LibraryService,
) -> None:
    root = library_service.add_root(r"D:\Games", "children", 1, [])
    game = library_service.create_game_for_test(root.id, "GameA", "GameA")

    with pytest.raises(InvalidGameRemoval, match="status"):
        library_service.remove_games((GameRemovalRequest(game.id, "missing"),))

    assert library_service.get_game(game.id) is not None


def test_batch_remove_rejects_unsafe_installed_relative_path_without_changes(
    library_service: LibraryService,
) -> None:
    root = library_service.add_root(r"D:\Games", "children", 1, [])
    game = library_service.create_game_for_test(root.id, "GameA", "GameA")

    def corrupt_relative_path(connection: sqlite3.Connection) -> None:
        connection.execute(
            "UPDATE games SET relative_dir = '../outside' WHERE id = ?",
            (game.id,),
        )

    library_service._writer.submit(corrupt_relative_path).result()  # noqa: SLF001

    with pytest.raises(InvalidGameRemoval, match="relative"):
        library_service.remove_games((GameRemovalRequest(game.id, "installed"),))

    assert library_service.get_game(game.id) is not None
    assert library_service.list_roots()[0].exclusions == ()


def test_batch_remove_rejects_more_than_five_hundred_submitted_items(
    library_service: LibraryService,
) -> None:
    requests = tuple(GameRemovalRequest("same", "installed") for _ in range(501))

    with pytest.raises(InvalidGameRemoval, match="500"):
        library_service.remove_games(requests)


@pytest.mark.parametrize(
    ("raw_version", "expected_version"),
    [("  Ver 2.0  ", "Ver 2.0"), ("   ", None), (None, None)],
)
def test_set_game_metadata_atomically_normalizes_and_protects_both_fields(
    library_service: LibraryService,
    raw_version: str | None,
    expected_version: str | None,
) -> None:
    root = library_service.add_root(r"D:\Games", "children", 1, [])
    game = library_service.create_game_for_test(root.id, "Alice", "Alice")

    updated = library_service.set_game_metadata(
        game.id,
        "  自定义标题  ",
        raw_version,
    )

    with library_service._repository.factory.connect(readonly=True) as connection:  # noqa: SLF001
        row = connection.execute(
            "SELECT title_is_manual, version_is_manual FROM games WHERE id = ?",
            (game.id,),
        ).fetchone()
    assert updated.title == "自定义标题"
    assert updated.version == expected_version
    assert (row["title_is_manual"], row["version_is_manual"]) == (1, 1)


def test_set_game_metadata_rejects_empty_title_without_changing_either_field(
    library_service: LibraryService,
) -> None:
    root = library_service.add_root(r"D:\Games", "children", 1, [])
    game = library_service.create_game_for_test(root.id, "Alice", "Alice")
    library_service.set_game_metadata(game.id, "Saved title", "v1.0")

    with pytest.raises(InvalidGameConfiguration, match="标题|title"):
        library_service.set_game_metadata(game.id, "   ", "v2.0")

    preserved = library_service.get_game(game.id)
    assert preserved is not None
    assert preserved.title == "Saved title"
    assert preserved.version == "v1.0"


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


def test_set_game_executable_stores_the_selected_pe_architecture(
    tmp_path: Path, library_service: LibraryService, monkeypatch
) -> None:
    root_path = tmp_path / "games"
    game_path = root_path / "Alice"
    game_path.mkdir(parents=True)
    executable = game_path / "Alice.exe"
    executable.write_bytes(b"MZ")
    root = library_service.add_root(str(root_path), "children", 1, [])
    game = library_service.create_game_for_test(root.id, "Alice", "Alice")
    monkeypatch.setattr(
        "gameshelf.library.service.read_pe_metadata",
        lambda _: PeMetadata("", "", "", "x64"),
        raising=False,
    )

    updated = library_service.set_game_executable(game.id, str(executable))

    assert updated.main_exe_relpath == "Alice.exe"
    assert updated.main_exe_is_manual is True
    assert updated.exe_arch == "x64"
