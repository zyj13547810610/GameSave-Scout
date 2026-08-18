from io import BytesIO
from pathlib import Path

from PIL import Image

from gameshelf.bootstrap.paths import AppPaths
from gameshelf.bridge.api import BridgeApi
from gameshelf.bridge.tasks import TaskRegistry
from gameshelf.covers.service import CoverService
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
        snapshot = tasks.wait(result["data"]["taskId"], timeout=3)
        assert snapshot.result["checked"] == 0
        assert snapshot.result["cacheHits"] == 0
        assert snapshot.result["reanalyzed"] == 0
        assert snapshot.result["fullAnalyses"] == 0
    finally:
        tasks.close()
        writer.close()


def test_start_scan_rejects_a_disabled_root_before_submitting_task(
    tmp_path: Path,
) -> None:
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
        api.update_root(
            {
                "rootId": root["id"],
                "displayPath": root["displayPath"],
                "enabled": False,
                "scanMode": root["scanMode"],
                "maxDepth": root["maxDepth"],
                "exclusions": root["exclusions"],
            }
        )

        result = api.start_scan({"rootId": root["id"], "kind": "quick"})

        assert result["ok"] is False
        assert result["error"]["code"] == "root_disabled"
    finally:
        tasks.close()
        writer.close()


def test_start_game_reanalysis_returns_task_id_and_updated_game(tmp_path: Path) -> None:
    api, tasks, writer, library = _library_api(tmp_path)
    game_root = tmp_path / "games"
    game_dir = game_root / "Alice"
    game_dir.mkdir(parents=True)
    (game_dir / "Alice.exe").write_bytes(b"not-a-real-pe")
    try:
        root = library.add_root(str(game_root), "children", 1, [])
        game = library.create_game_for_test(root.id, "Alice", "Alice")

        result = api.start_game_reanalysis({"gameId": game.id})

        assert result["ok"] is True
        task_id = result["data"]["taskId"]
        assert isinstance(task_id, str)
        snapshot = tasks.wait(task_id, timeout=3)
        assert snapshot.status == "completed"
        assert snapshot.result["id"] == game.id
        assert snapshot.result["mainExeRelpath"] == "Alice.exe"
    finally:
        tasks.close()
        writer.close()


def test_start_game_reanalysis_rejects_bad_or_unavailable_games(
    tmp_path: Path,
) -> None:
    api, tasks, writer, library = _library_api(tmp_path)
    game_root = tmp_path / "games"
    game_dir = game_root / "Alice"
    game_dir.mkdir(parents=True)
    try:
        root = library.add_root(str(game_root), "children", 1, [])
        game = library.create_game_for_test(root.id, "Alice", "Alice")
        writer.submit(
            lambda connection: connection.execute(
                "UPDATE games SET status = 'missing' WHERE id = ?", (game.id,)
            ).rowcount
        ).result()

        malformed = (
            api.start_game_reanalysis({"gameId": ""}),
            api.start_game_reanalysis({"gameId": game.id, "extra": True}),
        )
        missing = api.start_game_reanalysis({"gameId": "unknown"})
        unavailable = api.start_game_reanalysis({"gameId": game.id})

        assert [item["error"]["code"] for item in malformed] == [
            "invalid_request",
            "invalid_request",
        ]
        assert missing["error"]["code"] == "game_not_found"
        assert unavailable["error"]["code"] == "invalid_game_state"
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


def test_set_game_metadata_returns_version_and_accepts_null(tmp_path: Path) -> None:
    api, tasks, writer, library = _library_api(tmp_path)
    try:
        root = library.add_root(r"D:\Games", "children", 1, [])
        game = library.create_game_for_test(root.id, "Alice", "Alice")

        updated = api.set_game_metadata(
            {"gameId": game.id, "title": "  Alice  ", "version": "  v1.0  "}
        )
        cleared = api.set_game_metadata(
            {"gameId": game.id, "title": "Alice", "version": None}
        )

        assert updated["ok"] is True
        assert updated["data"]["title"] == "Alice"
        assert updated["data"]["version"] == "v1.0"
        assert cleared["ok"] is True
        assert cleared["data"]["version"] is None
    finally:
        tasks.close()
        writer.close()


def test_set_game_metadata_rejects_incomplete_or_malformed_payloads(
    tmp_path: Path,
) -> None:
    api, tasks, writer, library = _library_api(tmp_path)
    try:
        root = library.add_root(r"D:\Games", "children", 1, [])
        game = library.create_game_for_test(root.id, "Alice", "Alice")
        invalid_payloads = (
            {"gameId": game.id, "title": "Alice"},
            {"gameId": game.id, "title": "Alice", "version": 1},
            {"gameId": game.id, "title": "Alice", "version": None, "extra": True},
            {"gameId": game.id, "title": "   ", "version": "v2"},
        )

        results = [api.set_game_metadata(payload) for payload in invalid_payloads]

        assert all(result["ok"] is False for result in results)
        assert all(result["error"]["code"] == "invalid_request" for result in results)
        preserved = library.get_game(game.id)
        assert preserved is not None
        assert preserved.title == "Alice"
        assert preserved.version is None
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
        covers = api._covers  # noqa: SLF001
        assert isinstance(covers, CoverService)
        root = library.add_root(r"D:\Games", "children", 1, [])
        game = library.create_game_for_test(root.id, "GameA", "GameA")
        cover = covers.import_clipboard_png(game.id, _png())

        result = api.delete_missing_game({"gameId": game.id})

        assert result["ok"] is False
        assert result["error"]["code"] == "invalid_game_state"
        preserved = library.get_game(game.id)
        assert preserved is not None
        assert preserved.cover_original_relpath == cover.original_relpath
        assert (covers._paths.data_dir / cover.original_relpath).is_file()  # noqa: SLF001
    finally:
        tasks.close()
        writer.close()


def test_delete_missing_game_removes_record_through_bridge(tmp_path: Path) -> None:
    api, tasks, writer, library = _library_api(tmp_path)
    try:
        covers = api._covers  # noqa: SLF001
        assert isinstance(covers, CoverService)
        root = library.add_root(r"D:\Games", "children", 1, [])
        game = library.create_game_for_test(root.id, "GameA", "GameA")
        cover = covers.import_clipboard_png(game.id, _png())
        library.remove_root(root.id)
        cleanup_calls: list[tuple[str, ...]] = []

        def cleanup_after_commit(relative_paths) -> int:
            assert library.get_game(game.id) is None
            cleanup_calls.append(tuple(relative_paths))
            return 0

        covers.cleanup_managed_files = cleanup_after_commit  # type: ignore[method-assign]

        result = api.delete_missing_game({"gameId": game.id})

        assert result == {"ok": True, "data": {"removed": True}}
        assert library.get_game(game.id) is None
        assert cleanup_calls == [(cover.original_relpath, cover.thumb_relpath)]
    finally:
        tasks.close()
        writer.close()


def test_batch_remove_returns_summary_and_cleanup_warning_without_paths(
    tmp_path: Path,
) -> None:
    api, tasks, writer, library = _library_api(tmp_path)
    try:
        covers = api._covers  # noqa: SLF001
        assert isinstance(covers, CoverService)
        installed_root = library.add_root(r"D:\Games", "children", 1, [])
        missing_root = library.add_root(r"E:\OldGames", "children", 1, [])
        installed = library.create_game_for_test(
            installed_root.id, "GameA", "GameA"
        )
        missing = library.create_game_for_test(missing_root.id, "GameB", "GameB")
        cover = covers.import_clipboard_png(installed.id, _png())
        library.remove_root(missing_root.id)
        cleanup_calls: list[tuple[str, ...]] = []

        def cleanup_with_warnings(relative_paths) -> int:
            cleanup_calls.append(tuple(relative_paths))
            return 2

        covers.cleanup_managed_files = cleanup_with_warnings  # type: ignore[method-assign]

        result = api.remove_games(
            {
                "items": [
                    {"gameId": installed.id, "expectedStatus": "installed"},
                    {"gameId": missing.id, "expectedStatus": "missing"},
                    {"gameId": installed.id, "expectedStatus": "installed"},
                ]
            }
        )

        assert result == {
            "ok": True,
            "data": {
                "installedCount": 1,
                "missingCount": 1,
                "updatedRootCount": 1,
                "cleanupWarnings": [
                    "有 2 个受管封面文件未能清理，可稍后查看日志。"
                ],
            },
        }
        assert cleanup_calls == [(cover.original_relpath, cover.thumb_relpath)]
        assert str(covers._paths.data_dir) not in str(result)  # noqa: SLF001
        assert library.list_games() == ()
        assert library.list_roots()[0].exclusions == ("GameA",)
    finally:
        tasks.close()
        writer.close()


def test_batch_remove_status_change_rolls_back_and_skips_cover_cleanup(
    tmp_path: Path,
) -> None:
    api, tasks, writer, library = _library_api(tmp_path)
    try:
        covers = api._covers  # noqa: SLF001
        assert isinstance(covers, CoverService)
        root = library.add_root(r"D:\Games", "children", 1, [])
        first = library.create_game_for_test(root.id, "GameA", "GameA")
        second = library.create_game_for_test(root.id, "GameB", "GameB")
        cleanup_calls: list[tuple[str, ...]] = []
        covers.cleanup_managed_files = (  # type: ignore[method-assign]
            lambda paths: cleanup_calls.append(tuple(paths)) or 0
        )

        result = api.remove_games(
            {
                "items": [
                    {"gameId": first.id, "expectedStatus": "installed"},
                    {"gameId": second.id, "expectedStatus": "missing"},
                ]
            }
        )

        assert result["ok"] is False
        assert result["error"]["code"] == "invalid_game_state"
        assert {game.id for game in library.list_games()} == {first.id, second.id}
        assert library.list_roots()[0].exclusions == ()
        assert cleanup_calls == []
    finally:
        tasks.close()
        writer.close()


def test_batch_remove_rejects_non_removable_status_in_payload(tmp_path: Path) -> None:
    api, tasks, writer, _ = _library_api(tmp_path)
    try:
        result = api.remove_games(
            {"items": [{"gameId": "game-1", "expectedStatus": "save_only"}]}
        )

        assert result["ok"] is False
        assert result["error"]["code"] == "invalid_request"
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
    covers = CoverService(paths, repository, writer)
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
        covers=covers,
    )
    return api, tasks, writer, library


def _png() -> bytes:
    stream = BytesIO()
    Image.new("RGBA", (30, 45), "purple").save(stream, format="PNG")
    return stream.getvalue()
