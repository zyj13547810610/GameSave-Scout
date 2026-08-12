from collections.abc import Iterator
from pathlib import Path
from threading import Event

import pytest

from gameshelf.bridge.tasks import TaskContext
from gameshelf.db.connection import ConnectionFactory
from gameshelf.db.migrator import Migrator
from gameshelf.db.writer import DbWriter
from gameshelf.engines.service import EngineDetectionService
from gameshelf.library.models import Game
from gameshelf.library.repository import LibraryRepository
from gameshelf.library.service import LibraryService
from gameshelf.scanning.service import ScanService


@pytest.fixture
def engine_scan_harness(tmp_path: Path) -> Iterator["EngineScanHarness"]:
    factory = ConnectionFactory(tmp_path / "data" / "library.db")
    Migrator(factory, tmp_path / "backups").migrate()
    writer = DbWriter(factory)
    writer.start()
    repository = LibraryRepository(factory)
    library = LibraryService(repository, writer)
    root_path = tmp_path / "games"
    root_path.mkdir()
    root = library.add_root(str(root_path), "children", 1, [])
    detector = EngineDetectionService.from_rules_file(
        Path(__file__).parents[3] / "resources" / "rules" / "engines.yaml"
    )
    harness = EngineScanHarness(
        root_path,
        root.id,
        factory,
        writer,
        library,
        ScanService(repository, writer, detector),
    )
    try:
        yield harness
    finally:
        writer.close()


def test_scan_adopts_detected_engine_when_not_manual(
    engine_scan_harness: "EngineScanHarness",
) -> None:
    game = engine_scan_harness.scan_fixture("renpy")

    assert game.detected_engine_id == "renpy"
    assert game.engine_id == "renpy"
    assert game.engine_is_manual is False
    assert game.engine_confidence == pytest.approx(0.96)
    assert {item.code for item in game.engine_evidence} == {
        "renpy_script",
        "renpy_runtime",
    }


def test_scan_refreshes_suggestion_but_preserves_manual_engine(
    engine_scan_harness: "EngineScanHarness",
) -> None:
    game = engine_scan_harness.scan_fixture("renpy")
    engine_scan_harness.set_manual_engine(game.id, "custom:my-engine", None)
    engine_scan_harness.replace_fixture_with_unity()

    refreshed = engine_scan_harness.rescan()

    assert refreshed.detected_engine_id == "unity"
    assert refreshed.engine_id == "custom:my-engine"
    assert refreshed.engine_is_manual is True


class EngineScanHarness:
    def __init__(
        self,
        root_path: Path,
        root_id: str,
        factory: ConnectionFactory,
        writer: DbWriter,
        library: LibraryService,
        scanner: ScanService,
    ) -> None:
        self.root_path = root_path
        self.root_id = root_id
        self.factory = factory
        self.writer = writer
        self.library = library
        self.scanner = scanner

    @property
    def game_path(self) -> Path:
        return self.root_path / "SampleGame"

    def scan_fixture(self, engine: str) -> Game:
        assert engine == "renpy"
        self.game_path.mkdir()
        (self.game_path / "Game.exe").write_bytes(b"not-a-real-pe")
        (self.game_path / "game").mkdir()
        (self.game_path / "game" / "script.rpyc").write_bytes(b"synthetic")
        (self.game_path / "renpy").mkdir()
        return self.rescan()

    def replace_fixture_with_unity(self) -> None:
        for child in (self.game_path / "game", self.game_path / "renpy"):
            child.rmdir() if not any(child.iterdir()) else _remove_tree(child)
        (self.game_path / "UnityPlayer.dll").write_bytes(b"synthetic")
        data = self.game_path / "Game_Data"
        data.mkdir()
        (data / "globalgamemanagers").write_bytes(b"synthetic")

    def rescan(self) -> Game:
        summary = self.scanner.scan_root(
            self.root_id,
            "full",
            TaskContext(Event(), lambda *_: None),
        )
        assert len(summary.games) == 1
        return summary.games[0]

    def set_manual_engine(
        self, game_id: str, engine_id: str | None, variant: str | None
    ) -> None:
        self.writer.submit(
            lambda connection: connection.execute(
                """
                UPDATE games
                SET engine_id = ?, engine_variant = ?, engine_is_manual = 1
                WHERE id = ?
                """,
                (engine_id, variant, game_id),
            ).rowcount
        ).result()


def _remove_tree(path: Path) -> None:
    for child in path.iterdir():
        if child.is_dir():
            _remove_tree(child)
        else:
            child.unlink()
    path.rmdir()
