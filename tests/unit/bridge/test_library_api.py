from pathlib import Path

from gameshelf.bootstrap.paths import AppPaths
from gameshelf.bridge.api import BridgeApi
from gameshelf.bridge.tasks import TaskRegistry
from gameshelf.db.connection import ConnectionFactory
from gameshelf.db.migrator import Migrator
from gameshelf.db.writer import DbWriter
from gameshelf.library.launcher import GameLauncher
from gameshelf.library.repository import LibraryRepository
from gameshelf.library.service import LibraryService
from gameshelf.platform.windows.processes import WindowsProcessLauncher
from gameshelf.platform.windows.shell import WindowsShell
from gameshelf.scanning.service import ScanService


def test_start_scan_returns_task_id(tmp_path: Path) -> None:
    api, tasks, writer, _ = _library_api(tmp_path)
    game_root = tmp_path / "games"
    game_root.mkdir()
    try:
        root = api.add_root(
            {
                "displayPath": str(game_root),
                "scanMode": "children",
                "maxDepth": 1,
                "exclusions": [],
            }
        )["data"]

        result = api.start_scan({"rootId": root["id"], "kind": "full"})

        assert result["ok"] is True
        assert isinstance(result["data"]["taskId"], str)
        tasks.wait(result["data"]["taskId"], timeout=3)
    finally:
        tasks.close()
        writer.close()


def test_manual_executable_must_remain_inside_game_directory(tmp_path: Path) -> None:
    api, tasks, writer, library = _library_api(tmp_path)
    game_root = tmp_path / "games"
    game_dir = game_root / "Alice"
    game_dir.mkdir(parents=True)
    outside = tmp_path / "Other" / "tool.exe"
    outside.parent.mkdir()
    outside.write_bytes(b"MZ")
    try:
        root = library.add_root(str(game_root), "children", 1, [])
        game = library.create_game_for_test(root.id, "Alice", "Alice")

        result = api.set_game_executable(
            {"gameId": game.id, "selectedPath": str(outside)}
        )

        assert result["ok"] is False
        assert result["error"]["code"] == "invalid_executable"
    finally:
        tasks.close()
        writer.close()


def test_library_dtos_are_camel_case_and_bad_payloads_are_rejected(
    tmp_path: Path,
) -> None:
    api, tasks, writer, _ = _library_api(tmp_path)
    try:
        invalid = api.add_root({"displayPath": "relative", "scanMode": "children"})
        assert invalid["ok"] is False
        assert invalid["error"]["code"] == "invalid_request"

        root_path = tmp_path / "games"
        root_path.mkdir()
        created = api.add_root(
            {
                "displayPath": str(root_path),
                "scanMode": "recursive",
                "maxDepth": 2,
                "exclusions": ["tools"],
            }
        )
        assert created["ok"] is True
        assert created["data"]["displayPath"] == str(root_path)
        assert created["data"]["scanMode"] == "recursive"
        assert created["data"]["maxDepth"] == 2
        assert api.list_roots()["data"] == [created["data"]]
    finally:
        tasks.close()
        writer.close()


def test_remove_installed_game_adds_exclusion_through_bridge(tmp_path: Path) -> None:
    api, tasks, writer, library = _library_api(tmp_path)
    try:
        root = library.add_root(r"D:\Games", "recursive", 3, ["Tools"])
        game = library.create_game_for_test(root.id, "Group/GameA", "GameA")

        result = api.remove_game_and_exclude({"gameId": game.id})

        assert result == {"ok": True, "data": {"removed": True}}
        assert api.list_games()["data"] == []
        assert api.list_roots()["data"][0]["exclusions"] == ["Tools", "Group/GameA"]
    finally:
        tasks.close()
        writer.close()


def test_delete_missing_game_rejects_installed_game_through_bridge(
    tmp_path: Path,
) -> None:
    api, tasks, writer, library = _library_api(tmp_path)
    try:
        root = library.add_root(r"D:\Games", "children", 1, [])
        game = library.create_game_for_test(root.id, "GameA", "GameA")

        result = api.delete_missing_game({"gameId": game.id})

        assert result["ok"] is False
        assert result["error"]["code"] == "invalid_game_state"
        assert library.get_game(game.id) is not None
    finally:
        tasks.close()
        writer.close()


def test_delete_missing_game_removes_record_through_bridge(tmp_path: Path) -> None:
    api, tasks, writer, library = _library_api(tmp_path)
    try:
        root = library.add_root(r"D:\Games", "children", 1, [])
        game = library.create_game_for_test(root.id, "GameA", "GameA")
        library.remove_root(root.id)

        result = api.delete_missing_game({"gameId": game.id})

        assert result == {"ok": True, "data": {"removed": True}}
        assert library.get_game(game.id) is None
    finally:
        tasks.close()
        writer.close()


def _library_api(
    tmp_path: Path,
) -> tuple[BridgeApi, TaskRegistry, DbWriter, LibraryService]:
    paths = AppPaths.from_root(tmp_path / "portable")
    paths.ensure_writable()
    factory = ConnectionFactory(paths.database_file)
    Migrator(factory, paths.backups_dir).migrate()
    writer = DbWriter(factory)
    writer.start()
    tasks = TaskRegistry(max_workers=1)
    repository = LibraryRepository(factory)
    library = LibraryService(repository, writer)
    scanner = ScanService(repository, writer)
    launcher = GameLauncher(
        repository, writer, WindowsProcessLauncher(), WindowsShell()
    )
    api = BridgeApi(
        paths,
        tasks,
        schema_version=1,
        library=library,
        scanner=scanner,
        launcher=launcher,
    )
    return api, tasks, writer, library
