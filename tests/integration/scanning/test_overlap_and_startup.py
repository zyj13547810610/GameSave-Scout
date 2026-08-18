from pathlib import Path
from threading import Event

from gameshelf.bridge.tasks import TaskContext
from gameshelf.db.connection import ConnectionFactory
from gameshelf.db.migrator import Migrator
from gameshelf.db.writer import DbWriter
from gameshelf.library.repository import LibraryRepository
from gameshelf.library.service import LibraryService
from gameshelf.scanning.service import ScanService


def test_quick_checks_only_known_games_for_children_and_recursive_roots(
    tmp_path: Path,
) -> None:
    factory = ConnectionFactory(tmp_path / "data" / "library.db")
    Migrator(factory, tmp_path / "backups").migrate()
    writer = DbWriter(factory)
    writer.start()
    repository = LibraryRepository(factory)
    library = LibraryService(repository, writer)
    scanner = ScanService(repository, writer)

    def context() -> TaskContext:
        return TaskContext(Event(), lambda *_: None)

    try:
        children_path = tmp_path / "children"
        known_child = children_path / "KnownChild"
        known_child.mkdir(parents=True)
        children = library.add_root(str(children_path), "children", 1, [])
        library.create_game_for_test(children.id, "KnownChild", "KnownChild")
        (children_path / "NewChild").mkdir()
        quick_children = scanner.scan_root(children.id, "quick", context())
        assert quick_children.discovered == 1
        assert quick_children.added == 0
        assert not any(game.title == "NewChild" for game in library.list_games())

        recursive_path = tmp_path / "recursive"
        known = recursive_path / "group" / "Known"
        known.mkdir(parents=True)
        (known / "Known.exe").write_bytes(b"MZ")
        recursive = library.add_root(str(recursive_path), "recursive", 2, [])
        scanner.scan_root(recursive.id, "full", context())
        new_game = recursive_path / "other" / "NewGame"
        new_game.mkdir(parents=True)
        (new_game / "New.exe").write_bytes(b"MZ")

        quick_recursive = scanner.scan_root(recursive.id, "quick", context())
        assert quick_recursive.discovered == 1
        assert not any(game.title == "NewGame" for game in library.list_games())

        scanner.scan_root(children.id, "full", context())
        scanner.scan_root(recursive.id, "full", context())
        assert any(game.title == "NewChild" for game in library.list_games())
        assert any(game.title == "NewGame" for game in library.list_games())
    finally:
        writer.close()
