from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from pathlib import Path

from gameshelf.db.connection import ConnectionFactory
from gameshelf.db.migrator import Migrator
from gameshelf.db.writer import DbWriter
from gameshelf.library.launcher import LaunchReceipt
from gameshelf.platform.windows.known_folders import KnownFolders
from gameshelf.saves.guided_events import RawFileChange
from gameshelf.saves.guided_models import GuidedSavePreview, GuidedScopeOption
from gameshelf.saves.guided_registry import RegistrySnapshot
from gameshelf.saves.guided_repository import GuidedSaveRepository
from gameshelf.saves.guided_scanner import BoundedMetadataScanner
from gameshelf.saves.guided_scoring import GuidedScoringContext
from gameshelf.saves.guided_service import GuidedSaveSessionService
from gameshelf.saves.templates import PathTemplateResolver


def test_guided_session_persists_review_candidate_without_formal_location(
    tmp_path: Path,
) -> None:
    factory = ConnectionFactory(tmp_path / "data" / "library.db")
    Migrator(factory, tmp_path / "backups").migrate()
    game_dir = tmp_path / "Games" / "Alice"
    save_dir = game_dir / "Saves"
    save_dir.mkdir(parents=True)
    with factory.connect() as connection:
        _insert_game(connection, game_dir)
        connection.commit()
    writer = DbWriter(factory)
    writer.start()
    repository = GuidedSaveRepository(factory, writer)
    scope = GuidedScopeOption(
        "default:game",
        "游戏安装目录",
        str(game_dir),
        "<game>",
        "game",
        True,
        True,
    )
    scopes = StaticScopes(GuidedSavePreview("game-1", "Alice", "Alice.exe", (scope,), ()))
    watcher = CapturingWatcher()
    scheduler = ManualScheduler()
    resolver = PathTemplateResolver(_folders(tmp_path))
    service = GuidedSaveSessionService(
        repository=repository,
        scope_builder=scopes,
        registry_reader=EmptyRegistry(),
        watcher=watcher,
        launcher=StaticLauncher(),
        process_tracker=StaticProcessTracker(),
        scanner=BoundedMetadataScanner(),
        scoring_context_factory=lambda _game, _scopes, overflow, truncated: GuidedScoringContext(
            resolver=resolver,
            game_dir=game_dir,
            overflowed_root_keys=overflow,
            truncated_root_keys=truncated,
        ),
        scheduler=scheduler,
        utc_now=TickClock().utc_now,
        monotonic_ns=TickClock().monotonic_ns,
        submit_analysis=lambda operation: operation(),
    )
    try:
        session = service.start("game-1", ("default:game",), ())
        watcher.sink.on_change(
            RawFileChange(
                "modified", save_dir / "slot1.sav", None, 2_000_000_000, root=game_dir
            )
        )
        service.mark_saved(session.id)
        scheduler.run(3.0)

        completed = repository.get_session(session.id)
        assert completed is not None
        assert completed.status == "completed"
        assert len(repository.list_discoveries(session.id)) == 1
        with factory.connect(readonly=True) as connection:
            formal_count = connection.execute(
                "SELECT COUNT(*) FROM save_locations"
            ).fetchone()[0]
        assert formal_count == 0
    finally:
        service.close()
        writer.close()


class StaticScopes:
    def __init__(self, preview: GuidedSavePreview) -> None:
        self._preview = preview

    def preview(self, _game_id: str) -> GuidedSavePreview:
        return self._preview

    def resolve_selected(
        self,
        _game_id: str,
        _selected: Sequence[str],
        _additional: Sequence[str],
    ) -> tuple[GuidedScopeOption, ...]:
        return self._preview.scopes


class EmptyRegistry:
    def snapshot(self, _keys: tuple[str, ...]) -> RegistrySnapshot:
        return RegistrySnapshot(())


class StopHandle:
    def stop(self) -> None:
        return None


class CapturingWatcher:
    sink: object

    def start(self, _root: Path, sink: object) -> StopHandle:
        self.sink = sink
        return StopHandle()


class StaticLauncher:
    def launch(self, game_id: str) -> LaunchReceipt:
        return LaunchReceipt(game_id, 123, "2026-08-15T00:00:01+00:00")


class StaticProcessTracker:
    def start(self, _pid: int, _sink: object) -> StopHandle:
        return StopHandle()


class TimerHandle:
    def __init__(self, delay: float, callback: Callable[[], None]) -> None:
        self.delay = delay
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class ManualScheduler:
    def __init__(self) -> None:
        self.timers: list[TimerHandle] = []

    def call_later(self, delay: float, callback: Callable[[], None]) -> TimerHandle:
        timer = TimerHandle(delay, callback)
        self.timers.append(timer)
        return timer

    def run(self, delay: float) -> None:
        next(timer for timer in self.timers if timer.delay == delay).callback()


class TickClock:
    def __init__(self) -> None:
        self.tick = 0

    def utc_now(self) -> str:
        self.tick += 1
        return f"2026-08-15T00:00:{self.tick:02d}+00:00"

    def monotonic_ns(self) -> int:
        self.tick += 1
        return self.tick * 1_000_000_000


def _insert_game(connection: sqlite3.Connection, game_dir: Path) -> None:
    connection.execute(
        """
        INSERT INTO games(
            id, install_path_key, title, status, main_exe_relpath, added_at, updated_at
        ) VALUES (
            'game-1', ?, 'Alice', 'save_only', 'Alice.exe',
            '2026-08-15T00:00:00+00:00', '2026-08-15T00:00:00+00:00'
        )
        """,
        (str(game_dir),),
    )


def _folders(tmp_path: Path) -> KnownFolders:
    home = tmp_path / "Profile"
    return KnownFolders(
        home,
        home / "AppData" / "Roaming",
        home / "AppData" / "Local",
        home / "AppData" / "LocalLow",
        home / "Documents",
        home / "Saved Games",
        tmp_path / "ProgramData",
        tmp_path / "Public",
        tmp_path / "Windows",
    )
