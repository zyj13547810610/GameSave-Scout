import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Thread

import pytest

from gameshelf.bridge.tasks import TaskCancelled, TaskContext
from gameshelf.db.connection import ConnectionFactory
from gameshelf.db.migrator import Migrator
from gameshelf.db.writer import DbWriter
from gameshelf.library.models import Game, ScanRoot
from gameshelf.library.repository import LibraryRepository
from gameshelf.library.service import LibraryService
from gameshelf.scanning.analysis_cache import PendingAnalysisCache, upsert_analysis_cache
from gameshelf.scanning.analysis_pool import ScanAnalysisPool
from gameshelf.scanning.executable_ranker import RANKER_RULES_VERSION
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


def test_scan_splits_only_explicit_version_suffixes(
    scan_harness: "ScanHarness",
) -> None:
    root = scan_harness.add_root(mode="children")
    scan_harness.mkdir("AoiChan.v1.0.8")
    scan_harness.mkdir("Need for Speed 21 Heat")

    scan_harness.scan(root.id, "full")

    games = {game.relative_dir: game for game in scan_harness.games()}
    explicit = games["AoiChan.v1.0.8"]
    ambiguous = games["Need for Speed 21 Heat"]
    assert explicit.title == "AoiChan"
    assert explicit.detected_title == "AoiChan"
    assert explicit.version == "v1.0.8"
    assert explicit.detected_version == "v1.0.8"
    assert ambiguous.title == "Need for Speed 21 Heat"
    assert ambiguous.version is None


def test_rescan_refreshes_detection_without_overwriting_manual_empty_version(
    scan_harness: "ScanHarness",
) -> None:
    root = scan_harness.add_root(mode="children")
    scan_harness.mkdir("AoiChan.v1.0.8")
    game = scan_harness.scan(root.id, "full").games[0]
    scan_harness.library.set_game_metadata(game.id, "自定义标题", None)

    scan_harness.scan(root.id, "full")

    refreshed = scan_harness.game(game.id)
    assert refreshed.title == "自定义标题"
    assert refreshed.version is None
    assert refreshed.detected_title == "AoiChan"
    assert refreshed.detected_version == "v1.0.8"


def test_reconcile_uses_latest_exclusions_after_game_is_removed_mid_scan(
    scan_harness: "ScanHarness",
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = scan_harness.add_root(mode="children")
    scan_harness.mkdir("GameA")
    game = scan_harness.library.create_game_for_test(root.id, "GameA", "GameA")
    observations_staged = Event()
    release_reconcile = Event()
    scan_errors: list[BaseException] = []
    original_stage_batch = scan_harness.scanner._stage_batch  # noqa: SLF001

    def block_after_staging(session_id: str, batch: list[tuple[str, str]]) -> None:
        original_stage_batch(session_id, batch)
        observations_staged.set()
        assert release_reconcile.wait(timeout=2)

    monkeypatch.setattr(scan_harness.scanner, "_stage_batch", block_after_staging)

    def run_scan() -> None:
        try:
            scan_harness.scan(root.id, "full")
        except BaseException as error:
            scan_errors.append(error)

    scan_thread = Thread(target=run_scan)
    scan_thread.start()
    assert observations_staged.wait(timeout=2)

    scan_harness.library.remove_game_and_exclude(game.id)
    release_reconcile.set()
    scan_thread.join(timeout=3)

    assert not scan_thread.is_alive()
    assert scan_errors == []
    assert scan_harness.games() == ()
    assert scan_harness.library.list_roots()[0].exclusions == ("GameA",)


def test_scan_reports_structured_stages_and_completion_summary(
    scan_harness: "ScanHarness",
) -> None:
    root = scan_harness.add_root(mode="children")
    scan_harness.mkdir("GameA", exes=["GameA.exe"])
    reports: list[dict[str, object]] = []

    summary = scan_harness.scanner.scan_root(
        root.id,
        "full",
        TaskContext(
            Event(),
            lambda _completed, _total, _message, details: reports.append(details),
        ),
    )

    stages = [report["stage"] for report in reports]
    assert stages[0] == "preparing"
    assert "discovering" in stages
    assert stages[-2:] == ["reconciling", "completed"]
    final = dict(reports[-1])
    elapsed = final.pop("elapsedSeconds")
    assert isinstance(elapsed, float)
    assert elapsed >= 0
    assert final == {
        "stage": "completed",
        "currentPath": "GameA",
        "directoriesScanned": 2,
        "discovered": 1,
        "inaccessibleDirectories": 0,
        "warnings": 0,
        "added": 1,
        "updated": 0,
        "missing": 0,
    }
    assert summary.discovered == 1


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


def test_quick_marks_only_a_confirmed_missing_game_and_restores_it(
    scan_harness: "ScanHarness",
) -> None:
    root = scan_harness.add_root(mode="children")
    scan_harness.mkdir("GameA")
    scan_harness.mkdir("GameB")
    scan_harness.scan(root.id, "full")
    games = {game.relative_dir: game for game in scan_harness.games()}

    scan_harness.remove_dir("GameA")
    missing = scan_harness.scan(root.id, "quick")

    assert missing.checked == 2
    assert missing.missing == 1
    assert scan_harness.game(games["GameA"].id).status == "missing"
    assert scan_harness.game(games["GameB"].id).status == "installed"

    scan_harness.mkdir("GameA")
    restored = scan_harness.scan(root.id, "quick")

    assert restored.checked == 2
    assert scan_harness.game(games["GameA"].id).status == "installed"


def test_quick_unknown_game_path_keeps_status_and_reports_warning(
    scan_harness: "ScanHarness",
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = scan_harness.add_root(mode="children")
    game_dir = scan_harness.mkdir("GameA")
    game = scan_harness.scan(root.id, "full").games[0]
    from gameshelf.scanning import service as scanning_service

    original_probe = scanning_service._probe_directory

    def probe(path: Path):
        if path == game_dir:
            return scanning_service.PathProbe("unknown", "permission denied")
        return original_probe(path)

    monkeypatch.setattr(scanning_service, "_probe_directory", probe)

    summary = scan_harness.scan(root.id, "quick")

    assert summary.checked == 1
    assert summary.warnings == 1
    assert scan_harness.game(game.id).status == "installed"


def test_disabled_root_is_rejected_before_a_scan_session_is_created(
    scan_harness: "ScanHarness",
) -> None:
    root = scan_harness.add_root(mode="children")
    scan_harness.library.update_root(
        root.id,
        enabled=False,
        scan_mode=root.scan_mode,
        max_depth=root.max_depth,
        exclusions=root.exclusions,
    )
    before = scan_harness.session_count()

    with pytest.raises(ValueError, match="未参与扫描"):
        scan_harness.scan(root.id, "quick")
    with pytest.raises(ValueError, match="未参与扫描"):
        scan_harness.scan(root.id, "full")

    assert scan_harness.session_count() == before


def test_quick_reuses_a_matching_persistent_analysis_cache(
    scan_harness: "ScanHarness",
) -> None:
    root = scan_harness.add_root(mode="children")
    game_dir = scan_harness.mkdir("GameA", exes=["GameA.exe"])
    game = scan_harness.scan(root.id, "full").games[0]
    executable = game_dir / "GameA.exe"
    info = executable.stat()
    with scan_harness.factory.connect() as connection:
        upsert_analysis_cache(
            connection,
            game.id,
            PendingAnalysisCache(
                "GameA.exe",
                info.st_size,
                info.st_mtime_ns,
                RANKER_RULES_VERSION,
                "none",
            ),
            "now",
        )
    pool = ScanAnalysisPool(lambda: 2)
    scanner = ScanService(
        LibraryRepository(scan_harness.factory),
        scan_harness.writer,
        analysis_pool=pool,
    )
    try:
        summary = scanner.scan_root(root.id, "quick", TaskContext(Event(), lambda *_: None))
    finally:
        pool.close()

    assert summary.checked == 1
    assert summary.cache_hits == 1
    assert summary.reanalyzed == 0
    assert summary.full_analyses == 0


def test_manual_executable_survives_new_auto_recommendation(
    scan_harness: "ScanHarness",
) -> None:
    root = scan_harness.add_root(mode="children")
    scan_harness.mkdir("GameA", exes=["A.exe", "Better.exe"])
    game = scan_harness.scan(root.id, "full").games[0]
    scan_harness.set_manual_exe(game.id, "A.exe", architecture="x64")

    scan_harness.scan(root.id, "full")

    refreshed = scan_harness.game(game.id)
    assert refreshed.main_exe_relpath == "A.exe"
    assert refreshed.exe_arch == "x64"
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
    scan_harness.set_exe_arch(summary.games[0].id, "x64")
    suggestion = summary.move_suggestions[0]

    confirmed = scan_harness.scanner.confirm_move(
        summary.session_id,
        suggestion.existing_game_id,
        suggestion.candidate_relative_dir,
    )

    assert confirmed.id == original.id
    assert confirmed.scan_root_id == moved_root.id
    assert confirmed.status == "installed"
    assert confirmed.exe_arch == "x64"
    assert scan_harness.games() == (confirmed,)


def test_confirmed_move_preserves_manual_metadata_and_refreshes_detection(
    scan_harness: "ScanHarness",
) -> None:
    original_root = scan_harness.add_root(mode="children")
    scan_harness.mkdir("GameA.v1.0", exes=["Game.exe"])
    original = scan_harness.scan(original_root.id, "full").games[0]
    scan_harness.library.set_game_metadata(original.id, "GameA!", "manual-v")
    scan_harness.remove_dir("GameA.v1.0")
    scan_harness.scan(original_root.id, "full")

    moved_root_path = scan_harness.root_path.parent / "moved-versioned-games"
    moved_game = moved_root_path / "GameA.v2.0"
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

    with scan_harness.factory.connect(readonly=True) as connection:
        flags = connection.execute(
            "SELECT title_is_manual, version_is_manual FROM games WHERE id = ?",
            (confirmed.id,),
        ).fetchone()
    assert confirmed.id == original.id
    assert confirmed.relative_dir == "GameA.v2.0"
    assert confirmed.title == "GameA!"
    assert confirmed.version == "manual-v"
    assert confirmed.detected_title == "GameA"
    assert confirmed.detected_version == "v2.0"
    assert (flags["title_is_manual"], flags["version_is_manual"]) == (1, 1)


def test_confirmed_move_preserves_architecture_for_a_manual_executable(
    scan_harness: "ScanHarness",
) -> None:
    original_root = scan_harness.add_root(mode="children")
    scan_harness.mkdir("GameA", exes=["Game.exe"])
    original = scan_harness.scan(original_root.id, "full").games[0]
    scan_harness.set_manual_exe(original.id, "Game.exe", architecture="x86")
    scan_harness.remove_dir("GameA")
    scan_harness.scan(original_root.id, "full")

    moved_root_path = scan_harness.root_path.parent / "moved-manual-game"
    moved_game = moved_root_path / "GameA"
    moved_game.mkdir(parents=True)
    (moved_game / "Game.exe").write_bytes(b"MZ")
    moved_root = scan_harness.add_root(mode="children", path=moved_root_path)
    summary = scan_harness.scan(moved_root.id, "full")
    scan_harness.set_exe_arch(summary.games[0].id, "x64")
    suggestion = summary.move_suggestions[0]

    confirmed = scan_harness.scanner.confirm_move(
        summary.session_id,
        suggestion.existing_game_id,
        suggestion.candidate_relative_dir,
    )

    assert confirmed.main_exe_relpath == "Game.exe"
    assert confirmed.main_exe_is_manual is True
    assert confirmed.exe_arch == "x86"


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


def test_confirmed_move_keeps_ambiguous_candidates_despite_unrelated_diagnostic(
    scan_harness: "ScanHarness",
) -> None:
    original_root = scan_harness.add_root(mode="children")
    scan_harness.mkdir("GameA", exes=["Game.exe"])
    original = scan_harness.scan(original_root.id, "full").games[0]
    scan_harness.set_engine_metadata(
        original.id,
        detected="renpy",
        adopted="renpy",
        manual=False,
    )
    scan_harness.remove_dir("GameA")
    scan_harness.scan(original_root.id, "full")

    moved_root_path = scan_harness.root_path.parent / "moved-ambiguous-games"
    moved_game = moved_root_path / "GameA"
    moved_game.mkdir(parents=True)
    (moved_game / "Game.exe").write_bytes(b"not-a-real-pe")
    moved_root = scan_harness.add_root(mode="children", path=moved_root_path)
    summary = scan_harness.scan(moved_root.id, "full")
    candidate = summary.games[0]
    scan_harness.set_ambiguous_engine_metadata(candidate.id)
    suggestion = summary.move_suggestions[0]

    confirmed = scan_harness.scanner.confirm_move(
        summary.session_id,
        suggestion.existing_game_id,
        suggestion.candidate_relative_dir,
    )

    assert confirmed.detected_engine_id is None
    assert confirmed.engine_id is None
    assert confirmed.engine_confidence == pytest.approx(0.82)
    assert [item.code for item in confirmed.engine_evidence] == [
        "candidate:unity",
        "candidate:renpy",
        "detector_error",
    ]


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

    def set_manual_exe(
        self, game_id: str, relative_path: str, *, architecture: str = "unknown"
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

    def set_exe_arch(self, game_id: str, architecture: str) -> None:
        self.writer.submit(
            lambda connection: connection.execute(
                "UPDATE games SET exe_arch = ? WHERE id = ?",
                (architecture, game_id),
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

    def set_ambiguous_engine_metadata(self, game_id: str) -> None:
        self.writer.submit(
            lambda connection: connection.execute(
                """
                UPDATE games
                SET detected_engine_id = NULL, detected_engine_variant = NULL,
                    engine_id = NULL, engine_variant = NULL, engine_is_manual = 0,
                    engine_confidence = 0.82,
                    engine_evidence_json = json(?),
                    engine_rules_version = 'ambiguous-test'
                WHERE id = ?
                """,
                (
                    '[{"code":"candidate:unity","detail":"Unity",'
                    '"path":null,"weight":0.82},'
                    '{"code":"candidate:renpy","detail":"RenPy",'
                    '"path":null,"weight":0.78},'
                    '{"code":"detector_error","detail":"OSError",'
                    '"path":null,"weight":0.0}]',
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

    def session_count(self) -> int:
        with self.factory.connect(readonly=True) as connection:
            return int(connection.execute("SELECT COUNT(*) FROM scan_sessions").fetchone()[0])
