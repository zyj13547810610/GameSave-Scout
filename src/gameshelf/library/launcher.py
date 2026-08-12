"""Validate stored launch settings before calling Windows adapters."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from gameshelf.db.writer import DbWriter
from gameshelf.library.models import Game
from gameshelf.library.repository import LibraryRepository
from gameshelf.platform.windows.processes import LaunchedProcess
from gameshelf.scanning.path_keys import PathTraversalError, expand_relative


class InvalidLaunchConfiguration(ValueError):
    """Raised when a game cannot be launched from its stored configuration."""


class GameNotFoundError(LookupError):
    """Raised when a launch command names an unknown game."""


class ProcessLauncher(Protocol):
    def launch(
        self,
        executable: Path,
        arguments: Sequence[str],
        cwd: Path,
        environment: Mapping[str, str],
    ) -> LaunchedProcess: ...


class DirectoryShell(Protocol):
    def open_directory(self, path: Path) -> None: ...


@dataclass(frozen=True)
class LaunchReceipt:
    game_id: str
    pid: int
    launched_at: str


class GameLauncher:
    def __init__(
        self,
        repository: LibraryRepository,
        writer: DbWriter,
        process_launcher: ProcessLauncher,
        shell: DirectoryShell,
    ) -> None:
        self._repository = repository
        self._writer = writer
        self._process_launcher = process_launcher
        self._shell = shell

    def launch(self, game_id: str) -> LaunchReceipt:
        game = self._require_game(game_id)
        install_dir = self._install_directory(game)
        if game.status != "installed" or not install_dir.is_dir():
            raise InvalidLaunchConfiguration("The game installation is unavailable.")
        if game.main_exe_relpath is None:
            raise InvalidLaunchConfiguration("No main executable has been selected.")
        executable = _safe_relative(install_dir, game.main_exe_relpath, "executable")
        if executable.suffix.casefold() != ".exe" or not executable.is_file():
            raise InvalidLaunchConfiguration("The selected executable does not exist.")

        if game.working_dir_relpath is None:
            working_directory = install_dir
        else:
            working_directory = _safe_relative(
                install_dir, game.working_dir_relpath, "working directory"
            )
        if not working_directory.is_dir():
            raise InvalidLaunchConfiguration("The configured working directory is unavailable.")

        environment = dict(os.environ)
        for key, value in game.environment.items():
            if not key or "=" in key or "\x00" in key or "\x00" in value:
                raise InvalidLaunchConfiguration("The launch environment contains invalid text.")
            environment[key] = value

        launched = self._process_launcher.launch(
            executable,
            game.launch_args,
            working_directory,
            environment,
        )
        launched_at = datetime.now(UTC).isoformat(timespec="seconds")
        self._record_success(game.id, launched_at)
        return LaunchReceipt(game.id, launched.pid, launched_at)

    def open_install_directory(self, game_id: str) -> None:
        game = self._require_game(game_id)
        install_dir = self._install_directory(game)
        if not install_dir.is_dir():
            raise InvalidLaunchConfiguration("The game installation directory is unavailable.")
        self._shell.open_directory(install_dir)

    def _require_game(self, game_id: str) -> Game:
        game = self._repository.get_game(game_id)
        if game is None:
            raise GameNotFoundError(game_id)
        return game

    def _install_directory(self, game: Game) -> Path:
        if game.scan_root_id is not None and game.relative_dir is not None:
            root = self._repository.get_root(game.scan_root_id)
            if root is not None:
                return _safe_relative(Path(root.display_path), game.relative_dir, "game directory")
        if game.install_path_key is not None:
            return Path(game.install_path_key)
        raise InvalidLaunchConfiguration("The game has no installation directory.")

    def _record_success(self, game_id: str, launched_at: str) -> None:
        def operation(connection: sqlite3.Connection) -> None:
            connection.execute(
                "UPDATE games SET last_launched_at = ?, updated_at = ? WHERE id = ?",
                (launched_at, launched_at, game_id),
            )

        self._writer.submit(operation).result()


def _safe_relative(root: Path, relative: str, label: str) -> Path:
    try:
        return expand_relative(root, relative)
    except PathTraversalError as error:
        raise InvalidLaunchConfiguration(
            f"The configured {label} escapes the game directory."
        ) from error
