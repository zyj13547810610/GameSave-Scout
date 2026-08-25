from pathlib import Path

from gamesave_scout.bootstrap.paths import AppPaths
from gamesave_scout.bridge.api import BridgeApi
from gamesave_scout.bridge.tasks import TaskRegistry
from gamesave_scout.db.connection import ConnectionFactory
from gamesave_scout.db.migrator import Migrator
from gamesave_scout.db.writer import DbWriter
from gamesave_scout.library.group_repository import GroupRepository
from gamesave_scout.library.group_service import GroupService
from gamesave_scout.library.repository import LibraryRepository
from gamesave_scout.library.service import LibraryService


def test_group_api_crud_returns_stable_dtos(tmp_path: Path) -> None:
    api, tasks, writer, _, _ = _group_api(tmp_path)
    try:
        created = api.create_game_group({"name": "  RPG  "})
        group_id = created["data"]["id"]
        listed = api.list_game_groups()
        renamed = api.rename_game_group(
            {"groupId": group_id, "name": "角色扮演"}
        )
        deleted = api.delete_game_group({"groupId": group_id})

        assert created["ok"] is True
        assert created["data"] == {
            "id": group_id,
            "name": "RPG",
            "gameCount": 0,
            "createdAt": created["data"]["createdAt"],
            "updatedAt": created["data"]["updatedAt"],
        }
        assert listed["data"] == [created["data"]]
        assert renamed["data"]["name"] == "角色扮演"
        assert deleted == {"ok": True, "data": {"deleted": True}}
        assert api.list_game_groups()["data"] == []
    finally:
        tasks.close()
        writer.close()


def test_group_api_sets_and_batch_updates_memberships(tmp_path: Path) -> None:
    api, tasks, writer, library, _ = _group_api(tmp_path)
    try:
        root = library.add_root(r"D:\Games", "children", 1, [])
        first = library.create_game_for_test(root.id, "Alice", "Alice")
        second = library.create_game_for_test(root.id, "Bob", "Bob")
        group_id = api.create_game_group({"name": "RPG"})["data"]["id"]

        assigned = api.set_game_groups(
            {"gameId": first.id, "groupIds": [group_id]}
        )
        added = api.update_game_group_memberships(
            {
                "groupId": group_id,
                "gameIds": [first.id, second.id, second.id],
                "mode": "add",
            }
        )
        removed = api.update_game_group_memberships(
            {"groupId": group_id, "gameIds": [first.id], "mode": "remove"}
        )

        assert assigned["data"]["groupIds"] == [group_id]
        assert added == {
            "ok": True,
            "data": {"addedCount": 1, "removedCount": 0, "unchangedCount": 1},
        }
        assert removed == {
            "ok": True,
            "data": {"addedCount": 0, "removedCount": 1, "unchangedCount": 0},
        }
        assert api.list_game_groups()["data"][0]["gameCount"] == 1
    finally:
        tasks.close()
        writer.close()


def test_group_api_rejects_malformed_payloads(tmp_path: Path) -> None:
    api, tasks, writer, _, _ = _group_api(tmp_path)
    try:
        results = (
            api.create_game_group({"name": "RPG", "extra": True}),
            api.rename_game_group({"groupId": "group", "name": ""}),
            api.delete_game_group({}),
            api.set_game_groups({"gameId": "game", "groupIds": "group"}),
            api.update_game_group_memberships(
                {"groupId": "group", "gameIds": [], "mode": "replace"}
            ),
        )

        assert [result["error"]["code"] for result in results] == [
            "invalid_request",
            "invalid_request",
            "invalid_request",
            "invalid_request",
            "invalid_request",
        ]
    finally:
        tasks.close()
        writer.close()


def test_group_api_maps_domain_errors_to_stable_codes(tmp_path: Path) -> None:
    api, tasks, writer, _, factory = _group_api(tmp_path)
    try:
        group_id = api.create_game_group({"name": "RPG"})["data"]["id"]
        duplicate = api.create_game_group({"name": "ｒｐｇ"})
        invalid_name = api.create_game_group({"name": "x" * 41})
        missing_group = api.delete_game_group({"groupId": "missing"})
        missing_game = api.set_game_groups(
            {"gameId": "missing", "groupIds": [group_id]}
        )
        oversized = api.update_game_group_memberships(
            {
                "groupId": group_id,
                "gameIds": ["game"] * 501,
                "mode": "add",
            }
        )
        with factory.connect() as connection:
            connection.execute("DELETE FROM game_groups")
            connection.executemany(
                """
                INSERT INTO game_groups(id, name, normalized_name, created_at, updated_at)
                VALUES (?, ?, ?, 'now', 'now')
                """,
                (
                    (f"group-{index}", f"Group {index}", f"group {index}")
                    for index in range(200)
                ),
            )
            connection.commit()
        limit = api.create_game_group({"name": "One more"})

        assert duplicate["error"]["code"] == "duplicate_game_group"
        assert invalid_name["error"]["code"] == "invalid_game_group_operation"
        assert missing_group["error"]["code"] == "game_group_not_found"
        assert missing_game["error"]["code"] == "game_not_found"
        assert oversized["error"]["code"] == "invalid_game_group_operation"
        assert limit["error"]["code"] == "game_group_limit"
    finally:
        tasks.close()
        writer.close()


def _group_api(
    tmp_path: Path,
) -> tuple[
    BridgeApi,
    TaskRegistry,
    DbWriter,
    LibraryService,
    ConnectionFactory,
]:
    paths = AppPaths.from_root(tmp_path / "portable")
    paths.ensure_writable()
    factory = ConnectionFactory(paths.database_file)
    Migrator(factory, paths.backups_dir).migrate()
    writer = DbWriter(factory)
    writer.start()
    tasks = TaskRegistry(max_workers=1)
    repository = LibraryRepository(factory)
    library = LibraryService(repository, writer)
    groups = GroupService(
        connection_factory=factory,
        writer=writer,
        repository=GroupRepository(factory),
    )
    api = BridgeApi(
        paths,
        tasks,
        schema_version=3,
        library=library,
        groups=groups,
    )
    return api, tasks, writer, library, factory
