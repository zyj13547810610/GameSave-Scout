from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from gameshelf.db.connection import ConnectionFactory
from gameshelf.db.migrator import Migrator
from gameshelf.db.writer import DbWriter
from gameshelf.library.models import Game
from gameshelf.library.repository import LibraryRepository
from gameshelf.library.service import LibraryService
from gameshelf.platform.windows.known_folders import KnownFolders
from gameshelf.saves.models import SaveLocationSuggestion
from gameshelf.saves.repository import SaveLocationRepository
from gameshelf.saves.service import InvalidSaveLocation, SaveLocationService
from gameshelf.saves.templates import PathTemplateResolver


@dataclass
class FakeShell:
    opened_directories: list[Path] = field(default_factory=list)
    revealed_files: list[Path] = field(default_factory=list)

    def open_directory(self, path: Path) -> None:
        self.opened_directories.append(path)

    def reveal_file(self, path: Path) -> None:
        self.revealed_files.append(path)


@dataclass
class FakeRegistry:
    existing: set[str] = field(default_factory=set)
    opened: list[str] = field(default_factory=list)

    def key_exists(self, key: str) -> bool:
        return key in self.existing

    def open_key(self, key: str) -> None:
        self.opened.append(key)


@dataclass
class SaveStack:
    service: SaveLocationService
    library: LibraryService
    game: Game
    home: Path
    game_dir: Path
    shell: FakeShell
    registry: FakeRegistry


@pytest.fixture
def save_stack(tmp_path: Path) -> Iterator[SaveStack]:
    factory = ConnectionFactory(tmp_path / "data" / "library.db")
    Migrator(factory, tmp_path / "backups").migrate()
    writer = DbWriter(factory)
    writer.start()
    library = LibraryService(LibraryRepository(factory), writer)
    games_root = tmp_path / "Games"
    game_dir = games_root / "Alice"
    game_dir.mkdir(parents=True)
    root = library.add_root(str(games_root), "children", 1, [])
    game = library.create_game_for_test(root.id, "Alice", "Alice")
    home = tmp_path / "Profile"
    home.mkdir()
    folders = KnownFolders(
        home=home,
        app_data=home / "AppData" / "Roaming",
        local_app_data=home / "AppData" / "Local",
        local_app_data_low=home / "AppData" / "LocalLow",
        documents=home / "Documents",
        saved_games=home / "Saved Games",
        program_data=tmp_path / "ProgramData",
        public=tmp_path / "Public",
        windows=tmp_path / "Windows",
    )
    shell = FakeShell()
    registry = FakeRegistry()
    service = SaveLocationService(
        SaveLocationRepository(factory),
        writer,
        PathTemplateResolver(folders),
        library,
        shell,
        registry,
    )
    try:
        yield SaveStack(service, library, game, home, game_dir, shell, registry)
    finally:
        writer.close()


def test_game_can_have_multiple_confirmed_manual_locations(save_stack: SaveStack) -> None:
    save_dir = save_stack.home / "Manual Saves"
    save_dir.mkdir()
    save_file = save_stack.game_dir / "save.dat"
    save_file.write_bytes(b"slot")

    first = save_stack.service.add_manual(save_stack.game.id, "directory", save_dir)
    second = save_stack.service.add_manual(save_stack.game.id, "file", save_file)

    listed = save_stack.service.list_for_game(save_stack.game.id)
    assert [item.id for item in listed] == [first.id, second.id]
    assert [item.path_template for item in listed] == [
        r"<home>\Manual Saves",
        r"<game>\save.dat",
    ]
    assert all(item.confirmed for item in (first, second))


def test_accepting_same_suggestion_twice_deduplicates(save_stack: SaveStack) -> None:
    suggestion = SaveLocationSuggestion(
        kind="directory",
        path_template=r"<game>\save",
        display_path=str(save_stack.game_dir / "save"),
        source="engine",
        confidence=0.8,
        evidence=("引擎默认位置",),
    )

    first = save_stack.service.accept_suggestion(save_stack.game.id, suggestion)
    second = save_stack.service.accept_suggestion(save_stack.game.id, suggestion)

    assert first.id == second.id
    assert len(save_stack.service.list_for_game(save_stack.game.id)) == 1


def test_manual_location_wins_over_same_automatic_suggestion(save_stack: SaveStack) -> None:
    save_dir = save_stack.game_dir / "save"
    save_dir.mkdir()
    manual = save_stack.service.add_manual(save_stack.game.id, "directory", save_dir)
    suggestion = SaveLocationSuggestion(
        kind="directory",
        path_template=r"<game>\save",
        display_path=str(save_dir),
        source="engine",
        confidence=0.8,
        evidence=("引擎默认位置",),
    )

    accepted = save_stack.service.accept_suggestion(save_stack.game.id, suggestion)

    assert accepted.id == manual.id
    assert accepted.source == "manual"


def test_manual_path_must_exist_when_added(save_stack: SaveStack) -> None:
    with pytest.raises(InvalidSaveLocation, match="存在"):
        save_stack.service.add_manual(
            save_stack.game.id,
            "directory",
            save_stack.home / "MissingSave",
        )


def test_verification_updates_existence_but_never_disables_manual_path(
    save_stack: SaveStack,
) -> None:
    save_dir = save_stack.home / "Will Be Removed"
    save_dir.mkdir()
    location = save_stack.service.add_manual(save_stack.game.id, "directory", save_dir)
    save_dir.rmdir()

    verified = save_stack.service.verify_game(save_stack.game.id)[0]

    assert verified.id == location.id
    assert verified.confirmed is True
    assert verified.enabled is True
    assert verified.exists is False
    assert verified.last_verified_at is not None


def test_disable_and_remove_only_change_location_records(save_stack: SaveStack) -> None:
    save_dir = save_stack.home / "Managed"
    save_dir.mkdir()
    location = save_stack.service.add_manual(save_stack.game.id, "directory", save_dir)

    disabled = save_stack.service.disable(location.id)
    save_stack.service.remove(location.id)

    assert disabled.enabled is False
    assert save_stack.service.list_for_game(save_stack.game.id) == ()
    assert save_stack.library.get_game(save_stack.game.id) == save_stack.game


def test_glob_verification_caps_match_count_at_one_thousand(save_stack: SaveStack) -> None:
    slots = save_stack.home / "Slots"
    slots.mkdir()
    for index in range(1001):
        (slots / f"slot-{index}.sav").write_bytes(b"")
    suggestion = SaveLocationSuggestion(
        kind="glob",
        path_template=r"<home>\Slots\*.sav",
        display_path=str(slots / "*.sav"),
        source="ludusavi",
        confidence=0.95,
        evidence=("Ludusavi 清单",),
    )
    save_stack.service.accept_suggestion(save_stack.game.id, suggestion)

    verified = save_stack.service.verify_game(save_stack.game.id)[0]

    assert verified.exists is True
    assert verified.match_count == 1000
    assert verified.matches_truncated is True


def test_open_location_uses_kind_specific_adapter(save_stack: SaveStack) -> None:
    save_file = save_stack.game_dir / "slot.dat"
    save_file.write_bytes(b"slot")
    location = save_stack.service.add_manual(save_stack.game.id, "file", save_file)

    save_stack.service.open_location(location.id)

    assert save_stack.shell.revealed_files == [save_file]


def test_confirmed_registry_location_can_be_verified_and_opened(
    save_stack: SaveStack,
) -> None:
    key = r"HKEY_CURRENT_USER\Software\Studio\Alice"
    save_stack.registry.existing.add(key)
    location = save_stack.service.add_manual(save_stack.game.id, "registry", key)

    verified = save_stack.service.verify_game(save_stack.game.id)[0]
    save_stack.service.open_location(location.id)

    assert verified.exists is True
    assert save_stack.registry.opened == [key]
