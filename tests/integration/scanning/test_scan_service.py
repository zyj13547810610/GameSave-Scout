import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from threading import Event

import pytest

from gameshelf.bridge.tasks import TaskCancelled, TaskContext
from gameshelf.db.connection import ConnectionFactory
from gameshelf.db.migrator import Migrator
from gameshelf.db.writer import DbWriter
from gameshelf.library.models import Game, ScanRoot
from gameshelf.library.repository import LibraryRepository
from gameshelf.library.service import LibraryService
from gameshelf.scanning.service import ScanService, ScanSummary


@pytest.fixture
def scan_harness(tmp_path: Path) -> "ScanHarness":
    factory = ConnectionFactory(tmp_path / "data" / "library.db")
    Migrator(factory, tmp_path / "backups").migrate()
    writer = DbWriter(factory)
    writer.start()
    repository = LibraryRepository(factory)
    library = LibraryService(repository, writer)
    root_path = tmp_path / "games"
    root_path.mkdir()
    harness = ScanHarness(
        root_path,
        factory,
        writer,
        library,
        ScanService(repository, writer),
    )
    try:
        yield harness
    finally:
        writer.close()


def test_successful_full_scan_adds_games_and_marks_removed_game_missing(
    scan_harness: "ScanHarness",
) -> None:
    root = scan_harness.add_root(mode="children")
    scan_harness.mkdir("GameA")

    first = scan_harness.scan(root.id, "full")
    game = scan_harness.games()[0]
    assert first.added == 1

    scan_harness.remove_dir("GameA")
    second = scan_harness.scan(root.id, "full")

    assert second.missing == 1
    assert scan_harness.game(game.id).status == "missing"


def test_unavailable_root_preserves_installed_status(
    scan_harness: "ScanHarness",
) -> None:
    root = scan_harness.add_root(mode="children")
    scan_harness.mkdir("GameA")
    scan_harness.scan(root.id, "full")
    game = scan_harness.games()[0]

    scan_harness.make_root_unavailable()
    summary = scan_harness.scan(root.id, "full")

    assert summary.status == "unavailable"
    assert scan_harness.game(game.id).status == "installed"


def test_manual_executable_survives_new_auto_recommendation(
    scan_harness: "ScanHarness",
) -> None:
    root = scan_harness.add_root(mode="children")
    scan_harness.mkdir("GameA", exes=["A.exe", "Better.exe"])
    game = scan_harness.scan(root.id, "full").games[0]
    scan_harness.set_manual_exe(game.id, "A.exe")

    scan_harness.scan(root.id, "full")

    refreshed = scan_harness.game(game.id)
    assert refreshed.main_exe_relpath == "A.exe"
    assert scan_harness.detected_executable(game.id) is not None


def test_cancelled_scan_preserves_visible_games_and_records_cancelled_session(
    scan_harness: "ScanHarness",
) -> None:
    root = scan_harness.add_root(mode="children")
    scan_harness.mkdir("GameA")
    scan_harness.scan(root.id, "full")
    game = scan_harness.games()[0]
    scan_harness.remove_dir("GameA")
    event = Event()
    event.set()

    with pytest.raises(TaskCancelled):
        scan_harness.scanner.scan_root(
            root.id, "full", TaskContext(event, lambda *_: None)
        )

    assert scan_harness.game(game.id).status == "installed"
    assert scan_harness.latest_session_status() == "cancelled"


def test_recursive_scan_and_direct_no_exe_are_both_supported(
    scan_harness: "ScanHarness",
) -> None:
    recursive = scan_harness.add_root(mode="recursive", depth=2)
    scan_harness.mkdir("group/GameC", exes=["GameC.exe"])

    summary = scan_harness.scan(recursive.id, "full")

    assert [game.relative_dir for game in summary.games] == ["group/GameC"]

    other_path = scan_harness.root_path.parent / "other-games"
    other_path.mkdir()
    direct = scan_harness.add_root(mode="children", path=other_path)
    (other_path / "NoExeYet").mkdir()
    scan_harness.scan(direct.id, "full")
    no_exe = next(game for game in scan_harness.games() if game.title == "NoExeYet")
    assert no_exe.main_exe_relpath is None


def test_overlapping_roots_assign_candidate_to_longest_root(
    scan_harness: "ScanHarness",
) -> None:
    broad = scan_harness.add_root(mode="recursive", depth=2)
    collection = scan_harness.root_path / "Collection"
    collection.mkdir()
    narrow = scan_harness.add_root(mode="children", path=collection)
    scan_harness.mkdir("Collection/GameA")

    scan_harness.scan(broad.id, "full")
    assert scan_harness.games() == ()
    scan_harness.scan(narrow.id, "full")

    games = scan_harness.games()
    assert len(games) == 1
    assert games[0].scan_root_id == narrow.id
    assert games[0].relative_dir == "GameA"


def test_confirmed_move_preserves_original_game_id_and_removes_temporary_candidate(
    scan_harness: "ScanHarness",
) -> None:
    original_root = scan_harness.add_root(mode="children")
    scan_harness.mkdir("GameA", exes=["Game.exe"])
    original = scan_harness.scan(original_root.id, "full").games[0]
    scan_harness.remove_dir("GameA")
    scan_harness.scan(original_root.id, "full")

    moved_root_path = scan_harness.root_path.parent / "moved-games"
    moved_game = moved_root_path / "GameA"
    moved_game.mkdir(parents=True)
    (moved_game / "Game.exe").write_bytes(b"not-a-real-pe")
    moved_root = scan_harness.add_root(mode="children", path=moved_root_path)
    summary = scan_harness.scan(moved_root.id, "full")
    suggestion = summary.move_suggestions[0]

    confirmed = scan_harness.scanner.confirm_move(
        summary.session_id,
        suggestion.existing_game_id,
        suggestion.candidate_relative_dir,
    )

    assert confirmed.id == original.id
    assert confirmed.scan_root_id == moved_root.id
    assert confirmed.status == "installed"
    assert scan_harness.games() == (confirmed,)


@pytest.mark.parametrize(
    ("manual", "original_engine", "expected_engine"),
    [(False, "renpy", "unity"), (True, "custom:mine", "custom:mine")],
)
def test_confirmed_move_refreshes_detection_and_preserves_manual_adoption(
    scan_harness: "ScanHarness",
    manual: bool,
    original_engine: str,
    expected_engine: str,
) -> None:
    original_root = scan_harness.add_root(mode="children")
    scan_harness.mkdir("GameA", exes=["Game.exe"])
    original = scan_harness.scan(original_root.id, "full").games[0]
    scan_harness.set_engine_metadata(
        original.id,
        detected="renpy",
        adopted=original_engine,
        manual=manual,
    )
    scan_harness.remove_dir("GameA")
    scan_harness.scan(original_root.id, "full")

    moved_root_path = scan_harness.root_path.parent / "moved-engine-games"
    moved_game = moved_root_path / "GameA"
    moved_game.mkdir(parents=True)
    (moved_game / "Game.exe").write_bytes(b"not-a-real-pe")
    moved_root = scan_harness.add_root(mode="children", path=moved_root_path)
    summary = scan_harness.scan(moved_root.id, "full")
    candidate = summary.games[0]
    scan_harness.set_engine_metadata(
        candidate.id,
        detected="unity",
        adopted="unity",
        manual=False,
    )
    suggestion = summary.move_suggestions[0]

    confirmed = scan_harness.scanner.confirm_move(
        summary.session_id,
        suggestion.existing_game_id,
        suggestion.candidate_relative_dir,
    )

    assert confirmed.detected_engine_id == "unity"
    assert confirmed.engine_id == expected_engine
    assert confirmed.engine_confidence == pytest.approx(0.97)
    assert confirmed.engine_rules_version == "unity-test"
    assert confirmed.engine_evidence[0].code == "unity_player"


@dataclass
class ScanHarness:
    root_path: Path
    factory: ConnectionFactory
    writer: DbWriter
    library: LibraryService
    scanner: ScanService

    def add_root(
        self,
        *,
        mode: str,
        depth: int = 1,
        path: Path | None = None,
    ) -> ScanRoot:
        return self.library.add_root(
            str(path or self.root_path), mode, depth, []  # type: ignore[arg-type]
        )

    def mkdir(self, relative: str, exes: list[str] | None = None) -> Path:
        directory = self.root_path / Path(relative)
        directory.mkdir(parents=True, exist_ok=True)
        for executable in exes or []:
            (directory / executable).write_bytes(b"not-a-real-pe")
        return directory

    def remove_dir(self, relative: str) -> None:
        shutil.rmtree(self.root_path / Path(relative))

    def make_root_unavailable(self) -> None:
        self.root_path.rename(self.root_path.with_name("games-disconnected"))

    def scan(self, root_id: str, kind: str) -> ScanSummary:
        return self.scanner.scan_root(
            root_id, kind, TaskContext(Event(), lambda *_: None)  # type: ignore[arg-type]
        )

    def games(self) -> tuple[Game, ...]:
        return self.library.list_games()

    def game(self, game_id: str) -> Game:
        game = self.library.get_game(game_id)
        assert game is not None
        return game

    def set_manual_exe(self, game_id: str, relative_path: str) -> None:
        self.writer.submit(
            lambda connection: connection.execute(
                """
                UPDATE games
                SET main_exe_relpath = ?, main_exe_is_manual = 1
                WHERE id = ?
                """,
                (relative_path, game_id),
            ).rowcount
        ).result()

    def set_engine_metadata(
        self,
        game_id: str,
        *,
        detected: str,
        adopted: str,
        manual: bool,
    ) -> None:
        self.writer.submit(
            lambda connection: connection.execute(
                """
                UPDATE games
                SET detected_engine_id = ?, detected_engine_variant = NULL,
                    engine_id = ?, engine_variant = NULL, engine_is_manual = ?,
                    engine_confidence = 0.97,
                    engine_evidence_json = json(?),
                    engine_rules_version = ?
                WHERE id = ?
                """,
                (
                    detected,
                    adopted,
                    manual,
                    '[{"code":"unity_player","detail":"Unity evidence",'
                    '"path":"UnityPlayer.dll","weight":0.97}]',
                    f"{detected}-test",
                    game_id,
                ),
            ).rowcount
        ).result()

    def detected_executable(self, game_id: str) -> str | None:
        with self.factory.connect(readonly=True) as connection:
            row = connection.execute(
                "SELECT detected_main_exe_relpath FROM games WHERE id = ?", (game_id,)
            ).fetchone()
        assert row is not None
        return row[0]

    def latest_session_status(self) -> str:
        with self.factory.connect(readonly=True) as connection:
            row: sqlite3.Row | None = connection.execute(
                "SELECT status FROM scan_sessions ORDER BY started_at DESC, rowid DESC LIMIT 1"
            ).fetchone()
        assert row is not None
        return str(row[0])
