from collections.abc import Iterator
from pathlib import Path
from threading import Event

import pytest

from gameshelf.bridge.tasks import TaskContext
from gameshelf.db.connection import ConnectionFactory
from gameshelf.db.migrator import Migrator
from gameshelf.db.writer import DbWriter
from gameshelf.engines.registry import DetectorRegistry
from gameshelf.engines.service import EngineDetectionService
from gameshelf.library.models import Game
from gameshelf.library.repository import LibraryRepository
from gameshelf.library.service import LibraryService
from gameshelf.scanning.analysis import GameAnalyzer
from gameshelf.scanning.analysis_cache import AnalysisCacheRepository
from gameshelf.scanning.executable_ranker import ExecutableCandidate
from gameshelf.scanning.pe_metadata import PeMetadata
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

    refreshed = engine_scan_harness.scanner.reanalyze_game(
        game.id, TaskContext(Event(), lambda *_: None)
    )

    assert refreshed.detected_engine_id == "unity"
    assert refreshed.engine_id == "custom:my-engine"
    assert refreshed.engine_is_manual is True
    assert refreshed.engine_confidence == pytest.approx(0.97)
    assert refreshed.engine_rules_version == "unity-2026.08.12"
    assert {item.code for item in refreshed.engine_evidence} == {
        "unity_player",
        "unity_data",
    }


def test_detector_failure_preserves_previous_detected_and_adopted_engine(
    engine_scan_harness: "EngineScanHarness",
) -> None:
    game = engine_scan_harness.scan_fixture("renpy")
    engine_scan_harness.scanner = ScanService(
        LibraryRepository(engine_scan_harness.factory),
        engine_scan_harness.writer,
        EngineDetectionService(DetectorRegistry([BrokenDetector()])),
    )

    summary = engine_scan_harness.scanner.scan_root(
        engine_scan_harness.root_id,
        "full",
        TaskContext(Event(), lambda *_: None),
    )
    refreshed = summary.games[0]

    assert summary.warnings == 1
    assert refreshed.detected_engine_id == "renpy"
    assert refreshed.engine_id == "renpy"
    assert refreshed.engine_evidence == game.engine_evidence
    assert AnalysisCacheRepository(engine_scan_harness.factory).get(game.id) is None


def test_rescan_uses_valid_manual_executable_for_engine_detection(
    engine_scan_harness: "EngineScanHarness", monkeypatch
) -> None:
    engine_scan_harness.game_path.mkdir()
    wrong_tool = engine_scan_harness.game_path / "WrongTool.exe"
    game_executable = engine_scan_harness.game_path / "Game.exe"
    wrong_tool.write_bytes(b"MZ")
    game_executable.write_bytes(b"MZ")
    game = engine_scan_harness.rescan()
    monkeypatch.setattr(
        "gameshelf.library.service.read_pe_metadata",
        lambda _: PeMetadata("", "", "", "x64"),
        raising=False,
    )
    engine_scan_harness.library.set_game_executable(game.id, str(game_executable))
    (engine_scan_harness.game_path / "UnityPlayer.dll").write_bytes(b"unity")
    data = engine_scan_harness.game_path / "Game_Data"
    data.mkdir()
    (data / "globalgamemanagers").write_bytes(b"unity")
    detector = EngineDetectionService.from_rules_file(
        Path(__file__).parents[3] / "resources" / "rules" / "engines.yaml"
    )
    engine_scan_harness.scanner = ScanService(
        LibraryRepository(engine_scan_harness.factory),
        engine_scan_harness.writer,
        analyzer=GameAnalyzer(
            detector,
            ranker=lambda _: (
                ExecutableCandidate("WrongTool.exe", 100, "x86", ("test",)),
                ExecutableCandidate("Game.exe", 10, "x64", ("test",)),
            ),
        ),
    )

    refreshed = engine_scan_harness.rescan()

    assert engine_scan_harness.detected_executable(game.id) == "WrongTool.exe"
    assert refreshed.main_exe_relpath == "Game.exe"
    assert refreshed.main_exe_is_manual is True
    assert refreshed.exe_arch == "x64"
    assert refreshed.detected_engine_id == "unity"


def test_invalid_manual_executable_falls_back_and_adds_warning(
    engine_scan_harness: "EngineScanHarness",
) -> None:
    engine_scan_harness.game_path.mkdir()
    (engine_scan_harness.game_path / "Game.exe").write_bytes(b"MZ")
    game = engine_scan_harness.rescan()
    engine_scan_harness.set_stored_manual_executable(
        game.id, "../Outside.exe", architecture="x64"
    )
    (engine_scan_harness.game_path / "UnityPlayer.dll").write_bytes(b"unity")
    data = engine_scan_harness.game_path / "Game_Data"
    data.mkdir()
    (data / "globalgamemanagers").write_bytes(b"unity")

    summary = engine_scan_harness.scan()
    refreshed = summary.games[0]

    assert summary.warnings == 1
    assert refreshed.main_exe_relpath == "../Outside.exe"
    assert refreshed.main_exe_is_manual is True
    assert refreshed.exe_arch == "x64"
    assert refreshed.detected_engine_id == "unity"


def test_scan_detects_a_unity_runtime_nested_below_the_library_entry(
    engine_scan_harness: "EngineScanHarness",
) -> None:
    build = engine_scan_harness.game_path / "Build"
    data = build / "Mortal_Data"
    data.mkdir(parents=True)
    (build / "Mortal.exe").write_bytes(b"MZ")
    (build / "UnityPlayer.dll").write_bytes(b"unity")
    (data / "globalgamemanagers").write_bytes(b"unity")
    (build / "UnityCrashHandler64.exe").write_bytes(b"MZ")

    game = engine_scan_harness.rescan()

    assert game.main_exe_relpath == "Build/Mortal.exe"
    assert game.detected_engine_id == "unity"
    assert {item.path for item in game.engine_evidence} == {
        "Build/UnityPlayer.dll",
        "Build/Mortal_Data/globalgamemanagers",
    }


def test_scan_detects_unreal_shipping_runtime(
    engine_scan_harness: "EngineScanHarness",
) -> None:
    runtime = engine_scan_harness.game_path
    (runtime / "Engine" / "Binaries").mkdir(parents=True)
    executable = (
        runtime
        / "Sample"
        / "Binaries"
        / "Win64"
        / "Sample-Win64-Shipping.exe"
    )
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"MZ")

    game = engine_scan_harness.rescan()

    assert game.main_exe_relpath == "Sample/Binaries/Win64/Sample-Win64-Shipping.exe"
    assert game.detected_engine_id == "unreal"


def test_scan_adopts_new_declarative_godot_engine(
    engine_scan_harness: "EngineScanHarness",
) -> None:
    engine_scan_harness.game_path.mkdir()
    (engine_scan_harness.game_path / "Game.exe").write_bytes(b"MZ")
    (engine_scan_harness.game_path / "Game.pck").write_bytes(
        b"GDPC" + b"\x04\0\0\0" + b"\0" * 32
    )

    game = engine_scan_harness.rescan()

    assert game.detected_engine_id == "godot"
    assert game.engine_id == "godot"
    assert game.engine_is_manual is False


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
        summary = self.scan()
        assert len(summary.games) == 1
        return summary.games[0]

    def scan(self):
        return self.scanner.scan_root(
            self.root_id,
            "full",
            TaskContext(Event(), lambda *_: None),
        )

    def detected_executable(self, game_id: str) -> str | None:
        with self.factory.connect(readonly=True) as connection:
            row = connection.execute(
                "SELECT detected_main_exe_relpath FROM games WHERE id = ?", (game_id,)
            ).fetchone()
        assert row is not None
        return row[0]

    def set_stored_manual_executable(
        self, game_id: str, relative_path: str, *, architecture: str
    ) -> None:
        self.writer.submit(
            lambda connection: connection.execute(
                """
                UPDATE games
                SET main_exe_relpath = ?, main_exe_is_manual = 1, exe_arch = ?
                WHERE id = ?
                """,
                (relative_path, architecture, game_id),
            ).rowcount
        ).result()

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


class BrokenDetector:
    def cheap_probe(self, _context: object) -> bool:
        return True

    def inspect(self, _context: object) -> None:
        raise OSError("synthetic detector failure")
