"""Composition root for portable GameShelf services."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock

from gameshelf.bootstrap.logging import configure_logging
from gameshelf.bootstrap.paths import AppPaths
from gameshelf.bridge.api import BridgeApi
from gameshelf.bridge.tasks import TaskRegistry
from gameshelf.covers.service import CoverService
from gameshelf.db.connection import ConnectionFactory
from gameshelf.db.migrator import Migrator
from gameshelf.db.writer import DbWriter
from gameshelf.library.launcher import GameLauncher
from gameshelf.library.repository import LibraryRepository
from gameshelf.library.service import LibraryService
from gameshelf.platform.windows.processes import WindowsProcessLauncher
from gameshelf.platform.windows.shell import WindowsShell
from gameshelf.scanning.service import ScanService
from gameshelf.web.asset_server import AssetServer, AssetServerAddress


@dataclass
class Application:
    paths: AppPaths
    api: BridgeApi
    database: ConnectionFactory
    writer: DbWriter
    tasks: TaskRegistry
    logger: logging.Logger
    schema_version: int
    asset_server: AssetServer
    asset_address: AssetServerAddress
    _close_lock: Lock = field(default_factory=Lock, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        self.tasks.close()
        self.asset_server.stop()
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
    covers = CoverService(paths, repository, writer)
    def cover_lookup(game_id: str, variant: str) -> Path | None:
        column = "cover_original_relpath" if variant == "original" else "cover_thumb_relpath"
        with database.connect(readonly=True) as connection:
            row = connection.execute(
                f"SELECT {column} FROM games WHERE id = ?", (game_id,)
            ).fetchone()
        if row is None or row[0] is None:
            return None
        return paths.data_dir.joinpath(*str(row[0]).split("/"))

    asset_server = AssetServer(
        paths.app_root / "resources" / "ui",
        cover_lookup,
        managed_cover_roots=(paths.covers_original_dir, paths.covers_thumbs_dir),
    )
    asset_address = asset_server.start()
    api = BridgeApi(
        paths,
        tasks,
        schema_version=schema_version,
        library=library,
        scanner=scanner,
        launcher=launcher,
        covers=covers,
        asset_session_token=asset_address.session_token,
    )
    return Application(
        paths=paths,
        api=api,
        database=database,
        writer=writer,
        tasks=tasks,
        logger=logger,
        schema_version=schema_version,
        asset_server=asset_server,
        asset_address=asset_address,
    )
