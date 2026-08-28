"""Composition root for portable GameSave Scout services."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Lock
from time import monotonic_ns
from typing import cast

from gamesave_scout.bootstrap.config import ConfigService, JsonConfigStore
from gamesave_scout.bootstrap.logging import configure_logging
from gamesave_scout.bootstrap.paths import AppPaths
from gamesave_scout.bootstrap.resources import ResourcePaths
from gamesave_scout.bridge.api import BridgeApi
from gamesave_scout.bridge.rule_controller import RuleBridgeController
from gamesave_scout.bridge.tasks import TaskRegistry
from gamesave_scout.covers.local_discovery import LocalCoverDiscovery
from gamesave_scout.covers.service import CoverService
from gamesave_scout.covers.vndb import VndbClient
from gamesave_scout.covers.wizard_service import CoverWizardService
from gamesave_scout.db.connection import ConnectionFactory
from gamesave_scout.db.migrator import Migrator
from gamesave_scout.db.writer import DbWriter
from gamesave_scout.library.group_repository import GroupRepository
from gamesave_scout.library.group_service import GroupService
from gamesave_scout.library.launcher import GameLauncher
from gamesave_scout.library.repository import LibraryRepository
from gamesave_scout.library.service import LibraryService
from gamesave_scout.platform.windows.directory_watcher import WindowsDirectoryWatcher
from gamesave_scout.platform.windows.known_folders import WindowsKnownFolderProvider
from gamesave_scout.platform.windows.process_tree import WindowsProcessTreeTracker
from gamesave_scout.platform.windows.processes import WindowsProcessLauncher
from gamesave_scout.platform.windows.registry import WindowsRegistry
from gamesave_scout.platform.windows.shell import WindowsShell
from gamesave_scout.rules.catalog import RuleCatalogService
from gamesave_scout.rules.import_export import RuleImportExportService
from gamesave_scout.rules.management import RuleManagementService
from gamesave_scout.rules.repository import UserRuleRepository
from gamesave_scout.rules.settings import RuleSettingsStore
from gamesave_scout.saves.batch_external import BatchCandidateOpener, BatchExternalLookup
from gamesave_scout.saves.batch_repository import BatchSaveRepository
from gamesave_scout.saves.batch_review import BatchSaveReviewService
from gamesave_scout.saves.batch_rules import BatchRuleProvider
from gamesave_scout.saves.batch_scanner import BatchFilesystemScanner
from gamesave_scout.saves.batch_scope import BatchScopeBuilder
from gamesave_scout.saves.batch_service import BatchSaveDiscoveryService
from gamesave_scout.saves.builtin_rules import SaveRuleProvider
from gamesave_scout.saves.engine_hints import EngineSaveHintProvider
from gamesave_scout.saves.guided_models import GuidedScopeOption
from gamesave_scout.saves.guided_registry import RegistryMetadataReader
from gamesave_scout.saves.guided_repository import GuidedSaveRepository
from gamesave_scout.saves.guided_review import GuidedSaveReviewService
from gamesave_scout.saves.guided_scanner import BoundedMetadataScanner
from gamesave_scout.saves.guided_scope import GuidedSaveScopeBuilder
from gamesave_scout.saves.guided_scoring import GuidedScoringContext
from gamesave_scout.saves.guided_service import (
    DirectoryWatcher,
    GuidedSaveSessionService,
    ProcessTracker,
)
from gamesave_scout.saves.ludusavi_provider import LudusaviProvider
from gamesave_scout.saves.repository import SaveLocationRepository
from gamesave_scout.saves.service import SaveLocationService
from gamesave_scout.saves.static_discovery import StaticSaveDiscovery
from gamesave_scout.saves.templates import PathTemplateResolver
from gamesave_scout.scanning.analysis_pool import ScanAnalysisPool
from gamesave_scout.scanning.path_keys import windows_path_key
from gamesave_scout.scanning.service import ScanService
from gamesave_scout.web.asset_server import AssetServer, AssetServerAddress


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
    builtin_save_rules: SaveRuleProvider
    rule_catalog: RuleCatalogService
    rule_management: RuleManagementService
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
    known_folders = WindowsKnownFolderProvider().load()
    resolver = PathTemplateResolver(known_folders)
    rule_settings_store = RuleSettingsStore(paths.rule_settings_file)
    rule_catalog = RuleCatalogService(
        builtin_engine_file=resource_paths.builtin_engine_rules_file,
        builtin_save_file=resource_paths.builtin_save_rules_file,
        repository=UserRuleRepository(
            paths.user_engine_rules_dir,
            paths.user_save_rules_dir,
            paths.temp_dir,
        ),
        settings_store=rule_settings_store,
        resolver=resolver,
        legacy_manifest_dir=paths.legacy_manifests_dir,
        logger=logger,
    )
    rule_snapshot = rule_catalog.snapshot()
    builtin_save_rules = rule_snapshot.save_rules
    for diagnostic in rule_snapshot.diagnostics:
        source_path = {
            "builtin/engines.yaml": resource_paths.builtin_engine_rules_file,
            "builtin/saves.yaml": resource_paths.builtin_save_rules_file,
        }.get(diagnostic.source_name, Path(diagnostic.source_name))
        logger.warning("%s（%s）", diagnostic.message, source_path)
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
        engine_detection_provider=lambda: (
            rule_catalog.snapshot().engine_detection
        ),
        analysis_pool=analysis_pool,
    )
    shell = WindowsShell()
    launcher = GameLauncher(repository, writer, WindowsProcessLauncher(), shell)
    covers = CoverService(
        paths,
        repository,
        writer,
        lambda: config.current.cover_optimize_enabled,
    )
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
    rule_management = RuleManagementService(
        catalog=rule_catalog,
        repository=rule_catalog.repository,
        resolver=resolver,
        library=library,
        save_repository=save_repository,
        registry=registry,
    )
    rule_import_export = RuleImportExportService(
        catalog=rule_catalog,
        repository=rule_catalog.repository,
    )
    ludusavi_provider = LudusaviProvider(
        resource_dir=resource_paths.ludusavi_dir,
        active_dir=paths.ludusavi_active_dir,
        temp_dir=paths.temp_dir,
    )
    static_discovery = StaticSaveDiscovery(
        library=library,
        save_repository=save_repository,
        resolver=resolver,
        ludusavi_provider=ludusavi_provider,
        engine_hints=EngineSaveHintProvider(resolver),
        rule_snapshot_provider=rule_catalog.snapshot,
        registry=registry,
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
        engine_hints=EngineSaveHintProvider(resolver),
        rule_snapshot_provider=rule_catalog.snapshot,
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
        engine_ids_provider=lambda: tuple(
            option.id
            for option in rule_catalog.snapshot().engine_detection.list_options()
        ),
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
    rule_controller = RuleBridgeController(
        management=rule_management,
        catalog=rule_catalog,
        import_export=rule_import_export,
        user_rule_directory=paths.user_rules_dir,
        legacy_manifest_directory=paths.legacy_manifests_dir,
        directory_opener=shell.open_directory,
        tasks=tasks,
        ludusavi_provider=ludusavi_provider,
        ludusavi_invalidator=static_discovery.invalidate_ludusavi,
    )
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
        rule_catalog=rule_catalog,
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
        rule_controller=rule_controller,
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
        rule_catalog=rule_catalog,
        rule_management=rule_management,
        cover_wizard=cover_wizard,
        analysis_pool=analysis_pool,
    )
