from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from threading import Thread

import pytest

from gamesave_scout.db.connection import ConnectionFactory
from gamesave_scout.db.migrator import Migrator
from gamesave_scout.db.writer import DbWriter
from gamesave_scout.library.launcher import LaunchReceipt
from gamesave_scout.platform.windows.known_folders import KnownFolders
from gamesave_scout.saves.guided_events import RawFileChange
from gamesave_scout.saves.guided_models import (
    GuidedSavePreview,
    GuidedScopeOption,
)
from gamesave_scout.saves.guided_registry import RegistrySnapshot
from gamesave_scout.saves.guided_repository import GuidedSaveRepository
from gamesave_scout.saves.guided_scanner import MetadataScanResult
from gamesave_scout.saves.guided_scoring import GuidedScoringContext
from gamesave_scout.saves.guided_service import GuidedSaveError, GuidedSaveSessionService
from gamesave_scout.saves.templates import PathTemplateResolver


@dataclass
class ServiceHarness:
    service: GuidedSaveSessionService
    repository: GuidedSaveRepository
    writer: DbWriter
    scheduler: FakeScheduler
    watcher: FakeWatcher
    processes: FakeProcessTracker
    scanner: FakeScanner
    scope_builder: FakeScopeBuilder
    order: list[str]
    game_id: str
    save_dir: Path

    def start(self):  # type: ignore[no-untyped-def]
        return self.service.start(self.game_id, ("default:game",), ())


@pytest.fixture
def guided_service(tmp_path: Path) -> Iterator[ServiceHarness]:
    factory = ConnectionFactory(tmp_path / "data" / "library.db")
    Migrator(factory, tmp_path / "backups").migrate()
    game_dir = tmp_path / "Games" / "Alice"
    game_dir.mkdir(parents=True)
    with factory.connect() as connection:
        _insert_game(connection, "game-1", game_dir)
        connection.commit()
    writer = DbWriter(factory)
    writer.start()
    repository = GuidedSaveRepository(factory, writer)
    scope = GuidedScopeOption(
        id="default:game",
        label="游戏安装目录",
        display_path=str(game_dir),
        path_template="<game>",
        source="game",
        default_selected=True,
        available=True,
    )
    scope_builder = FakeScopeBuilder(
        GuidedSavePreview("game-1", "Alice", str(game_dir / "Alice.exe"), (scope,), ())
    )
    order: list[str] = []
    scheduler = FakeScheduler()
    watcher = FakeWatcher()
    processes = FakeProcessTracker(order)
    launcher = FakeLauncher(order)
    folders = _known_folders(tmp_path)
    resolver = PathTemplateResolver(folders)
    save_dir = game_dir / "Saves"
    clock = FakeClock()
    exits: list[str] = []

    def scoring_context(
        _game_id: str,
        _scopes: tuple[GuidedScopeOption, ...],
        overflowed: tuple[str, ...],
        truncated: tuple[str, ...],
    ) -> GuidedScoringContext:
        return GuidedScoringContext(
            resolver=resolver,
            game_dir=game_dir,
            trusted_root_keys=(),
            overflowed_root_keys=overflowed,
            truncated_root_keys=truncated,
        )

    scanner = FakeScanner()
    service = GuidedSaveSessionService(
        repository=repository,
        scope_builder=scope_builder,
        registry_reader=FakeRegistryReader(),
        watcher=watcher,
        launcher=launcher,
        process_tracker=processes,
        scanner=scanner,
        scoring_context_factory=scoring_context,
        scheduler=scheduler,
        utc_now=clock.utc_now,
        monotonic_ns=clock.monotonic_ns,
        wall_time_ns=clock.wall_time_ns,
        submit_analysis=lambda operation: operation(),
        exit_callback=lambda: exits.append("exit"),
    )
    watcher.order = order
    try:
        yield ServiceHarness(
            service,
            repository,
            writer,
            scheduler,
            watcher,
            processes,
            scanner,
            scope_builder,
            order,
            "game-1",
            save_dir,
        )
    finally:
        service.close()
        writer.close()


def test_start_arms_all_watchers_before_launch(guided_service: ServiceHarness) -> None:
    session = guided_service.start()

    assert session.status == "monitoring"
    assert guided_service.order == ["watch", "launch", "process"]
    assert guided_service.scheduler.delays == [1800.0]


def test_mark_saved_schedules_one_three_second_settle(
    guided_service: ServiceHarness,
) -> None:
    session = guided_service.start()
    guided_service.save_dir.mkdir()
    sink = guided_service.watcher.sinks[0]
    sink.on_change(
        RawFileChange(
            "modified",
            guided_service.save_dir / "slot1.sav",
            None,
            2_000_000_000,
            root=guided_service.save_dir.parent,
        )
    )

    first = guided_service.service.mark_saved(session.id)
    second = guided_service.service.mark_saved(session.id)

    assert first.status == second.status == "settling"
    assert guided_service.scheduler.delays.count(3.0) == 1
    guided_service.scheduler.run_delay(3.0)
    completed = guided_service.repository.get_session(session.id)
    assert completed is not None
    assert completed.status == "completed"
    assert len(guided_service.repository.list_discoveries(session.id)) == 1


def test_second_session_is_rejected_and_cancel_cleans_resources(
    guided_service: ServiceHarness,
) -> None:
    session = guided_service.start()

    with pytest.raises(GuidedSaveError) as captured:
        guided_service.start()
    cancelled = guided_service.service.cancel(session.id)

    assert captured.value.code == "guided_session_active"
    assert cancelled.status == "cancelled"
    assert guided_service.watcher.handles[0].stops == 1
    assert guided_service.processes.handle.stops == 1


def test_process_tracking_degrade_does_not_end_session(
    guided_service: ServiceHarness,
) -> None:
    session = guided_service.start()

    guided_service.processes.sink.on_tracking_degraded("launcher_detached")

    current = guided_service.repository.get_session(session.id)
    assert current is not None
    assert current.status == "monitoring"
    assert current.process_tracking_degraded is True


def test_reliable_process_exit_stops_and_analyzes(guided_service: ServiceHarness) -> None:
    session = guided_service.start()

    guided_service.processes.sink.on_tree_exit()

    completed = guided_service.repository.get_session(session.id)
    assert completed is not None
    assert completed.status == "completed"


def test_manual_stop_enters_settling_before_async_analysis(
    guided_service: ServiceHarness,
) -> None:
    pending: list[Callable[[], None]] = []
    guided_service.service._submit_analysis = pending.append  # type: ignore[attr-defined]
    session = guided_service.start()

    settling = guided_service.service.stop_and_analyze(session.id)

    assert settling.status == "settling"
    assert settling.save_marked_at is None
    assert len(pending) == 1
    pending[0]()
    assert guided_service.repository.get_session(session.id).status == "completed"  # type: ignore[union-attr]


def test_overflow_scan_uses_wall_clock_window_not_monotonic_ticks(
    guided_service: ServiceHarness,
) -> None:
    session = guided_service.start()
    guided_service.watcher.sinks[0].on_overflow(guided_service.save_dir.parent)

    guided_service.service.stop_and_analyze(session.id)

    assert len(guided_service.scanner.windows) == 1
    started_ns, finished_ns = guided_service.scanner.windows[0]
    assert started_ns >= 1_700_000_000_000_000_000
    assert finished_ns >= started_ns


def test_failed_watch_root_is_reported_as_incomplete(
    guided_service: ServiceHarness,
) -> None:
    session = guided_service.start()
    failed_root = guided_service.save_dir.parent
    guided_service.watcher.sinks[0].on_failure(failed_root, "win32_error_3")

    guided_service.service.stop_and_analyze(session.id)

    completed = guided_service.repository.get_session(session.id)
    assert completed is not None
    assert completed.status == "completed"
    assert completed.truncated_scopes == (str(failed_root),)


def test_close_request_requires_explicit_resolution(guided_service: ServiceHarness) -> None:
    session = guided_service.start()

    assert guided_service.service.request_close() is False
    assert guided_service.service.close_requested is True
    guided_service.service.resolve_close("return")
    assert guided_service.service.close_requested is False
    guided_service.service.cancel(session.id)
    assert guided_service.service.request_close() is True


def test_cancel_and_exit_releases_lock_before_exit_callback(
    guided_service: ServiceHarness,
) -> None:
    session = guided_service.start()
    callback_observations: list[bool] = []
    close_results: list[bool] = []
    workers: list[Thread] = []

    def exit_callback() -> None:
        worker = Thread(
            target=lambda: close_results.append(
                guided_service.service.request_close()
            )
        )
        workers.append(worker)
        worker.start()
        worker.join(0.1)
        callback_observations.append(worker.is_alive())

    guided_service.service.set_exit_callback(exit_callback)

    guided_service.service.resolve_close("cancel_and_exit")
    for worker in workers:
        worker.join(1.0)

    assert guided_service.repository.get_session(session.id).status == "cancelled"  # type: ignore[union-attr]
    assert callback_observations == [False]
    assert close_results == [True]


def test_launch_failure_marks_session_failed_and_stops_watcher(
    guided_service: ServiceHarness,
) -> None:
    guided_service.service._launcher = FailingLauncher()  # type: ignore[attr-defined]

    with pytest.raises(GuidedSaveError) as captured:
        guided_service.start()

    latest = guided_service.repository.get_session(
        guided_service.repository.active().id  # type: ignore[union-attr]
    ) if guided_service.repository.active() is not None else None
    assert captured.value.code == "guided_start_failed"
    assert latest is None
    assert guided_service.watcher.handles[0].stops == 1


def test_registry_baseline_failure_does_not_leave_active_session(
    guided_service: ServiceHarness,
) -> None:
    guided_service.service._registry_reader = FailingRegistryReader()  # type: ignore[attr-defined]

    with pytest.raises(GuidedSaveError) as captured:
        guided_service.start()

    assert captured.value.code == "guided_start_failed"
    assert guided_service.repository.active() is None


def test_second_watcher_start_failure_stops_first_and_never_launches_game(
    guided_service: ServiceHarness,
) -> None:
    first = guided_service.scope_builder._preview.scopes[0]
    second_root = guided_service.save_dir.parent / "Other"
    second_root.mkdir()
    second = GuidedScopeOption(
        id="extra:other",
        label="额外目录",
        display_path=str(second_root),
        path_template="<game>\\Other",
        source="extra",
        default_selected=True,
        available=True,
    )
    guided_service.scope_builder._preview = GuidedSavePreview(
        "game-1", "Alice", str(guided_service.save_dir.parent / "Alice.exe"),
        (first, second), (),
    )
    watcher = FailingSecondWatcher(guided_service.order)
    guided_service.service._watcher = watcher  # type: ignore[attr-defined]

    with pytest.raises(GuidedSaveError) as captured:
        guided_service.service.start("game-1", (first.id, second.id), ())

    assert captured.value.code == "guided_start_failed"
    assert "launch" not in guided_service.order
    assert watcher.handles[0].stops == 1
    assert guided_service.repository.active() is None


class FakeScopeBuilder:
    def __init__(self, preview: GuidedSavePreview) -> None:
        self._preview = preview

    def preview(self, _game_id: str) -> GuidedSavePreview:
        return self._preview

    def resolve_selected(
        self,
        _game_id: str,
        _selected_scope_ids: tuple[str, ...],
        _additional_directories: tuple[str, ...],
    ) -> tuple[GuidedScopeOption, ...]:
        return self._preview.scopes


class FakeRegistryReader:
    def snapshot(self, _keys: tuple[str, ...]) -> RegistrySnapshot:
        return RegistrySnapshot(())


class FailingRegistryReader:
    def snapshot(self, _keys: tuple[str, ...]) -> RegistrySnapshot:
        raise OSError("registry unavailable")


class FakeWatchHandle:
    def __init__(self) -> None:
        self.stops = 0

    def stop(self) -> None:
        self.stops += 1


class FakeWatcher:
    def __init__(self) -> None:
        self.order: list[str] = []
        self.handles: list[FakeWatchHandle] = []
        self.sinks: list[object] = []

    def start(self, _root: Path, sink: object) -> FakeWatchHandle:
        self.order.append("watch")
        self.sinks.append(sink)
        handle = FakeWatchHandle()
        self.handles.append(handle)
        return handle


class FailingSecondWatcher(FakeWatcher):
    def __init__(self, order: list[str]) -> None:
        super().__init__()
        self.order = order

    def start(self, root: Path, sink: object) -> FakeWatchHandle:
        if self.handles:
            self.order.append("watch")
            raise OSError(f"cannot watch {root}")
        return super().start(root, sink)


class FakeProcessHandle:
    def __init__(self) -> None:
        self.stops = 0

    def stop(self) -> None:
        self.stops += 1


class FakeProcessTracker:
    def __init__(self, order: list[str]) -> None:
        self._order = order
        self.handle = FakeProcessHandle()
        self.sink: object

    def start(self, _pid: int, sink: object) -> FakeProcessHandle:
        self._order.append("process")
        self.sink = sink
        return self.handle


class FakeScanner:
    def __init__(self) -> None:
        self.windows: list[tuple[int, int]] = []

    def scan(
        self, root: Path, *, started_ns: int, finished_ns: int
    ) -> MetadataScanResult:
        self.windows.append((started_ns, finished_ns))
        return MetadataScanResult(str(root), (), 0, 0, 0, None)


class FakeLauncher:
    def __init__(self, order: list[str]) -> None:
        self._order = order

    def launch(self, game_id: str) -> LaunchReceipt:
        self._order.append("launch")
        return LaunchReceipt(game_id, 123, "2026-08-15T00:00:01+00:00")


class FailingLauncher:
    def launch(self, _game_id: str) -> LaunchReceipt:
        raise OSError("launch failed")


class FakeTimer:
    def __init__(self, delay: float, callback: Callable[[], None]) -> None:
        self.delay = delay
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class FakeScheduler:
    def __init__(self) -> None:
        self.timers: list[FakeTimer] = []

    @property
    def delays(self) -> list[float]:
        return [timer.delay for timer in self.timers]

    def call_later(self, delay: float, callback: Callable[[], None]) -> FakeTimer:
        timer = FakeTimer(delay, callback)
        self.timers.append(timer)
        return timer

    def run_delay(self, delay: float) -> None:
        timer = next(
            timer for timer in self.timers if timer.delay == delay and not timer.cancelled
        )
        timer.callback()


class FakeClock:
    def __init__(self) -> None:
        self._ticks = 0

    def utc_now(self) -> str:
        self._ticks += 1
        return f"2026-08-15T00:00:{self._ticks:02d}+00:00"

    def monotonic_ns(self) -> int:
        self._ticks += 1
        return self._ticks * 1_000_000_000

    def wall_time_ns(self) -> int:
        self._ticks += 1
        return 1_700_000_000_000_000_000 + self._ticks * 1_000_000_000


def _insert_game(connection: sqlite3.Connection, game_id: str, game_dir: Path) -> None:
    connection.execute(
        """
        INSERT INTO games(
            id, install_path_key, title, status, main_exe_relpath, added_at, updated_at
        ) VALUES (?, ?, 'Alice', 'save_only', 'Alice.exe',
                  '2026-08-15T00:00:00+00:00', '2026-08-15T00:00:00+00:00')
        """,
        (game_id, str(game_dir)),
    )


def _known_folders(tmp_path: Path) -> KnownFolders:
    home = tmp_path / "Profile"
    return KnownFolders(
        home=home,
        app_data=home / "AppData" / "Roaming",
        local_app_data=home / "AppData" / "Local",
        local_app_data_low=home / "AppData" / "LocalLow",
        documents=home / "Documents",
        saved_games=home / "Saved Games",
        program_data=tmp_path / "ProgramData",
        public=tmp_path / "Public",
        windows=tmp_path / "Windows",
    )
