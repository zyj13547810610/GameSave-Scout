from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from gameshelf.bootstrap.paths import AppPaths
from gameshelf.bridge.api import BridgeApi
from gameshelf.bridge.tasks import TaskRegistry
from gameshelf.db.connection import ConnectionFactory
from gameshelf.db.migrator import Migrator
from gameshelf.db.writer import DbWriter
from gameshelf.engines.registry import DetectorRegistry
from gameshelf.engines.service import EngineDetectionService, EngineOption
from gameshelf.library.repository import LibraryRepository
from gameshelf.library.service import LibraryService


@pytest.fixture
def engine_api(tmp_path: Path) -> Iterator["EngineApiHarness"]:
    paths = AppPaths.from_root(tmp_path / "portable")
    paths.ensure_writable()
    factory = ConnectionFactory(paths.database_file)
    Migrator(factory, paths.backups_dir).migrate()
    writer = DbWriter(factory)
    writer.start()
    tasks = TaskRegistry(max_workers=1)
    repository = LibraryRepository(factory)
    library = LibraryService(repository, writer)
    game_root = tmp_path / "games"
    (game_root / "Sample").mkdir(parents=True)
    root = library.add_root(str(game_root), "children", 1, [])
    game = library.create_game_for_test(root.id, "Sample", "Sample")
    writer.submit(
        lambda connection: connection.execute(
            """
            UPDATE games
            SET detected_engine_id = 'unity', detected_engine_variant = NULL,
                engine_id = 'unity', engine_variant = NULL,
                engine_confidence = 0.94,
                engine_evidence_json = json(?),
                engine_rules_version = 'unity-test'
            WHERE id = ?
            """,
            (
                '[{"code":"unity_player","detail":"发现 UnityPlayer.dll",'
                '"path":"UnityPlayer.dll","weight":0.42}]',
                game.id,
            ),
        ).rowcount
    ).result()
    detector = EngineDetectionService.from_rules_file(
        Path(__file__).parents[3]
        / "resources"
        / "rules"
        / "builtin"
        / "engines.yaml"
    )
    catalog = _MutableRuleCatalog(detector)
    api = BridgeApi(
        paths,
        tasks,
        schema_version=1,
        library=library,
        rule_catalog=catalog,  # type: ignore[arg-type]
    )
    harness = EngineApiHarness(api, tasks, writer, game.id, catalog)
    try:
        yield harness
    finally:
        tasks.close()
        writer.close()


def test_manual_engine_api_rejects_empty_custom_label(
    engine_api: "EngineApiHarness",
) -> None:
    result = engine_api.api.set_game_engine(
        {"gameId": engine_api.game_id, "engineId": "custom", "customLabel": "  "}
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_engine"


def test_manual_engine_can_be_set_and_cleared(engine_api: "EngineApiHarness") -> None:
    selected = engine_api.api.set_game_engine(
        {
            "gameId": engine_api.game_id,
            "engineId": "custom",
            "customLabel": "My Engine",
        }
    )

    assert selected["ok"] is True
    assert selected["data"]["engineId"] == "custom:My Engine"
    assert selected["data"]["engineIsManual"] is True
    assert selected["data"]["detectedEngine"]["id"] == "unity"

    cleared = engine_api.api.clear_manual_engine({"gameId": engine_api.game_id})

    assert cleared["ok"] is True
    assert cleared["data"]["engineId"] == "unity"
    assert cleared["data"]["engineIsManual"] is False


def test_engine_options_and_evidence_are_exposed(engine_api: "EngineApiHarness") -> None:
    options = engine_api.api.list_engine_options()
    game = engine_api.api.list_games()["data"][0]

    assert options["ok"] is True
    assert {item["id"] for item in options["data"]} >= {"renpy", "unity", "qlie"}
    assert game["engineLabel"] == "Unity"
    assert game["detectedEngine"] == {
        "id": "unity",
        "label": "Unity",
        "variant": None,
        "confidence": "高",
        "evidence": [
            {
                "code": "unity_player",
                "detail": "发现 UnityPlayer.dll",
                "path": "UnityPlayer.dll",
                "weight": 0.42,
            }
        ],
        "ambiguous": False,
        "experimental": False,
        "alternatives": [],
    }


def test_engine_api_reads_the_latest_catalog_snapshot(
    engine_api: "EngineApiHarness",
) -> None:
    replacement = EngineDetectionService(
        DetectorRegistry(()),
        options=(EngineOption("user_engine", "用户新引擎", True),),
    )
    engine_api.catalog.engine_detection = replacement

    options = engine_api.api.list_engine_options()
    selected = engine_api.api.set_game_engine(
        {"gameId": engine_api.game_id, "engineId": "user_engine"}
    )

    assert options["data"] == [
        {"id": "user_engine", "label": "用户新引擎", "experimental": True}
    ]
    assert selected["ok"] is True
    assert selected["data"]["engineLabel"] == "用户新引擎"


@dataclass
class EngineApiHarness:
    api: BridgeApi
    tasks: TaskRegistry
    writer: DbWriter
    game_id: str
    catalog: "_MutableRuleCatalog"


class _MutableRuleCatalog:
    def __init__(self, engine_detection: EngineDetectionService) -> None:
        self.engine_detection = engine_detection

    def snapshot(self) -> object:
        return SimpleNamespace(engine_detection=self.engine_detection)
