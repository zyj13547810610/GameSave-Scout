from dataclasses import dataclass
from pathlib import Path

import pytest

from gamesave_scout.db.connection import ConnectionFactory
from gamesave_scout.db.migrator import Migrator
from gamesave_scout.db.writer import DbWriter
from gamesave_scout.library.launcher import GameLauncher, InvalidLaunchConfiguration
from gamesave_scout.library.models import Game
from gamesave_scout.library.repository import LibraryRepository
from gamesave_scout.library.service import LibraryService
from gamesave_scout.platform.windows.processes import LaunchedProcess


def test_launch_uses_array_cwd_and_shell_false(
    game_launcher: "LauncherHarness",
) -> None:
    game = game_launcher.fixture_game(
        exe="bin/Alice.exe",
        args=["--profile", "A B"],
        working_dir="bin",
    )

    receipt = game_launcher.launcher.launch(game.id)

    call = game_launcher.process.calls[0]
    assert call.executable == game_launcher.install_dir / "bin" / "Alice.exe"
    assert call.arguments == ("--profile", "A B")
    assert call.cwd == game_launcher.install_dir / "bin"
    assert call.shell is False
    assert receipt.pid == 4321
    assert game_launcher.game(game.id).last_launched_at is not None


def test_auto_selected_executable_without_working_directory_uses_install_directory(
    game_launcher: "LauncherHarness",
) -> None:
    game = game_launcher.fixture_game(
        exe="bin/Auto.exe",
        main_exe_is_manual=False,
    )

    game_launcher.launcher.launch(game.id)

    assert game_launcher.process.calls[0].cwd == game_launcher.install_dir


def test_manual_executable_without_working_directory_uses_executable_parent(
    game_launcher: "LauncherHarness",
) -> None:
    game = game_launcher.fixture_game(
        exe="game/Paralogue/Binaries/Win64/KiritoMod049.exe",
        main_exe_is_manual=True,
    )

    game_launcher.launcher.launch(game.id)

    assert game_launcher.process.calls[0].cwd == (
        game_launcher.install_dir / "game" / "Paralogue" / "Binaries" / "Win64"
    )
    assert game_launcher.game(game.id).working_dir_relpath is None


def test_explicit_working_directory_overrides_manual_executable_parent(
    game_launcher: "LauncherHarness",
) -> None:
    (game_launcher.install_dir / "runtime").mkdir()
    game = game_launcher.fixture_game(
        exe="bin/Manual.exe",
        main_exe_is_manual=True,
        working_dir="runtime",
    )

    game_launcher.launcher.launch(game.id)

    assert game_launcher.process.calls[0].cwd == game_launcher.install_dir / "runtime"


def test_launch_rejects_relative_exe_that_escapes_install_dir(
    game_launcher: "LauncherHarness",
) -> None:
    game = game_launcher.fixture_game(exe="../outside.exe", create_exe=False)

    with pytest.raises(InvalidLaunchConfiguration):
        game_launcher.launcher.launch(game.id)

    assert game_launcher.process.calls == []


def test_launch_requires_existing_exe_and_does_not_record_failed_attempt(
    game_launcher: "LauncherHarness",
) -> None:
    game = game_launcher.fixture_game(exe="Missing.exe", create_exe=False)

    with pytest.raises(InvalidLaunchConfiguration):
        game_launcher.launcher.launch(game.id)

    assert game_launcher.game(game.id).last_launched_at is None


def test_open_install_directory_uses_validated_shell_adapter(
    game_launcher: "LauncherHarness",
) -> None:
    game = game_launcher.fixture_game(exe="Alice.exe")

    game_launcher.launcher.open_install_directory(game.id)

    assert game_launcher.shell.opened == [game_launcher.install_dir]


@pytest.fixture
def game_launcher(tmp_path: Path) -> "LauncherHarness":
    factory = ConnectionFactory(tmp_path / "data" / "library.db")
    Migrator(factory, tmp_path / "backups").migrate()
    writer = DbWriter(factory)
    writer.start()
    repository = LibraryRepository(factory)
    service = LibraryService(repository, writer)
    root_path = tmp_path / "games"
    install_dir = root_path / "Alice"
    install_dir.mkdir(parents=True)
    root = service.add_root(str(root_path), "children", 1, [])
    process = FakeProcessLauncher()
    shell = FakeShell()
    harness = LauncherHarness(
        install_dir,
        writer,
        repository,
        service,
        root.id,
        process,
        shell,
        GameLauncher(repository, writer, process, shell),
    )
    try:
        yield harness
    finally:
        writer.close()


@dataclass(frozen=True)
class ProcessCall:
    executable: Path
    arguments: tuple[str, ...]
    cwd: Path
    environment: dict[str, str]
    shell: bool = False


class FakeProcessLauncher:
    def __init__(self) -> None:
        self.calls: list[ProcessCall] = []

    def launch(
        self,
        executable: Path,
        arguments: tuple[str, ...],
        cwd: Path,
        environment: dict[str, str],
    ) -> LaunchedProcess:
        self.calls.append(ProcessCall(executable, arguments, cwd, environment))
        return LaunchedProcess(4321)


class FakeShell:
    def __init__(self) -> None:
        self.opened: list[Path] = []

    def open_directory(self, path: Path) -> None:
        self.opened.append(path)


@dataclass
class LauncherHarness:
    install_dir: Path
    writer: DbWriter
    repository: LibraryRepository
    service: LibraryService
    root_id: str
    process: FakeProcessLauncher
    shell: FakeShell
    launcher: GameLauncher

    def fixture_game(
        self,
        *,
        exe: str,
        args: list[str] | None = None,
        working_dir: str | None = None,
        main_exe_is_manual: bool = False,
        create_exe: bool = True,
    ) -> Game:
        game = self.service.create_game_for_test(self.root_id, "Alice", "Alice")
        if create_exe and ".." not in exe.split("/"):
            executable = self.install_dir.joinpath(*exe.split("/"))
            executable.parent.mkdir(parents=True, exist_ok=True)
            executable.write_bytes(b"not-a-real-pe")
        import json

        self.writer.submit(
            lambda connection: connection.execute(
                """
                UPDATE games
                SET main_exe_relpath = ?, main_exe_is_manual = ?,
                    launch_args_json = ?, working_dir_relpath = ?
                WHERE id = ?
                """,
                (
                    exe,
                    int(main_exe_is_manual),
                    json.dumps(args or []),
                    working_dir,
                    game.id,
                ),
            ).rowcount
        ).result()
        return self.game(game.id)

    def game(self, game_id: str) -> Game:
        game = self.repository.get_game(game_id)
        assert game is not None
        return game
