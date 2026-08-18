from pathlib import Path
from threading import Event

import pytest

from gameshelf.bridge.tasks import TaskCancelled, TaskContext
from gameshelf.engines.models import DetectionOutcome, EngineEvidence, EngineMatch
from gameshelf.library.models import Game
from gameshelf.scanning.analysis import GameAnalyzer, choose_analysis_plan
from gameshelf.scanning.analysis_cache import AnalysisCacheEntry
from gameshelf.scanning.executable_ranker import ExecutableCandidate
from gameshelf.scanning.models import DirectoryCandidate
from gameshelf.scanning.pe_metadata import PeMetadata


def _game(
    *,
    main_exe_relpath: str | None = "Game.exe",
    detected_main_exe_relpath: str | None = "Game.exe",
    main_exe_is_manual: bool = False,
) -> Game:
    return Game(
        id="game-1",
        scan_root_id="root-1",
        relative_dir="Game",
        install_path_key="game-key",
        title="Game",
        detected_title="Game",
        status="installed",
        detected_engine_id="old-engine",
        detected_engine_variant="old-variant",
        engine_id="manual-engine" if main_exe_is_manual else "old-engine",
        engine_variant=None,
        engine_is_manual=main_exe_is_manual,
        engine_confidence=0.8,
        engine_evidence=(EngineEvidence("old", "old evidence", 0.8),),
        engine_rules_version="old-rule",
        main_exe_relpath=main_exe_relpath,
        main_exe_is_manual=main_exe_is_manual,
        working_dir_relpath=None,
        launch_args=(),
        environment={},
        exe_arch="x86",
        cover_original_relpath=None,
        cover_thumb_relpath=None,
        cover_revision=0,
        last_launched_at=None,
        missing_since=None,
        detected_main_exe_relpath=detected_main_exe_relpath,
    )


def _cache(
    executable: Path,
    *,
    relative_path: str = "Game.exe",
    ranker_version: str = "ranker-1",
    engine_version: str = "engine-1",
) -> AnalysisCacheEntry:
    info = executable.stat()
    return AnalysisCacheEntry(
        game_id="game-1",
        executable_relpath=relative_path,
        file_size=info.st_size,
        modified_time_ns=info.st_mtime_ns,
        ranker_rules_version=ranker_version,
        engine_rules_version=engine_version,
        analyzed_at="now",
    )


def _context() -> TaskContext:
    return TaskContext(Event(), lambda *_: None)


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("new", "full"),
        ("missing_cache", "full"),
        ("unchanged", "reuse"),
        ("engine_rules_changed", "refresh_engine"),
        ("executable_changed", "refresh_executable"),
        ("ranker_rules_changed", "full"),
        ("cache_path_changed", "full"),
        ("executable_missing", "full"),
        ("executable_not_file", "full"),
    ],
)
def test_choose_analysis_plan_uses_the_minimum_safe_refresh(
    tmp_path: Path,
    case: str,
    expected: str,
) -> None:
    game_dir = tmp_path / "Game"
    game_dir.mkdir()
    executable = game_dir / "Game.exe"
    executable.write_bytes(b"MZ")
    existing: Game | None = _game()
    cache: AnalysisCacheEntry | None = _cache(executable)
    ranker_version = "ranker-1"
    engine_version = "engine-1"

    if case == "new":
        existing = None
    elif case == "missing_cache":
        cache = None
    elif case == "engine_rules_changed":
        engine_version = "engine-2"
    elif case == "executable_changed":
        executable.write_bytes(b"MZ changed")
    elif case == "ranker_rules_changed":
        ranker_version = "ranker-2"
    elif case == "cache_path_changed":
        cache = _cache(executable, relative_path="Other.exe")
    elif case == "executable_missing":
        executable.unlink()
    elif case == "executable_not_file":
        executable.unlink()
        executable.mkdir()

    plan = choose_analysis_plan(
        game_dir,
        existing,
        cache,
        ranker_rules_version=ranker_version,
        engine_rules_version=engine_version,
    )

    assert plan.kind == expected


class _RecordingDetector:
    cache_version = "engine-1"

    def __init__(self) -> None:
        self.calls: list[tuple[Path, Path | None]] = []

    def detect(self, game_dir: Path, executable: Path | None) -> DetectionOutcome:
        self.calls.append((game_dir, executable))
        return DetectionOutcome(
            EngineMatch(
                "new-engine",
                "new-variant",
                0.9,
                (EngineEvidence("new", "new evidence", 0.9),),
                "engine-rule-2",
            ),
            (),
            False,
        )


class _AnalyzerHarness:
    def __init__(self, game_dir: Path, *, ranked: bool = True) -> None:
        self.game_dir = game_dir
        self.detector = _RecordingDetector()
        self.rank_calls: list[Path] = []
        self.pe_calls: list[Path] = []
        self.ranked = ranked
        self.analyzer = GameAnalyzer(
            self.detector,
            ranker=self.rank,
            pe_reader=self.read_pe,
            ranker_rules_version="ranker-1",
        )

    def rank(self, game_dir: Path) -> tuple[ExecutableCandidate, ...]:
        self.rank_calls.append(game_dir)
        if not self.ranked:
            return ()
        return (ExecutableCandidate("Auto.exe", 100, "x64", ("best",)),)

    def read_pe(self, executable: Path) -> PeMetadata:
        self.pe_calls.append(executable)
        return PeMetadata("", "", "", "x64")

    def candidate(self) -> DirectoryCandidate:
        return DirectoryCandidate(self.game_dir, "Game", 1, "direct_child")


def test_reuse_calls_no_expensive_boundary_and_preserves_automatic_fields(
    tmp_path: Path,
) -> None:
    game_dir = tmp_path / "Game"
    game_dir.mkdir()
    manual = game_dir / "Manual.exe"
    manual.write_bytes(b"MZ")
    harness = _AnalyzerHarness(game_dir)
    existing = _game(
        main_exe_relpath="Manual.exe",
        detected_main_exe_relpath="Auto.exe",
        main_exe_is_manual=True,
    )

    result = harness.analyzer.analyze(
        harness.candidate(), existing, _cache(manual, relative_path="Manual.exe"), _context()
    )

    assert result.analysis_kind == "reuse"
    assert harness.rank_calls == []
    assert harness.pe_calls == []
    assert harness.detector.calls == []
    assert result.payload["mainExeRelpath"] == "Auto.exe"
    assert result.payload["detectedEngineId"] == "old-engine"
    assert result.pending_cache is not None
    assert result.pending_cache.executable_relpath == "Manual.exe"


def test_engine_rule_change_only_runs_engine_detection(tmp_path: Path) -> None:
    game_dir = tmp_path / "Game"
    game_dir.mkdir()
    executable = game_dir / "Game.exe"
    executable.write_bytes(b"MZ")
    harness = _AnalyzerHarness(game_dir)
    stale = _cache(executable, engine_version="engine-0")

    result = harness.analyzer.analyze(
        harness.candidate(), _game(), stale, _context()
    )

    assert result.analysis_kind == "refresh_engine"
    assert harness.rank_calls == []
    assert harness.pe_calls == []
    assert harness.detector.calls == [(game_dir, executable)]
    assert result.payload["detectedEngineId"] == "new-engine"


def test_changed_executable_refreshes_metadata_without_reranking(tmp_path: Path) -> None:
    game_dir = tmp_path / "Game"
    game_dir.mkdir()
    executable = game_dir / "Game.exe"
    executable.write_bytes(b"MZ")
    stale = _cache(executable)
    executable.write_bytes(b"MZ changed")
    harness = _AnalyzerHarness(game_dir)

    result = harness.analyzer.analyze(
        harness.candidate(), _game(), stale, _context()
    )

    assert result.analysis_kind == "refresh_executable"
    assert harness.rank_calls == []
    assert harness.pe_calls == [executable]
    assert harness.detector.calls == [(game_dir, executable)]
    assert result.payload["exeArch"] == "x64"


def test_full_analysis_ranks_automatic_exe_but_detects_with_manual_exe(
    tmp_path: Path,
) -> None:
    game_dir = tmp_path / "Game"
    game_dir.mkdir()
    automatic = game_dir / "Auto.exe"
    manual = game_dir / "Manual.exe"
    automatic.write_bytes(b"MZ auto")
    manual.write_bytes(b"MZ manual")
    harness = _AnalyzerHarness(game_dir)
    existing = _game(
        main_exe_relpath="Manual.exe",
        detected_main_exe_relpath="OldAuto.exe",
        main_exe_is_manual=True,
    )

    result = harness.analyzer.analyze(
        harness.candidate(), existing, None, _context()
    )

    assert result.analysis_kind == "full"
    assert harness.rank_calls == [game_dir]
    assert harness.pe_calls == []
    assert harness.detector.calls == [(game_dir, manual)]
    assert result.payload["mainExeRelpath"] == "Auto.exe"
    assert result.pending_cache is not None
    assert result.pending_cache.executable_relpath == "Manual.exe"


def test_full_analysis_without_an_executable_does_not_create_cache(
    tmp_path: Path,
) -> None:
    game_dir = tmp_path / "Game"
    game_dir.mkdir()
    harness = _AnalyzerHarness(game_dir, ranked=False)

    result = harness.analyzer.analyze(
        harness.candidate(), None, None, _context()
    )

    assert result.analysis_kind == "full"
    assert harness.detector.calls == [(game_dir, None)]
    assert result.pending_cache is None


def test_full_analysis_stops_before_detection_when_ranking_cancels(
    tmp_path: Path,
) -> None:
    game_dir = tmp_path / "Game"
    game_dir.mkdir()
    (game_dir / "Auto.exe").write_bytes(b"MZ")
    detector = _RecordingDetector()
    cancelled = Event()

    def rank(_: Path) -> tuple[ExecutableCandidate, ...]:
        cancelled.set()
        return (ExecutableCandidate("Auto.exe", 100, "x64", ("best",)),)

    analyzer = GameAnalyzer(detector, ranker=rank, ranker_rules_version="ranker-1")
    context = TaskContext(cancelled, lambda *_: None)

    with pytest.raises(TaskCancelled):
        analyzer.analyze(
            DirectoryCandidate(game_dir, "Game", 1, "direct_child"),
            None,
            None,
            context,
        )

    assert detector.calls == []
