"""Composition root for portable GameShelf services."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from threading import Lock

from gameshelf.bootstrap.logging import configure_logging
from gameshelf.bootstrap.paths import AppPaths
from gameshelf.bridge.api import BridgeApi
from gameshelf.bridge.tasks import TaskRegistry
from gameshelf.db.connection import ConnectionFactory
from gameshelf.db.migrator import Migrator
from gameshelf.db.writer import DbWriter
from gameshelf.library.launcher import GameLauncher
from gameshelf.library.repository import LibraryRepository
from gameshelf.library.service import LibraryService
from gameshelf.platform.windows.processes import WindowsProcessLauncher
from gameshelf.platform.windows.shell import WindowsShell
from gameshelf.scanning.service import ScanService


@dataclass
class Application:
    paths: AppPaths
    api: BridgeApi
    database: ConnectionFactory
    writer: DbWriter
    tasks: TaskRegistry
    logger: logging.Logger
    schema_version: int
    _close_lock: Lock = field(default_factory=Lock, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        self.tasks.close()
        self.writer.close()
        for handler in tuple(self.logger.handlers):
            handler.flush()


def build_application(paths: AppPaths) -> Application:
    paths.ensure_writable()
    logger = configure_logging(paths.logs_dir)
    database = ConnectionFactory(paths.database_file)
    schema_version = Migrator(database, paths.backups_dir).migrate()
    writer = DbWriter(database)
    writer.start()
    tasks = TaskRegistry()
    repository = LibraryRepository(database)
    library = LibraryService(repository, writer)
    scanner = ScanService(repository, writer)
    launcher = GameLauncher(
        repository, writer, WindowsProcessLauncher(), WindowsShell()
    )
    api = BridgeApi(
        paths,
        tasks,
        schema_version=schema_version,
        library=library,
        scanner=scanner,
        launcher=launcher,
    )
    return Application(
        paths=paths,
        api=api,
        database=database,
        writer=writer,
        tasks=tasks,
        logger=logger,
        schema_version=schema_version,
    )
