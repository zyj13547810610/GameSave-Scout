"""Composition root for portable GameShelf services."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Lock
from time import monotonic_ns
from typing import cast

from gameshelf.bootstrap.config import ConfigService, JsonConfigStore
from gameshelf.bootstrap.logging import configure_logging
from gameshelf.bootstrap.paths import AppPaths
from gameshelf.bootstrap.resources import ResourcePaths
from gameshelf.bridge.api import BridgeApi
from gameshelf.bridge.tasks import TaskRegistry
from gameshelf.covers.local_discovery import LocalCoverDiscovery
from gameshelf.covers.service import CoverService
from gameshelf.covers.vndb import VndbClient
from gameshelf.covers.wizard_service import CoverWizardService
from gameshelf.db.connection import ConnectionFactory
from gameshelf.db.migrator import Migrator
from gameshelf.db.writer import DbWriter
from gameshelf.engines.rule_schema import RuleSchemaError
from gameshelf.engines.service import EngineDetectionService
from gameshelf.library.group_repository import GroupRepository
from gameshelf.library.group_service import GroupService
from gameshelf.library.launcher import GameLauncher
from gameshelf.library.repository import LibraryRepository
from gameshelf.library.service import LibraryService
from gameshelf.platform.windows.directory_watcher import WindowsDirectoryWatcher
from gameshelf.platform.windows.known_folders import WindowsKnownFolderProvider
from gameshelf.platform.windows.process_tree import WindowsProcessTreeTracker
from gameshelf.platform.windows.processes import WindowsProcessLauncher
from gameshelf.platform.windows.registry import WindowsRegistry
from gameshelf.platform.windows.shell import WindowsShell
from gameshelf.saves.batch_external import BatchCandidateOpener, BatchExternalLookup
from gameshelf.saves.batch_repository import BatchSaveRepository
from gameshelf.saves.batch_review import BatchSaveReviewService
from gameshelf.saves.batch_rules import BatchRuleProvider
from gameshelf.saves.batch_scanner import BatchFilesystemScanner
from gameshelf.saves.batch_scope import BatchScopeBuilder
from gameshelf.saves.batch_service import BatchSaveDiscoveryService
from gameshelf.saves.builtin_rules import BuiltinSaveRuleProvider
from gameshelf.saves.custom_manifest_provider import CustomManifestProvider
from gameshelf.saves.engine_hints import EngineSaveHintProvider
from gameshelf.saves.guided_models import GuidedScopeOption
from gameshelf.saves.guided_registry import RegistryMetadataReader
from gameshelf.saves.guided_repository import GuidedSaveRepository
from gameshelf.saves.guided_review import GuidedSaveReviewService
from gameshelf.saves.guided_scanner import BoundedMetadataScanner
from gameshelf.saves.guided_scope import GuidedSaveScopeBuilder
from gameshelf.saves.guided_scoring import GuidedScoringContext
from gameshelf.saves.guided_service import (
    DirectoryWatcher,
    GuidedSaveSessionService,
    ProcessTracker,
)
from gameshelf.saves.ludusavi_provider import LudusaviProvider
from gameshelf.saves.repository import SaveLocationRepository
from gameshelf.saves.rule_schema import SaveRuleSchemaError
from gameshelf.saves.service import SaveLocationService
from gameshelf.saves.static_discovery import StaticSaveDiscovery
from gameshelf.saves.templates import PathTemplateResolver
from gameshelf.scanning.analysis_pool import ScanAnalysisPool
from gameshelf.scanning.path_keys import windows_path_key
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
    guided_saves: GuidedSaveSessionService
    builtin_save_rules: BuiltinSaveRuleProvider
    cover_wizard: CoverWizardService
    analysis_pool: ScanAnalysisPool
    _close_lock: Lock = field(default_factory=Lock, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        self.guided_saves.close()
        self.tasks.close()
        self.analysis_pool.close()
        self.cover_wizard.close_all()
        self.asset_server.stop()
        self.writer.close()
        for handler in tuple(self.logger.handlers):
            handler.flush()
            if isinstance(handler, RotatingFileHandler):
                handler.close()
                self.logger.removeHandler(handler)
        self.logger.propagate = True


def build_application(
    paths: AppPaths,
    resources: ResourcePaths | None = None,
) -> Application:
    resource_paths = resources or ResourcePaths.for_runtime()
    paths.ensure_writable()
    logger = configure_logging(paths.logs_dir)
    config = ConfigService(JsonConfigStore(paths.config_file))
    engine_detection = _load_engine_detection(
        resource_paths.engine_rules_file,
        logger,
    )
    known_folders = WindowsKnownFolderProvider().load()
    resolver = PathTemplateResolver(known_folders)
    builtin_save_rules = _load_builtin_save_rules(
        resource_paths.save_rules_file,
        resolver,
        logger,
    )
    database = ConnectionFactory(paths.database_file)
    schema_version = Migrator(database, paths.backups_dir).migrate()
    writer = DbWriter(database)
    writer.start()
    tasks = TaskRegistry(logger=logger)
    repository = LibraryRepository(database)
    library = LibraryService(repository, writer)
    groups = GroupService(
        connection_factory=database,
        writer=writer,
        repository=GroupRepository(database),
    )
    analysis_pool = ScanAnalysisPool(lambda: config.current.scan_concurrency)
    scanner = ScanService(
        repository,
        writer,
        engine_detection,
        analysis_pool=analysis_pool,
    )
    shell = WindowsShell()
    launcher = GameLauncher(repository, writer, WindowsProcessLauncher(), shell)
    covers = CoverService(paths, repository, writer)
    cover_wizard = CoverWizardService(
        paths,
        library,
        covers,
        LocalCoverDiscovery(),
        VndbClient(),
    )
    save_repository = SaveLocationRepository(database)
    registry = WindowsRegistry()
    save_locations = SaveLocationService(
        save_repository,
        writer,
        resolver,
        library,
        shell,
        registry,
    )
    custom_manifest_directory = paths.manifests_dir / "custom"
    custom_provider = CustomManifestProvider(custom_manifest_directory)
    ludusavi_provider = LudusaviProvider(
        resource_dir=resource_paths.ludusavi_dir,
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
    guided_repository = GuidedSaveRepository(database, writer)
    guided_scope_builder = GuidedSaveScopeBuilder(
        library=library,
        save_repository=save_repository,
        resolver=resolver,
        known_folders=known_folders,
        static_discovery=static_discovery,
    )

    def guided_scoring_context(
        game_id: str,
        scopes: tuple[GuidedScopeOption, ...],
        overflowed_root_keys: tuple[str, ...],
        truncated_root_keys: tuple[str, ...],
    ) -> GuidedScoringContext:
        game_dir = library.install_directory(game_id)
        existing_location_keys = tuple(
            location.path_key for location in save_repository.list_for_game(game_id)
        )
        return GuidedScoringContext(
            resolver=resolver,
            game_dir=game_dir,
            trusted_root_keys=tuple(
                windows_path_key(Path(scope.display_path)) for scope in scopes
            ),
            existing_location_keys=existing_location_keys,
            overflowed_root_keys=overflowed_root_keys,
            truncated_root_keys=truncated_root_keys,
        )

    guided_saves = GuidedSaveSessionService(
        repository=guided_repository,
        scope_builder=guided_scope_builder,
        registry_reader=RegistryMetadataReader(registry),
        watcher=cast(DirectoryWatcher, WindowsDirectoryWatcher()),
        launcher=launcher,
        process_tracker=cast(ProcessTracker, WindowsProcessTreeTracker()),
        scanner=BoundedMetadataScanner(),
        scoring_context_factory=guided_scoring_context,
        monotonic_ns=monotonic_ns,
    )
    guided_saves.recover_interrupted()
    guided_review = GuidedSaveReviewService(
        database, writer, guided_repository, save_locations
    )
    batch_repository = BatchSaveRepository(database, writer)
    batch_repository.recover_interrupted()
    batch_rule_provider = BatchRuleProvider(
        library=library,
        save_repository=save_repository,
        resolver=resolver,
        ludusavi_provider=ludusavi_provider,
        custom_provider=custom_provider,
        engine_hints=EngineSaveHintProvider(resolver),
        registry=registry,
    )
    batch_saves = BatchSaveDiscoveryService(
        repository=batch_repository,
        rule_provider=batch_rule_provider,
        scope_builder=BatchScopeBuilder(known_folders, lambda: config.current),
        scanner=BatchFilesystemScanner(),
        library=library,
        save_repository=save_repository,
    )
    batch_review = BatchSaveReviewService(
        database,
        writer,
        batch_repository,
        engine_ids=tuple(option.id for option in engine_detection.list_options()),
    )
    batch_external = BatchExternalLookup(batch_repository, shell)
    batch_candidate_opener = BatchCandidateOpener(batch_repository, shell)

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
        resource_paths.ui_dir,
        cover_lookup,
        managed_cover_roots=(paths.covers_original_dir, paths.covers_thumbs_dir),
        candidate_lookup=cover_wizard.preview_path,
        candidate_root=paths.temp_dir / "cover-wizard",
    )
    asset_address = asset_server.start()
    api = BridgeApi(
        paths,
        tasks,
        schema_version=schema_version,
        config=config,
        library=library,
        groups=groups,
        scanner=scanner,
        launcher=launcher,
        covers=covers,
        cover_wizard=cover_wizard,
        engine_detection=engine_detection,
        save_locations=save_locations,
        static_discovery=static_discovery,
        guided_saves=guided_saves,
        guided_repository=guided_repository,
        guided_review=guided_review,
        batch_repository=batch_repository,
        batch_saves=batch_saves,
        batch_review=batch_review,
        batch_external=batch_external,
        batch_candidate_opener=batch_candidate_opener,
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
        guided_saves=guided_saves,
        builtin_save_rules=builtin_save_rules,
        cover_wizard=cover_wizard,
        analysis_pool=analysis_pool,
    )


def _load_engine_detection(
    rules_file: Path,
    logger: logging.Logger,
) -> EngineDetectionService:
    try:
        return EngineDetectionService.from_rules_file(rules_file)
    except RuleSchemaError as error:
        if not rules_file.is_file() or isinstance(error.__cause__, OSError):
            raise
        logger.warning(
            "声明式引擎规则加载失败，已仅启用内置检测器（%s）：%s",
            rules_file,
            error,
        )
        return EngineDetectionService.builtins_only()


def _load_builtin_save_rules(
    rules_file: Path,
    resolver: PathTemplateResolver,
    logger: logging.Logger,
) -> BuiltinSaveRuleProvider:
    try:
        return BuiltinSaveRuleProvider.from_file(rules_file, resolver, logger)
    except SaveRuleSchemaError as error:
        if not rules_file.is_file() or isinstance(error.__cause__, OSError):
            raise
        logger.warning(
            "内置存档规则加载失败，已禁用该建议来源（%s）：%s",
            rules_file,
            error,
        )
        return BuiltinSaveRuleProvider.empty(resolver, logger)
