"""Composition root for portable GameShelf services."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Lock

from gameshelf.bootstrap.config import ConfigService, JsonConfigStore
from gameshelf.bootstrap.logging import configure_logging
from gameshelf.bootstrap.paths import AppPaths
from gameshelf.bridge.api import BridgeApi
from gameshelf.bridge.tasks import TaskRegistry
from gameshelf.covers.service import CoverService
from gameshelf.db.connection import ConnectionFactory
from gameshelf.db.migrator import Migrator
from gameshelf.db.writer import DbWriter
from gameshelf.engines.service import EngineDetectionService
from gameshelf.library.launcher import GameLauncher
from gameshelf.library.repository import LibraryRepository
from gameshelf.library.service import LibraryService
from gameshelf.platform.windows.known_folders import WindowsKnownFolderProvider
from gameshelf.platform.windows.processes import WindowsProcessLauncher
from gameshelf.platform.windows.registry import WindowsRegistry
from gameshelf.platform.windows.shell import WindowsShell
from gameshelf.saves.custom_manifest_provider import CustomManifestProvider
from gameshelf.saves.engine_hints import EngineSaveHintProvider
from gameshelf.saves.ludusavi_provider import LudusaviProvider
from gameshelf.saves.repository import SaveLocationRepository
from gameshelf.saves.service import SaveLocationService
from gameshelf.saves.static_discovery import StaticSaveDiscovery
from gameshelf.saves.templates import PathTemplateResolver
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
    config: ConfigService
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
            if isinstance(handler, RotatingFileHandler):
                handler.close()
                self.logger.removeHandler(handler)
        self.logger.propagate = True


def build_application(paths: AppPaths) -> Application:
    paths.ensure_writable()
    logger = configure_logging(paths.logs_dir)
    config = ConfigService(JsonConfigStore(paths.config_file))
    database = ConnectionFactory(paths.database_file)
    schema_version = Migrator(database, paths.backups_dir).migrate()
    writer = DbWriter(database)
    writer.start()
    tasks = TaskRegistry(logger=logger)
    repository = LibraryRepository(database)
    library = LibraryService(repository, writer)
    engine_detection = EngineDetectionService.from_rules_file(_engine_rules_file(paths))
    scanner = ScanService(repository, writer, engine_detection)
    shell = WindowsShell()
    launcher = GameLauncher(repository, writer, WindowsProcessLauncher(), shell)
    covers = CoverService(paths, repository, writer)
    resolver = PathTemplateResolver(WindowsKnownFolderProvider().load())
    save_repository = SaveLocationRepository(database)
    save_locations = SaveLocationService(
        save_repository,
        writer,
        resolver,
        library,
        shell,
        WindowsRegistry(),
    )
    custom_manifest_directory = paths.manifests_dir / "custom"
    custom_provider = CustomManifestProvider(custom_manifest_directory)
    ludusavi_provider = LudusaviProvider(
        resource_dir=_ludusavi_resource_dir(paths),
        active_dir=paths.manifests_dir / "ludusavi",
        temp_dir=paths.temp_dir,
    )
    static_discovery = StaticSaveDiscovery(
        library=library,
        save_repository=save_repository,
        resolver=resolver,
        ludusavi_provider=ludusavi_provider,
        custom_provider=custom_provider,
        engine_hints=EngineSaveHintProvider(resolver),
        engine_is_experimental=engine_detection.is_experimental,
    )

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
        config=config,
        library=library,
        scanner=scanner,
        launcher=launcher,
        covers=covers,
        engine_detection=engine_detection,
        save_locations=save_locations,
        static_discovery=static_discovery,
        ludusavi_provider=ludusavi_provider,
        custom_provider=custom_provider,
        custom_manifest_directory=custom_manifest_directory,
        directory_opener=shell.open_directory,
        asset_session_token=asset_address.session_token,
    )
    return Application(
        paths=paths,
        api=api,
        database=database,
        writer=writer,
        tasks=tasks,
        logger=logger,
        config=config,
        schema_version=schema_version,
        asset_server=asset_server,
        asset_address=asset_address,
    )


def _engine_rules_file(paths: AppPaths) -> Path:
    adjacent = paths.app_root / "resources" / "rules" / "engines.yaml"
    if adjacent.is_file():
        return adjacent
    return Path(__file__).resolve().parents[3] / "resources" / "rules" / "engines.yaml"


def _ludusavi_resource_dir(paths: AppPaths) -> Path:
    adjacent = paths.app_root / "resources" / "manifests" / "ludusavi"
    if adjacent.is_dir():
        return adjacent
    return Path(__file__).resolve().parents[3] / "resources" / "manifests" / "ludusavi"
