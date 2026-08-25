from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

from gamesave_scout.db.connection import ConnectionFactory
from gamesave_scout.db.migrator import Migrator
from gamesave_scout.db.writer import DbWriter
from gamesave_scout.library.launcher import LaunchReceipt
from gamesave_scout.library.repository import LibraryRepository
from gamesave_scout.library.service import LibraryService
from gamesave_scout.platform.windows.known_folders import KnownFolders
from gamesave_scout.saves.guided_events import RawFileChange
from gamesave_scout.saves.guided_models import GuidedSavePreview, GuidedScopeOption
from gamesave_scout.saves.guided_registry import RegistrySnapshot
from gamesave_scout.saves.guided_repository import GuidedSaveRepository
from gamesave_scout.saves.guided_review import GuidedSaveReviewService
from gamesave_scout.saves.guided_scanner import BoundedMetadataScanner
from gamesave_scout.saves.guided_scoring import GuidedScoringContext
from gamesave_scout.saves.guided_service import GuidedSaveSessionService
from gamesave_scout.saves.repository import SaveLocationRepository
from gamesave_scout.saves.service import SaveLocationService
from gamesave_scout.saves.templates import PathTemplateResolver


class _UnusedShell:
    def open_directory(self, _path: Path) -> None:
        raise AssertionError("测试不应打开目录")

    def reveal_file(self, _path: Path) -> None:
        raise AssertionError("测试不应定位文件")


class _Registry:
    def key_exists(self, _key: str) -> bool:
        return False

    def open_key(self, _key: str) -> None:
        raise AssertionError("测试不应打开注册表")


@dataclass
class EndToEndHarness:
    factory: ConnectionFactory
    writer: DbWriter
    repository: GuidedSaveRepository
    service: GuidedSaveSessionService
    review: GuidedSaveReviewService
    scheduler: _Scheduler
    watcher: _Watcher
    resolver: PathTemplateResolver
    game_dir: Path


@pytest.fixture
def guided_end_to_end(tmp_path: Path) -> Iterator[EndToEndHarness]:
    factory = ConnectionFactory(tmp_path / "data" / "library.db")
    Migrator(factory, tmp_path / "backups").migrate()
    game_dir = tmp_path / "Games" / "Alice"
    game_dir.mkdir(parents=True)
    with factory.connect() as connection:
        _insert_game(connection, game_dir)
        connection.commit()
    writer = DbWriter(factory)
    writer.start()
    repository = GuidedSaveRepository(factory, writer)
    scope = GuidedScopeOption(
        "default:game", "游戏安装目录", str(game_dir), "<game>", "game", True, True
    )
    preview = GuidedSavePreview(
        "game-1", "Alice", str(game_dir / "Alice.exe"), (scope,), ()
    )
    resolver = PathTemplateResolver(_folders(tmp_path))
    watcher = _Watcher()
    scheduler = _Scheduler()
    clock = _Clock()
    service = GuidedSaveSessionService(
        repository=repository,
        scope_builder=_Scopes(preview),
        registry_reader=_EmptyRegistry(),
        watcher=watcher,
        launcher=_Launcher(),
        process_tracker=_Processes(),
        scanner=BoundedMetadataScanner(),
        scoring_context_factory=lambda _game, scopes, overflow, truncated: GuidedScoringContext(
            resolver=resolver,
            game_dir=game_dir,
            trusted_root_keys=tuple(item.display_path.casefold() for item in scopes),
            overflowed_root_keys=overflow,
            truncated_root_keys=truncated,
        ),
        scheduler=scheduler,
        utc_now=clock.utc_now,
        monotonic_ns=clock.monotonic_ns,
        wall_time_ns=clock.wall_time_ns,
        submit_analysis=lambda operation: operation(),
    )
    library = LibraryService(LibraryRepository(factory), writer)
    save_locations = SaveLocationService(
        SaveLocationRepository(factory),
        writer,
        resolver,
        library,
        _UnusedShell(),
        _Registry(),
    )
    review = GuidedSaveReviewService(factory, writer, repository, save_locations)
    try:
        yield EndToEndHarness(
            factory,
            writer,
            repository,
            service,
            review,
            scheduler,
            watcher,
            resolver,
            game_dir,
        )
    finally:
        service.close()
        writer.close()


def test_marked_save_is_reviewed_and_accepted_without_changing_file_bytes(
    guided_end_to_end: EndToEndHarness,
) -> None:
    harness = guided_end_to_end
    preview = harness.service.preview("game-1")
    session = harness.service.start("game-1", (preview.scopes[0].id,), ())
    save_file = harness.game_dir / "Saves" / "slot1.sav"
    save_file.parent.mkdir()
    original_bytes = b"GameSave Scout guided save e2e\x00\xff"
    save_file.write_bytes(original_bytes)
    harness.watcher.sink.on_change(
        RawFileChange(
            "modified",
            save_file,
            None,
            2_000_000_000,
            root=harness.game_dir,
            size=len(original_bytes),
        )
    )

    harness.service.mark_saved(session.id)
    harness.scheduler.run(3.0)
    discoveries = harness.repository.list_discoveries(session.id)
    accepted = harness.review.accept(session.id, (discoveries[0].id,), False)

    assert len(discoveries) == 1
    assert accepted[0].source == "dynamic"
    assert harness.resolver.expand(accepted[0].path_template, harness.game_dir) == save_file
    assert save_file.read_bytes() == original_bytes
    with harness.factory.connect(readonly=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM save_locations").fetchone()[0] == 1


def test_unmarked_atomic_replace_filters_cache_and_never_preselects(
    guided_end_to_end: EndToEndHarness,
) -> None:
    harness = guided_end_to_end
    session = harness.service.start("game-1", ("default:game",), ())
    saves = harness.game_dir / "Saves"
    cache = harness.game_dir / "Cache"
    saves.mkdir()
    cache.mkdir()
    temporary = saves / "slot1.tmp"
    final = saves / "slot1.sav"
    temporary.write_bytes(b"slot")
    temporary.replace(final)
    (cache / "browser.log").write_bytes(b"noise")
    harness.watcher.sink.on_change(
        RawFileChange("created", temporary, None, 2_000_000_000, root=harness.game_dir)
    )
    harness.watcher.sink.on_change(
        RawFileChange("moved", temporary, final, 2_100_000_000, root=harness.game_dir)
    )
    harness.watcher.sink.on_change(
        RawFileChange(
            "modified", cache / "browser.log", None, 2_200_000_000, root=harness.game_dir
        )
    )

    harness.service.stop_and_analyze(session.id)
    discoveries = harness.repository.list_discoveries(session.id)

    assert len(discoveries) == 1
    assert discoveries[0].display_path == str(final)
    assert discoveries[0].preselected is False
    assert all("Cache" not in item.display_path for item in discoveries)
    assert final.read_bytes() == b"slot"


class _Scopes:
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


class _EmptyRegistry:
    def snapshot(self, _keys: tuple[str, ...]) -> RegistrySnapshot:
        return RegistrySnapshot(())


class _Stop:
    def stop(self) -> None:
        return None


class _Watcher:
    sink: object

    def start(self, _root: Path, sink: object) -> _Stop:
        self.sink = sink
        return _Stop()


class _Processes:
    def start(self, _pid: int, _sink: object) -> _Stop:
        return _Stop()


class _Launcher:
    def launch(self, game_id: str) -> LaunchReceipt:
        return LaunchReceipt(game_id, 123, "2026-08-15T00:00:01+00:00")


class _Timer:
    def __init__(self, delay: float, callback: Callable[[], None]) -> None:
        self.delay = delay
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class _Scheduler:
    def __init__(self) -> None:
        self.timers: list[_Timer] = []

    def call_later(self, delay: float, callback: Callable[[], None]) -> _Timer:
        timer = _Timer(delay, callback)
        self.timers.append(timer)
        return timer

    def run(self, delay: float) -> None:
        next(
            timer
            for timer in self.timers
            if timer.delay == delay and not timer.cancelled
        ).callback()


class _Clock:
    def __init__(self) -> None:
        self.tick = 0

    def utc_now(self) -> str:
        self.tick += 1
        return f"2026-08-15T00:00:{self.tick:02d}+00:00"

    def monotonic_ns(self) -> int:
        self.tick += 1
        return self.tick * 1_000_000_000

    def wall_time_ns(self) -> int:
        self.tick += 1
        return 1_700_000_000_000_000_000 + self.tick * 1_000_000_000


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
