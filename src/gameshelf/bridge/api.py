"""Narrow, validated pywebview API exposed to the Vue frontend."""

from __future__ import annotations

import base64
import binascii
from pathlib import Path
from typing import Any, cast

from gameshelf.bootstrap.config import (
    AppConfig,
    BatchSaveCustomRoot,
    ConfigService,
    InvalidBatchSaveSettingsError,
    InvalidCoverWizardSettingsError,
    InvalidLibraryScanSettingsError,
    InvalidUiScaleError,
)
from gameshelf.bootstrap.paths import AppPaths
from gameshelf.bridge.contracts import ApiResult, JSONValue, failure, success
from gameshelf.bridge.rule_controller import RuleBridgeController
from gameshelf.bridge.tasks import (
    ActiveTaskConflict,
    TaskContext,
    TaskRegistry,
    TaskSnapshot,
)
from gameshelf.covers.candidates import (
    CoverCandidate,
    CoverWizardSnapshot,
)
from gameshelf.covers.image_pipeline import MAX_SOURCE_BYTES, InvalidCoverImage
from gameshelf.covers.service import CoverService
from gameshelf.covers.wizard_service import (
    ActiveCoverWizardError,
    CandidateSourceChangedError,
    CoverCandidateNotFoundError,
    CoverWizardBusyError,
    CoverWizardNotFoundError,
    CoverWizardService,
)
from gameshelf.engines.service import EngineDetectionService
from gameshelf.library.group_models import GameGroup, GroupMembershipMode
from gameshelf.library.group_service import (
    DuplicateGroupName,
    GroupLimitReached,
    GroupNotFoundError,
    GroupService,
    InvalidGroupMembership,
    InvalidGroupName,
)
from gameshelf.library.launcher import (
    GameLauncher,
    InvalidLaunchConfiguration,
)
from gameshelf.library.launcher import (
    GameNotFoundError as LauncherGameNotFoundError,
)
from gameshelf.library.models import (
    Game,
    GameRemovalRequest,
    RemovableGameStatus,
    ScanRoot,
)
from gameshelf.library.service import (
    GameNotFoundError,
    InvalidEngineConfiguration,
    InvalidExecutableError,
    InvalidGameConfiguration,
    InvalidGameRemoval,
    InvalidRootConfiguration,
    LibraryService,
    RootNotFoundError,
)
from gameshelf.rules.catalog import RuleCatalogService
from gameshelf.saves.batch_external import (
    BatchCandidateOpener,
    BatchCandidateOpenError,
    BatchExternalLookup,
    BatchExternalLookupError,
)
from gameshelf.saves.batch_models import BatchScanSummary
from gameshelf.saves.batch_repository import (
    BatchCandidatePage,
    BatchCandidateQuery,
    BatchSaveRepository,
    PersistedBatchCandidate,
)
from gameshelf.saves.batch_review import (
    BatchReviewError,
    BatchSaveReviewService,
    SaveOnlyDraft,
)
from gameshelf.saves.batch_service import BatchSaveDiscoveryService, BatchScanRequest
from gameshelf.saves.guided_models import (
    GuidedSaveDiscovery,
    GuidedSavePreview,
    GuidedSaveSession,
)
from gameshelf.saves.guided_repository import (
    ActiveGuidedSessionError,
    GuidedSaveRepository,
    GuidedSessionNotFoundError,
    InvalidGuidedSessionState,
)
from gameshelf.saves.guided_review import GuidedReviewError, GuidedSaveReviewService
from gameshelf.saves.guided_scope import InvalidGuidedScope
from gameshelf.saves.guided_service import (
    CloseResolution,
    GuidedSaveError,
    GuidedSaveSessionService,
)
from gameshelf.saves.ludusavi_provider import (
    LudusaviProvider,
    SnapshotUpdateError,
    UpdateResult,
)
from gameshelf.saves.models import SaveLocation, SaveLocationSuggestion
from gameshelf.saves.service import (
    InvalidSaveLocation,
    SaveLocationNotFoundError,
    SaveLocationOpenError,
    SaveLocationService,
)
from gameshelf.saves.static_discovery import StaticSaveDiscovery
from gameshelf.scanning.service import (
    ConfirmMoveError,
    GameReanalysisError,
    RootDisabledError,
    ScanService,
    ScanSummary,
)


class InvalidRequest(ValueError):
    """Raised when a bridge payload does not match its public JSON contract."""


class BridgeApi:
    def __init__(
        self,
        paths: AppPaths,
        tasks: TaskRegistry,
        *,
        schema_version: int,
        config: ConfigService | None = None,
        library: LibraryService | None = None,
        groups: GroupService | None = None,
        scanner: ScanService | None = None,
        launcher: GameLauncher | None = None,
        covers: CoverService | None = None,
        cover_wizard: CoverWizardService | None = None,
        engine_detection: EngineDetectionService | None = None,
        rule_catalog: RuleCatalogService | None = None,
        save_locations: SaveLocationService | None = None,
        static_discovery: StaticSaveDiscovery | None = None,
        guided_saves: GuidedSaveSessionService | None = None,
        guided_repository: GuidedSaveRepository | None = None,
        guided_review: GuidedSaveReviewService | None = None,
        batch_repository: BatchSaveRepository | None = None,
        batch_saves: BatchSaveDiscoveryService | None = None,
        batch_review: BatchSaveReviewService | None = None,
        batch_external: BatchExternalLookup | None = None,
        batch_candidate_opener: BatchCandidateOpener | None = None,
        ludusavi_provider: LudusaviProvider | None = None,
        rule_controller: RuleBridgeController | None = None,
        asset_session_token: str | None = None,
    ) -> None:
        self._paths = paths
        self._tasks = tasks
        self._schema_version = schema_version
        self._config = config
        self._library = library
        self._groups = groups
        self._scanner = scanner
        self._launcher = launcher
        self._covers = covers
        self._cover_wizard = cover_wizard
        self._engine_detection = engine_detection
        self._rule_catalog = rule_catalog
        self._save_locations = save_locations
        self._static_discovery = static_discovery
        self._guided_saves = guided_saves
        self._guided_repository = guided_repository
        self._guided_review = guided_review
        self._batch_repository = batch_repository
        self._batch_saves = batch_saves
        self._batch_review = batch_review
        self._batch_external = batch_external
        self._batch_candidate_opener = batch_candidate_opener
        self._ludusavi_provider = ludusavi_provider
        self._rule_controller = rule_controller
        self._asset_session_token = asset_session_token
        self._window: Any | None = None

    def attach_window(self, window: object) -> None:
        """Attach only the native window needed by whitelisted file dialogs."""
        self._window = window
        if self._rule_controller is not None:
            self._rule_controller.attach_window(window)

    def list_rules(self, request: object) -> ApiResult:
        return self._require_rule_controller().list_rules(request)

    def get_rule(self, request: object) -> ApiResult:
        return self._require_rule_controller().get_rule(request)

    def validate_rule_draft(self, request: object) -> ApiResult:
        return self._require_rule_controller().validate_rule_draft(request)

    def test_rule_draft(self, request: object) -> ApiResult:
        return self._require_rule_controller().test_rule_draft(request)

    def save_rule(self, request: object) -> ApiResult:
        return self._require_rule_controller().save_rule(request)

    def copy_rule(self, request: object) -> ApiResult:
        return self._require_rule_controller().copy_rule(request)

    def set_rule_enabled(self, request: object) -> ApiResult:
        return self._require_rule_controller().set_rule_enabled(request)

    def delete_rule(self, request: object) -> ApiResult:
        return self._require_rule_controller().delete_rule(request)

    def refresh_rules(self, request: object) -> ApiResult:
        return self._require_rule_controller().refresh_rules(request)

    def get_game_save_rule_prefill(self, request: object) -> ApiResult:
        return self._require_rule_controller().get_game_save_rule_prefill(request)

    def begin_rule_import(self, request: object) -> ApiResult:
        return self._require_rule_controller().begin_rule_import(request)

    def confirm_rule_import(self, request: object) -> ApiResult:
        return self._require_rule_controller().confirm_rule_import(request)

    def export_rule(self, request: object) -> ApiResult:
        return self._require_rule_controller().export_rule(request)

    def open_rule_directory(self, request: object) -> ApiResult:
        return self._require_rule_controller().open_rule_directory(request)

    def bootstrap(self) -> ApiResult:
        state: dict[str, JSONValue] = {
            "appName": "GameShelf",
            "schemaVersion": self._schema_version,
            "portable": True,
            "uiScale": self._config.current.ui_scale if self._config is not None else 1.0,
        }
        if self._asset_session_token is not None:
            state["assetSessionToken"] = self._asset_session_token
        if self._config is not None:
            state["libraryScanSettings"] = _library_scan_settings_dto(self._config.current)
            state["coverWizardSettings"] = _cover_wizard_settings_dto(self._config.current)
            state["batchSaveSettings"] = _batch_save_settings_dto(self._config.current)
        return success(state)

    def set_ui_scale(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            config = self._require_config().set_ui_scale(payload.get("uiScale"))
            return success({"uiScale": config.ui_scale})
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except InvalidUiScaleError as error:
            return failure("invalid_ui_scale", str(error))
        except OSError:
            return failure(
                "config_save_failed",
                "缩放设置保存失败，下次启动可能恢复默认值。",
            )

    def set_library_scan_settings(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"startupQuickScan", "scanConcurrency"})
            config = self._require_config().set_library_scan_settings(
                startup_quick_scan=_boolean(payload, "startupQuickScan"),
                scan_concurrency=_integer(payload, "scanConcurrency"),
            )
            return success(_library_scan_settings_dto(config))
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except InvalidLibraryScanSettingsError as error:
            return failure("invalid_library_scan_settings", str(error))
        except OSError:
            return failure(
                "config_save_failed",
                "游戏库扫描设置保存失败，下次启动可能恢复为原设置。",
            )

    def set_cover_wizard_settings(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(
                payload,
                {
                    "coverOnlineEnabled",
                    "coverVndbCandidateLimit",
                    "coverLocalScanCandidateLimit",
                },
            )
            config = self._require_config().set_cover_wizard_settings(
                online_enabled=_boolean(payload, "coverOnlineEnabled"),
                vndb_candidate_limit=_integer(payload, "coverVndbCandidateLimit"),
                local_scan_candidate_limit=_integer(payload, "coverLocalScanCandidateLimit"),
            )
            return success(_cover_wizard_settings_dto(config))
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except InvalidCoverWizardSettingsError as error:
            return failure("invalid_cover_wizard_settings", str(error))
        except OSError:
            return failure(
                "config_save_failed",
                "封面向导设置保存失败，下次启动可能恢复为原设置。",
            )

    def add_batch_save_custom_root(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"displayPath", "enabled", "maxDepth"})
            root = self._require_config().add_batch_save_custom_root(
                _string(payload, "displayPath"),
                enabled=_boolean(payload, "enabled"),
                max_depth=_integer(payload, "maxDepth"),
            )
            return success(_batch_save_custom_root_dto(root))
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except InvalidBatchSaveSettingsError as error:
            return failure("invalid_batch_save_settings", str(error))
        except OSError:
            return failure("config_save_failed", "批量存档目录设置保存失败。")

    def update_batch_save_custom_root(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"rootId", "enabled", "maxDepth"})
            root = self._require_config().update_batch_save_custom_root(
                _string(payload, "rootId"),
                enabled=_boolean(payload, "enabled"),
                max_depth=_integer(payload, "maxDepth"),
            )
            return success(_batch_save_custom_root_dto(root))
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except InvalidBatchSaveSettingsError as error:
            return failure("invalid_batch_save_settings", str(error))
        except OSError:
            return failure("config_save_failed", "批量存档目录设置保存失败。")

    def remove_batch_save_custom_root(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"rootId"})
            removed = self._require_config().remove_batch_save_custom_root(
                _string(payload, "rootId")
            )
            return success({"removed": removed})
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except InvalidBatchSaveSettingsError as error:
            return failure("invalid_batch_save_settings", str(error))
        except OSError:
            return failure("config_save_failed", "批量存档目录设置保存失败。")

    def choose_batch_save_custom_root(self) -> ApiResult:
        return success(self._choose_native_path(directory=True))

    def start_batch_save_scan(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"standardScopeIds", "customRootIds"})
            scan_request = BatchScanRequest(
                standard_scope_ids=tuple(_clean_string_list(payload, "standardScopeIds")),
                custom_root_ids=tuple(_clean_string_list(payload, "customRootIds")),
            )

            def operation(context: TaskContext) -> dict[str, JSONValue]:
                summary = self._require_batch_saves().run(scan_request, context)
                return _batch_scan_summary_dto(summary)

            task_id = self._tasks.submit(
                "batch_save_scan",
                operation,
                exclusive_group="disk_scan",
            )
            return success({"taskId": task_id})
        except (InvalidRequest, ValueError) as error:
            return failure("invalid_request", str(error))
        except ActiveTaskConflict:
            return failure(
                "disk_scan_active",
                "已有磁盘扫描正在运行，请等待完成或先取消。",
            )

    def current_batch_save_task(self) -> ApiResult:
        snapshot = self._tasks.latest_snapshot("batch_save_scan")
        return success(None if snapshot is None else self._snapshot_data(snapshot))

    def list_batch_save_candidates(self, request: object) -> ApiResult:
        try:
            query = _batch_candidate_query(request, paginated=True)
            page = self._require_batch_repository().list_candidates(query)
            return success(_batch_candidate_page_dto(page))
        except (InvalidRequest, ValueError) as error:
            return failure("invalid_request", str(error))

    def get_batch_save_candidate(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"candidateId"})
            candidate = self._require_batch_repository().get_candidate(
                _string(payload, "candidateId")
            )
            if candidate is None:
                return failure(
                    "batch_candidate_not_found",
                    "没有找到对应的批量存档候选。",
                )
            return success(_batch_candidate_dto(candidate))
        except (InvalidRequest, ValueError) as error:
            return failure("invalid_request", str(error))

    def select_batch_save_candidate_ids(self, request: object) -> ApiResult:
        try:
            query = _batch_candidate_query(request, paginated=False)
            candidate_ids = self._require_batch_repository().selectable_ids(
                query,
                limit=500,
            )
            return success({"candidateIds": list(candidate_ids)})
        except (InvalidRequest, ValueError) as error:
            return failure("invalid_request", str(error))

    def accept_batch_save_candidates(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"candidateIds", "confirmRegistry"})
            result = self._require_batch_review().accept(
                _batch_candidate_ids(payload),
                confirm_registry=_boolean(payload, "confirmRegistry"),
            )
            return success(
                {
                    "locations": [_save_location_dto(item) for item in result.locations],
                    "recordedCount": result.recorded_count,
                    "unchangedCount": result.unchanged_count,
                }
            )
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except BatchReviewError as error:
            return failure(error.code, str(error))

    def reassociate_batch_save_candidates(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"candidateIds", "gameId"})
            changed = self._require_batch_review().reassociate_many(
                _batch_candidate_ids(payload),
                _string(payload, "gameId"),
            )
            return success({"updatedCount": changed})
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except BatchReviewError as error:
            return failure(error.code, str(error))

    def ignore_batch_save_candidates(self, request: object) -> ApiResult:
        return self._set_batch_candidate_review(request, "ignore")

    def restore_batch_save_candidates(self, request: object) -> ApiResult:
        return self._set_batch_candidate_review(request, "restore")

    def clear_unavailable_batch_save_candidates(self, request: object) -> ApiResult:
        return self._set_batch_candidate_review(request, "clear")

    def create_batch_save_only_game(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(
                payload,
                {
                    "title",
                    "version",
                    "engineId",
                    "groupIds",
                    "candidateIds",
                    "confirmRegistry",
                },
            )
            game = self._require_batch_review().create_save_only(
                SaveOnlyDraft(
                    title=_string(payload, "title"),
                    version=_nullable_string(payload, "version"),
                    engine_id=_nullable_string(payload, "engineId"),
                    group_ids=tuple(_clean_string_list(payload, "groupIds")),
                    candidate_ids=_batch_candidate_ids(payload),
                    confirm_registry=_boolean(payload, "confirmRegistry"),
                )
            )
            return success(self._game_dto(game))
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except BatchReviewError as error:
            return failure(error.code, str(error))

    def open_batch_save_candidate(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"candidateId"})
            self._require_batch_candidate_opener().open(_string(payload, "candidateId"))
            return success({"opened": True})
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except BatchCandidateOpenError as error:
            return failure(error.code, str(error))
        except OSError as error:
            return failure("batch_candidate_open_failed", str(error))

    def open_batch_save_lookup(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"candidateId", "provider"})
            url = self._require_batch_external().open(
                _string(payload, "candidateId"),
                _string(payload, "provider"),
            )
            return success({"opened": True, "url": url})
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except BatchExternalLookupError as error:
            return failure(error.code, str(error))
        except OSError as error:
            return failure("batch_lookup_open_failed", str(error))

    def _set_batch_candidate_review(self, request: object, action: str) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"candidateIds"})
            ids = _batch_candidate_ids(payload)
            review = self._require_batch_review()
            if action == "ignore":
                changed = review.ignore(ids)
            elif action == "restore":
                changed = review.restore(ids)
            else:
                changed = review.clear_unavailable(ids)
            return success({"updatedCount": changed})
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except BatchReviewError as error:
            return failure(error.code, str(error))

    def start_cover_wizard(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"includeExisting"})
            snapshot = self._require_cover_wizard().start(
                _optional_boolean(payload, "includeExisting", default=False)
            )
            return success(_cover_wizard_snapshot_dto(snapshot))
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except ActiveCoverWizardError as error:
            return failure("cover_wizard_active", str(error))

    def cover_wizard_snapshot(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"sessionId"})
            snapshot = self._require_cover_wizard().snapshot(_string(payload, "sessionId"))
            return success(_cover_wizard_snapshot_dto(snapshot))
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except CoverWizardNotFoundError as error:
            return failure("cover_wizard_not_found", str(error))

    def set_cover_wizard_include_existing(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"sessionId", "includeExisting"})
            snapshot = self._require_cover_wizard().set_include_existing(
                _string(payload, "sessionId"),
                _boolean(payload, "includeExisting"),
            )
            return success(_cover_wizard_snapshot_dto(snapshot))
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except CoverWizardNotFoundError as error:
            return failure("cover_wizard_not_found", str(error))

    def list_cover_candidates(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"sessionId", "gameId"})
            session_id = _string(payload, "sessionId")
            candidates = self._require_cover_wizard().list_candidates(
                session_id, _string(payload, "gameId")
            )
            return success(
                [self._cover_candidate_dto(session_id, candidate) for candidate in candidates]
            )
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except CoverWizardNotFoundError as error:
            return failure("cover_wizard_not_found", str(error))
        except CoverCandidateNotFoundError as error:
            return failure("cover_candidate_not_found", str(error))

    def add_cover_candidate_bytes(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(
                payload,
                {"sessionId", "gameId", "source", "fileName", "contentType", "dataBase64"},
            )
            source = _string(payload, "source")
            if source not in {"clipboard", "drop"}:
                raise InvalidRequest("source must be 'clipboard' or 'drop'.")
            file_name = _string(payload, "fileName")
            if len(file_name) > 255 or "\x00" in file_name:
                raise InvalidRequest("fileName is too long or unsafe.")
            _string(payload, "contentType")
            encoded = _string(payload, "dataBase64")
            if len(encoded) > (MAX_SOURCE_BYTES * 4 // 3) + 8:
                raise InvalidRequest("dataBase64 exceeds the cover size limit.")
            try:
                decoded = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error) as error:
                raise InvalidRequest("dataBase64 is not valid base64.") from error
            candidate = self._require_cover_wizard().add_candidate_bytes(
                _string(payload, "sessionId"),
                _string(payload, "gameId"),
                file_name=file_name,
                payload=decoded,
                source=cast(Any, source),
            )
            session_id = _string(payload, "sessionId")
            return success(self._cover_candidate_dto(session_id, candidate))
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except InvalidCoverImage as error:
            return failure("invalid_cover", str(error))
        except CoverWizardNotFoundError as error:
            return failure("cover_wizard_not_found", str(error))
        except CoverWizardBusyError as error:
            return failure("cover_wizard_busy", str(error))
        except CoverCandidateNotFoundError as error:
            return failure("cover_candidate_not_found", str(error))

    def start_cover_vndb_search(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"sessionId", "gameIds", "limit"})
            if not self._require_config().current.cover_online_enabled:
                return failure("cover_online_disabled", "请先在封面向导设置中开启 VNDB。")
            session_id = _string(payload, "sessionId")
            game_ids = _clean_string_list(payload, "gameIds")
            if not game_ids or len(game_ids) > 500:
                raise InvalidRequest("gameIds must contain between 1 and 500 items.")
            limit = _integer(payload, "limit")
            if limit not in range(1, 21):
                raise InvalidRequest("limit must be between 1 and 20.")
            wizard = self._require_cover_wizard()

            def operation(context: TaskContext) -> dict[str, JSONValue]:
                if not self._require_config().current.cover_online_enabled:
                    raise RuntimeError("VNDB 已关闭。")
                snapshot = wizard.collect_vndb(session_id, game_ids, limit, context)
                failed = sum(
                    item.status == "failed" for item in snapshot.queue if item.game_id in game_ids
                )
                return {
                    "sessionId": session_id,
                    "completedCount": len(game_ids) - failed,
                    "failedCount": failed,
                }

            return success({"taskId": self._tasks.submit("cover_vndb_search", operation)})
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except CoverWizardNotFoundError as error:
            return failure("cover_wizard_not_found", str(error))
        except CoverWizardBusyError as error:
            return failure("cover_wizard_busy", str(error))

    def start_cover_shallow_scan(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"sessionId", "gameId", "limit"})
            session_id = _string(payload, "sessionId")
            game_id = _string(payload, "gameId")
            limit = _integer(payload, "limit")
            if limit not in range(1, 101):
                raise InvalidRequest("limit must be between 1 and 100.")
            wizard = self._require_cover_wizard()

            def operation(context: TaskContext) -> dict[str, JSONValue]:
                summary = wizard.collect_shallow(session_id, game_id, limit, context)
                candidate_count = len(summary.candidates)
                message = (
                    "浅层扫描完成，未找到候选封面。"
                    if candidate_count == 0
                    else f"浅层扫描完成，找到 {candidate_count} 张候选封面。"
                )
                context.report(1, 1, message)
                return {
                    "sessionId": session_id,
                    "completedCount": candidate_count,
                    "failedCount": summary.skipped,
                }

            return success({"taskId": self._tasks.submit("cover_shallow_scan", operation)})
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except CoverWizardNotFoundError as error:
            return failure("cover_wizard_not_found", str(error))
        except CoverWizardBusyError as error:
            return failure("cover_wizard_busy", str(error))

    def start_cover_directory_import(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"sessionId", "selectedPath"})
            session_id = _string(payload, "sessionId")
            directory = Path(_string(payload, "selectedPath"))
            wizard = self._require_cover_wizard()

            def operation(context: TaskContext) -> dict[str, JSONValue]:
                summaries = wizard.collect_directory(session_id, directory, context)
                return {
                    "sessionId": session_id,
                    "completedCount": sum(
                        len(summary.candidates) for summary in summaries.values()
                    ),
                    "failedCount": sum(summary.skipped for summary in summaries.values()),
                }

            return success({"taskId": self._tasks.submit("cover_directory_import", operation)})
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except CoverWizardNotFoundError as error:
            return failure("cover_wizard_not_found", str(error))
        except CoverWizardBusyError as error:
            return failure("cover_wizard_busy", str(error))

    def adopt_cover_candidate(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"sessionId", "candidateId"})
            session_id = _string(payload, "sessionId")
            wizard = self._require_cover_wizard()
            game = wizard.adopt(session_id, _string(payload, "candidateId"))
            return success(
                {
                    "game": self._game_dto(game),
                    "snapshot": _cover_wizard_snapshot_dto(wizard.snapshot(session_id)),
                }
            )
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except CoverWizardNotFoundError as error:
            return failure("cover_wizard_not_found", str(error))
        except CoverCandidateNotFoundError as error:
            return failure("cover_candidate_not_found", str(error))
        except CandidateSourceChangedError as error:
            return failure("cover_candidate_changed", str(error))
        except InvalidCoverImage as error:
            return failure("invalid_cover", str(error))

    def skip_cover_wizard_game(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"sessionId", "gameId"})
            snapshot = self._require_cover_wizard().skip(
                _string(payload, "sessionId"), _string(payload, "gameId")
            )
            return success(_cover_wizard_snapshot_dto(snapshot))
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except CoverWizardNotFoundError as error:
            return failure("cover_wizard_not_found", str(error))
        except CoverCandidateNotFoundError as error:
            return failure("cover_candidate_not_found", str(error))

    def close_cover_wizard(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"sessionId"})
            self._require_cover_wizard().close(_string(payload, "sessionId"))
            return success({"closed": True})
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except CoverWizardNotFoundError as error:
            return failure("cover_wizard_not_found", str(error))
        except CoverWizardBusyError as error:
            return failure("cover_wizard_busy", str(error))

    def list_roots(self) -> ApiResult:
        library = self._require_library()
        return success([_root_dto(root) for root in library.list_roots()])

    def add_root(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            root = self._require_library().add_root(
                _string(payload, "displayPath"),
                _scan_mode(payload),
                _integer(payload, "maxDepth"),
                _string_list(payload, "exclusions"),
            )
            return success(_root_dto(root))
        except (InvalidRequest, InvalidRootConfiguration) as error:
            return failure("invalid_request", str(error))

    def update_root(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            root = self._require_library().update_root(
                _string(payload, "rootId"),
                enabled=_boolean(payload, "enabled"),
                scan_mode=_scan_mode(payload),
                max_depth=_integer(payload, "maxDepth"),
                exclusions=_string_list(payload, "exclusions"),
            )
            return success(_root_dto(root))
        except (InvalidRequest, InvalidRootConfiguration) as error:
            return failure("invalid_request", str(error))
        except RootNotFoundError:
            return failure("root_not_found", "没有找到对应的游戏根目录。")

    def remove_root(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            self._require_library().remove_root(_string(payload, "rootId"))
            return success({"removed": True})
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except RootNotFoundError:
            return failure("root_not_found", "没有找到对应的游戏根目录。")

    def remap_root(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            root = self._require_library().remap_root(
                _string(payload, "rootId"), _string(payload, "displayPath")
            )
            return success(_root_dto(root))
        except (InvalidRequest, InvalidRootConfiguration) as error:
            return failure("invalid_request", str(error))
        except RootNotFoundError:
            return failure("root_not_found", "没有找到对应的游戏根目录。")

    def list_games(self) -> ApiResult:
        library = self._require_library()
        return success([self._game_dto(game) for game in library.list_games()])

    def list_game_groups(self) -> ApiResult:
        return success([_game_group_dto(group) for group in self._require_groups().list_groups()])

    def create_game_group(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"name"})
            group = self._require_groups().create_group(_string(payload, "name"))
            return success(_game_group_dto(group))
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except InvalidGroupName as error:
            return failure("invalid_game_group_operation", str(error))
        except DuplicateGroupName as error:
            return failure("duplicate_game_group", str(error))
        except GroupLimitReached as error:
            return failure("game_group_limit", str(error))

    def rename_game_group(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"groupId", "name"})
            group = self._require_groups().rename_group(
                _string(payload, "groupId"),
                _string(payload, "name"),
            )
            return success(_game_group_dto(group))
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except InvalidGroupName as error:
            return failure("invalid_game_group_operation", str(error))
        except DuplicateGroupName as error:
            return failure("duplicate_game_group", str(error))
        except GroupNotFoundError:
            return failure("game_group_not_found", "没有找到对应的游戏分组。")

    def delete_game_group(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"groupId"})
            self._require_groups().delete_group(_string(payload, "groupId"))
            return success({"deleted": True})
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except GroupNotFoundError:
            return failure("game_group_not_found", "没有找到对应的游戏分组。")

    def set_game_groups(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"gameId", "groupIds"})
            game = self._require_groups().set_game_groups(
                _string(payload, "gameId"),
                _clean_string_list(payload, "groupIds"),
            )
            return success(self._game_dto(game))
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except GroupNotFoundError:
            return failure("game_group_not_found", "没有找到对应的游戏分组。")
        except GameNotFoundError:
            return failure("game_not_found", "没有找到对应的游戏。")

    def update_game_group_memberships(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"groupId", "gameIds", "mode"})
            mode = _string(payload, "mode")
            if mode not in {"add", "remove"}:
                raise InvalidRequest("mode must be add or remove.")
            result = self._require_groups().update_memberships(
                _string(payload, "groupId"),
                _clean_string_list(payload, "gameIds"),
                cast(GroupMembershipMode, mode),
            )
            return success(
                {
                    "addedCount": result.added_count,
                    "removedCount": result.removed_count,
                    "unchangedCount": result.unchanged_count,
                }
            )
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except InvalidGroupMembership as error:
            return failure("invalid_game_group_operation", str(error))
        except GroupNotFoundError:
            return failure("game_group_not_found", "没有找到对应的游戏分组。")
        except GameNotFoundError:
            return failure("game_not_found", "没有找到对应的游戏。")

    def remove_game_and_exclude(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            game_id = _string(payload, "gameId")
            library = self._require_library()
            result = library.remove_games((GameRemovalRequest(game_id, "installed"),))
            if self._covers is not None:
                self._covers.cleanup_managed_files(result.managed_cover_relpaths)
            return success({"removed": True})
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except InvalidGameRemoval as error:
            return failure("invalid_game_state", str(error))
        except GameNotFoundError:
            return failure("game_not_found", "没有找到对应的游戏。")

    def delete_missing_game(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            game_id = _string(payload, "gameId")
            library = self._require_library()
            result = library.remove_games((GameRemovalRequest(game_id, "missing"),))
            if self._covers is not None:
                self._covers.cleanup_managed_files(result.managed_cover_relpaths)
            return success({"removed": True})
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except InvalidGameRemoval as error:
            return failure("invalid_game_state", str(error))
        except GameNotFoundError:
            return failure("game_not_found", "没有找到对应的游戏。")

    def remove_games(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            result = self._require_library().remove_games(_game_removal_requests(payload))
            cleanup_warning_count = (
                self._covers.cleanup_managed_files(result.managed_cover_relpaths)
                if self._covers is not None
                else 0
            )
            cleanup_warnings: list[JSONValue] = []
            if cleanup_warning_count:
                cleanup_warnings.append(
                    f"有 {cleanup_warning_count} 个受管封面文件未能清理，可稍后查看日志。"
                )
            return success(
                {
                    "installedCount": result.installed_count,
                    "missingCount": result.missing_count,
                    "updatedRootCount": len(result.updated_roots),
                    "cleanupWarnings": cleanup_warnings,
                }
            )
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except GameNotFoundError:
            return failure("game_not_found", "至少有一个所选游戏已不存在，请刷新后重新选择。")
        except (InvalidGameRemoval, RootNotFoundError) as error:
            return failure("invalid_game_state", str(error))

    def start_scan(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"rootId", "kind"})
            root_id = _string(payload, "rootId")
            kind = _string(payload, "kind")
            if kind not in {"quick", "full"}:
                raise InvalidRequest("kind must be 'quick' or 'full'.")
            root = next(
                (item for item in self._require_library().list_roots() if item.id == root_id),
                None,
            )
            if root is None:
                raise RootNotFoundError(root_id)
            if not root.enabled:
                raise RootDisabledError("该游戏目录未参与扫描。")
            scanner = self._require_scanner()
            task_id = self._tasks.submit(
                "library_scan",
                lambda context: _scan_summary_dto(
                    scanner.scan_root(root_id, cast(Any, kind), context)
                ),
                exclusive_group="disk_scan",
            )
            return success({"taskId": task_id})
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except RootNotFoundError:
            return failure("root_not_found", "没有找到对应的游戏目录。")
        except RootDisabledError as error:
            return failure("root_disabled", str(error))
        except ActiveTaskConflict:
            return failure(
                "disk_scan_active",
                "已有磁盘扫描正在运行，请等待完成或先取消。",
            )

    def start_game_reanalysis(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"gameId"})
            game_id = _string(payload, "gameId")
            library = self._require_library()
            game = library.get_game(game_id)
            if game is None:
                raise GameNotFoundError(game_id)
            if game.status != "installed" or game.scan_root_id is None or game.relative_dir is None:
                raise GameReanalysisError("只有安装目录可用的已安装游戏可以重新检测。")
            install_dir = library.install_directory(game_id)
            if not install_dir.is_dir():
                raise GameReanalysisError("游戏安装目录当前不可访问。")
            scanner = self._require_scanner()
            task_id = self._tasks.submit(
                "game_reanalysis",
                lambda context: self._game_dto(scanner.reanalyze_game(game_id, context)),
            )
            return success({"taskId": task_id})
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except GameNotFoundError:
            return failure("game_not_found", "没有找到对应的游戏。")
        except (InvalidGameConfiguration, GameReanalysisError) as error:
            return failure("invalid_game_state", str(error))

    def confirm_move(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            game = self._require_scanner().confirm_move(
                _string(payload, "sessionId"),
                _string(payload, "existingGameId"),
                _string(payload, "candidateRelativeDir"),
            )
            return success(self._game_dto(game))
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except ConfirmMoveError as error:
            return failure("invalid_move", str(error))

    def set_game_metadata(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"gameId", "title", "version"})
            if "version" not in payload:
                raise InvalidRequest("version is required.")
            version = payload["version"]
            if version is not None and not isinstance(version, str):
                raise InvalidRequest("version must be a string or null.")
            game = self._require_library().set_game_metadata(
                _string(payload, "gameId"),
                _string(payload, "title"),
                version,
            )
            return success(self._game_dto(game))
        except (InvalidRequest, InvalidGameConfiguration) as error:
            return failure("invalid_request", str(error))
        except GameNotFoundError:
            return failure("game_not_found", "没有找到对应的游戏。")

    def set_game_executable(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            game = self._require_library().set_game_executable(
                _string(payload, "gameId"), _string(payload, "selectedPath")
            )
            return success(self._game_dto(game))
        except (InvalidRequest, InvalidExecutableError) as error:
            return failure("invalid_executable", str(error))
        except GameNotFoundError:
            return failure("game_not_found", "没有找到对应的游戏。")

    def list_engine_options(self) -> ApiResult:
        options = self._require_engine_detection().list_options()
        return success(
            [
                {
                    "id": option.id,
                    "label": option.label,
                    "experimental": option.experimental,
                }
                for option in options
            ]
        )

    def set_game_engine(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            game_id = _string(payload, "gameId")
            requested = _string(payload, "engineId")
            if requested == "unknown":
                engine_id = None
            elif requested == "custom":
                label = _string(payload, "customLabel").strip()
                if len(label) > 80 or "\x00" in label:
                    raise InvalidRequest("customLabel must be at most 80 characters.")
                engine_id = f"custom:{label}"
            elif self._require_engine_detection().has_option(requested):
                engine_id = requested
            else:
                raise InvalidRequest("engineId is not a supported engine option.")
            game = self._require_library().set_game_engine(game_id, engine_id)
            return success(self._game_dto(game))
        except (InvalidRequest, InvalidEngineConfiguration) as error:
            return failure("invalid_engine", str(error))
        except GameNotFoundError:
            return failure("game_not_found", "没有找到对应的游戏。")

    def clear_manual_engine(self, request: object) -> ApiResult:
        try:
            game_id = _string(_payload(request), "gameId")
            game = self._require_library().clear_manual_engine(game_id)
            return success(self._game_dto(game))
        except (InvalidRequest, InvalidEngineConfiguration) as error:
            return failure("invalid_engine", str(error))
        except GameNotFoundError:
            return failure("game_not_found", "没有找到对应的游戏。")

    def update_launch_configuration(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            working = payload.get("workingDirRelpath")
            if working is not None and not isinstance(working, str):
                raise InvalidRequest("workingDirRelpath must be a string or null.")
            environment = payload.get("environment")
            if not isinstance(environment, dict) or not all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in environment.items()
            ):
                raise InvalidRequest("environment must contain string keys and values.")
            game = self._require_library().update_launch_configuration(
                _string(payload, "gameId"),
                working_dir_relpath=working,
                launch_args=_string_list(payload, "launchArgs"),
                environment=cast(dict[str, str], environment),
            )
            return success(self._game_dto(game))
        except (InvalidRequest, InvalidGameConfiguration) as error:
            return failure("invalid_request", str(error))
        except GameNotFoundError:
            return failure("game_not_found", "没有找到对应的游戏。")

    def launch_game(self, request: object) -> ApiResult:
        try:
            receipt = self._require_launcher().launch(_string(_payload(request), "gameId"))
            return success(
                {
                    "gameId": receipt.game_id,
                    "pid": receipt.pid,
                    "launchedAt": receipt.launched_at,
                }
            )
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except (InvalidLaunchConfiguration, LauncherGameNotFoundError) as error:
            return failure("launch_failed", str(error))

    def choose_cover_file(self, request: object) -> ApiResult:
        try:
            _payload(request)
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        return success(
            self._choose_native_path(
                directory=False,
                file_types=("Images (*.png;*.jpg;*.jpeg;*.webp;*.bmp)",),
            )
        )

    def set_cover_from_file(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            game_id = _string(payload, "gameId")
            self._require_covers().import_file(game_id, Path(_string(payload, "selectedPath")))
            return success(self._game_dto(self._require_game(game_id)))
        except (InvalidRequest, InvalidCoverImage) as error:
            return failure("invalid_cover", str(error))
        except GameNotFoundError:
            return failure("game_not_found", "没有找到对应的游戏。")

    def set_cover_from_clipboard(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            game_id = _string(payload, "gameId")
            encoded = _string(payload, "pngBase64")
            if len(encoded) > (MAX_SOURCE_BYTES * 4 // 3) + 8:
                raise InvalidCoverImage("Clipboard image exceeds the 50 MiB limit.")
            try:
                png_bytes = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error) as error:
                raise InvalidCoverImage("Clipboard image is not valid base64.") from error
            if len(png_bytes) > MAX_SOURCE_BYTES:
                raise InvalidCoverImage("Clipboard image exceeds the 50 MiB limit.")
            self._require_covers().import_clipboard_png(game_id, png_bytes)
            return success(self._game_dto(self._require_game(game_id)))
        except (InvalidRequest, InvalidCoverImage) as error:
            return failure("invalid_cover", str(error))
        except GameNotFoundError:
            return failure("game_not_found", "没有找到对应的游戏。")

    def remove_cover(self, request: object) -> ApiResult:
        try:
            game_id = _string(_payload(request), "gameId")
            self._require_covers().remove(game_id)
            return success(self._game_dto(self._require_game(game_id)))
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except GameNotFoundError:
            return failure("game_not_found", "没有找到对应的游戏。")

    def open_install_directory(self, request: object) -> ApiResult:
        try:
            self._require_launcher().open_install_directory(_string(_payload(request), "gameId"))
            return success({"opened": True})
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except (InvalidLaunchConfiguration, LauncherGameNotFoundError) as error:
            return failure("open_failed", str(error))

    def list_save_locations(self, request: object) -> ApiResult:
        try:
            game_id = _string(_payload(request), "gameId")
            locations = self._require_save_locations().list_for_game(game_id)
            return success([_save_location_dto(location) for location in locations])
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except GameNotFoundError:
            return failure("game_not_found", "没有找到对应的游戏。")

    def choose_save_path(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _string(payload, "gameId")
            kind = _save_kind(payload)
            if kind == "registry":
                raise InvalidSaveLocation("注册表位置请直接输入完整键路径。")
            initial: Path | None = None
            if self._library is not None:
                try:
                    initial = self._library.install_directory(_string(payload, "gameId"))
                except (GameNotFoundError, InvalidGameConfiguration):
                    initial = None
            return success(
                self._choose_native_path(
                    directory=kind in {"directory", "glob"},
                    initial=initial,
                    file_types=("所有文件 (*.*)",),
                )
            )
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except InvalidSaveLocation as error:
            return failure("invalid_save_location", str(error))

    def add_manual_save_location(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            location = self._require_save_locations().add_manual(
                _string(payload, "gameId"),
                _save_kind(payload),
                _string(payload, "selectedPath"),
            )
            return success(_save_location_dto(location))
        except (InvalidRequest, InvalidSaveLocation) as error:
            return failure("invalid_save_location", str(error))
        except GameNotFoundError:
            return failure("game_not_found", "没有找到对应的游戏。")

    def remove_save_location(self, request: object) -> ApiResult:
        try:
            location_id = _string(_payload(request), "locationId")
            self._require_save_locations().remove(location_id)
            return success({"removed": True})
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except SaveLocationNotFoundError:
            return failure("save_location_not_found", "没有找到对应的存档位置。")

    def verify_save_locations(self, request: object) -> ApiResult:
        try:
            game_id = _string(_payload(request), "gameId")
            locations = self._require_save_locations().verify_game(game_id)
            return success([_save_location_dto(location) for location in locations])
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except GameNotFoundError:
            return failure("game_not_found", "没有找到对应的游戏。")

    def open_save_location(self, request: object) -> ApiResult:
        try:
            self._require_save_locations().open_location(_string(_payload(request), "locationId"))
            return success({"opened": True})
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except SaveLocationNotFoundError:
            return failure("save_location_not_found", "没有找到对应的存档位置。")
        except (InvalidSaveLocation, SaveLocationOpenError, OSError) as error:
            return failure("open_failed", str(error))

    def suggest_save_locations(self, request: object) -> ApiResult:
        try:
            game_id = _string(_payload(request), "gameId")
            suggestions = self._require_static_discovery().suggest_for_game(game_id)
            return success([_save_suggestion_dto(item) for item in suggestions])
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except GameNotFoundError:
            return failure("game_not_found", "没有找到对应的游戏。")
        except (SnapshotUpdateError, OSError, ValueError) as error:
            return failure("save_discovery_failed", str(error))

    def accept_save_suggestions(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            game_id = _string(payload, "gameId")
            requested_ids = _string_list(payload, "suggestionIds")
            if not requested_ids:
                raise InvalidRequest("suggestionIds 至少需要一个项目。")
            suggestions = {
                item.suggestion_id: item
                for item in self._require_static_discovery().suggest_for_game(game_id)
                if item.suggestion_id is not None
            }
            if any(item_id not in suggestions for item_id in requested_ids):
                raise InvalidRequest("存档建议已经失效，请刷新后重试。")
            selected = [suggestions[item_id] for item_id in dict.fromkeys(requested_ids)]
            if any(item.kind == "registry" for item in selected) and not _optional_boolean(
                payload, "confirmRegistry", default=False
            ):
                return failure(
                    "registry_confirmation_required",
                    "注册表建议需要额外确认后才能接受。",
                )
            accepted = [
                self._require_save_locations().accept_suggestion(game_id, suggestion)
                for suggestion in selected
            ]
            return success([_save_location_dto(item) for item in accepted])
        except (InvalidRequest, InvalidSaveLocation) as error:
            return failure("invalid_save_location", str(error))
        except GameNotFoundError:
            return failure("game_not_found", "没有找到对应的游戏。")

    def preview_guided_save_detection(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"gameId"})
            preview = self._require_guided_saves().preview(_string(payload, "gameId"))
            return success(_guided_preview_dto(preview))
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except GameNotFoundError:
            return failure("game_not_found", "没有找到对应的游戏。")
        except InvalidGuidedScope as error:
            return failure("invalid_guided_scope", str(error))
        except OSError:
            return failure("guided_operation_failed", "引导式寻找操作失败。")

    def start_guided_save_detection(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"gameId", "selectedScopeIds", "additionalDirectories"})
            game_id = _string(payload, "gameId")
            selected = tuple(_clean_string_list(payload, "selectedScopeIds"))
            additional = tuple(_clean_string_list(payload, "additionalDirectories"))
            if not selected and not additional:
                return failure("guided_scope_empty", "至少选择一个监控范围。")
            session = self._require_guided_saves().start(game_id, selected, additional)
            return success(self._guided_session_dto(session))
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except GameNotFoundError:
            return failure("game_not_found", "没有找到对应的游戏。")
        except InvalidGuidedScope as error:
            return failure("invalid_guided_scope", str(error))
        except ActiveGuidedSessionError:
            return failure("guided_session_active", "已有游戏正在引导式寻找存档。")
        except GuidedSaveError as error:
            return _guided_service_failure(error)
        except OSError:
            return failure("guided_operation_failed", "引导式寻找操作失败。")

    def current_guided_save_detection(self) -> ApiResult:
        try:
            session = self._require_guided_saves().current()
            return success(None if session is None else self._guided_session_dto(session))
        except GameNotFoundError:
            return failure("game_not_found", "没有找到对应的游戏。")
        except GuidedSaveError as error:
            return _guided_service_failure(error)

    def guided_save_detection_status(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"sessionId"})
            session = self._require_guided_saves().status(_string(payload, "sessionId"))
            return success(self._guided_session_dto(session))
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except GameNotFoundError:
            return failure("game_not_found", "没有找到对应的游戏。")
        except GuidedSaveError as error:
            return _guided_service_failure(error)

    def latest_guided_save_detection_for_game(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"gameId"})
            game_id = _string(payload, "gameId")
            self._require_game(game_id)
            session = self._require_guided_saves().latest_for_game(game_id)
            return success(None if session is None else self._guided_session_dto(session))
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except GameNotFoundError:
            return failure("game_not_found", "没有找到对应的游戏。")
        except GuidedSaveError as error:
            return _guided_service_failure(error)

    def mark_guided_save_saved(self, request: object) -> ApiResult:
        return self._guided_session_command(request, "mark")

    def stop_guided_save_detection(self, request: object) -> ApiResult:
        return self._guided_session_command(request, "stop")

    def cancel_guided_save_detection(self, request: object) -> ApiResult:
        return self._guided_session_command(request, "cancel")

    def list_guided_save_discoveries(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"sessionId"})
            session_id = _string(payload, "sessionId")
            self._require_guided_saves().status(session_id)
            discoveries = self._require_guided_repository().list_discoveries(session_id)
            return success([_guided_discovery_dto(item) for item in discoveries])
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except GuidedSaveError as error:
            return _guided_service_failure(error)
        except OSError:
            return failure("guided_operation_failed", "引导式寻找操作失败。")

    def accept_guided_save_discoveries(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"sessionId", "discoveryIds", "confirmRegistry"})
            locations = self._require_guided_review().accept(
                _string(payload, "sessionId"),
                tuple(_clean_string_list(payload, "discoveryIds")),
                _boolean(payload, "confirmRegistry"),
            )
            return success([_save_location_dto(item) for item in locations])
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except GameNotFoundError:
            return failure("game_not_found", "没有找到对应的游戏。")
        except InvalidSaveLocation:
            return failure("guided_discovery_invalid", "引导式存档候选已经失效，请刷新后重试。")
        except GuidedReviewError as error:
            return _guided_review_failure(error)
        except OSError:
            return failure("guided_operation_failed", "引导式寻找操作失败。")

    def discard_guided_save_detection(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"sessionId"})
            discarded = self._require_guided_review().discard(_string(payload, "sessionId"))
            return success({"discarded": discarded})
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except GuidedSessionNotFoundError:
            return failure("guided_session_not_found", "找不到引导式寻找会话。")
        except InvalidGuidedSessionState:
            return failure("guided_session_not_reviewable", "该引导式寻找会话尚不能审核。")
        except GuidedReviewError as error:
            return _guided_review_failure(error)

    def resolve_guided_close(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"resolution"})
            resolution = _string(payload, "resolution")
            self._require_guided_saves().resolve_close(cast(CloseResolution, resolution))
            return success({"resolved": True})
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except GuidedSaveError as error:
            return _guided_service_failure(error)

    def _guided_session_command(self, request: object, command: str) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"sessionId"})
            session_id = _string(payload, "sessionId")
            guided = self._require_guided_saves()
            if command == "mark":
                session = guided.mark_saved(session_id)
            elif command == "stop":
                session = guided.stop_and_analyze(session_id)
            else:
                session = guided.cancel(session_id)
            return success(self._guided_session_dto(session))
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except GameNotFoundError:
            return failure("game_not_found", "没有找到对应的游戏。")
        except GuidedSaveError as error:
            return _guided_service_failure(error)
        except InvalidGuidedSessionState:
            return failure("guided_session_not_active", "该引导式寻找会话当前不能执行此操作。")
        except OSError:
            return failure("guided_operation_failed", "引导式寻找操作失败。")

    def ludusavi_status(self) -> ApiResult:
        try:
            metadata = self._require_ludusavi_provider().metadata()
        except (SnapshotUpdateError, OSError) as error:
            available = False
            unavailable_reason: str | None = str(error)
            source_url = downloaded_at = sha256 = etag = upstream_commit = None
        else:
            available = True
            unavailable_reason = None
            source_url = metadata.source_url
            downloaded_at = metadata.downloaded_at
            sha256 = metadata.sha256
            etag = metadata.etag
            upstream_commit = metadata.upstream_commit
        return success(
            {
                "available": available,
                "unavailableReason": unavailable_reason,
                "sourceUrl": source_url,
                "downloadedAt": downloaded_at,
                "sha256": sha256,
                "etag": etag,
                "upstreamCommit": upstream_commit,
            }
        )

    def update_ludusavi(self, request: object) -> ApiResult:
        try:
            _payload(request)
            provider = self._require_ludusavi_provider()
            discovery = self._require_static_discovery()

            def operation(context: TaskContext) -> dict[str, JSONValue]:
                stage_messages = {
                    "connecting": "正在连接 Ludusavi 数据源……",
                    "downloading": "正在下载 Ludusavi 清单……",
                    "validating": "正在验证下载的清单……",
                    "indexing": "正在生成 Ludusavi 查找索引……",
                    "replacing": "正在替换当前有效清单……",
                }

                def report(stage: str) -> None:
                    context.report(0, 1, stage_messages[stage])

                result = provider.update_explicitly(report)
                if result.status == "updated":
                    discovery.invalidate_ludusavi()
                context.report(1, 1, result.message)
                return _update_result_dto(result)

            task_id = self._tasks.submit("ludusavi_update", operation)
            return success({"taskId": task_id})
        except InvalidRequest as error:
            return failure("invalid_request", str(error))

    def choose_directory(self) -> ApiResult:
        return success(self._choose_native_path(directory=True))

    def choose_game_executable(self, request: object) -> ApiResult:
        try:
            game_id = _string(_payload(request), "gameId")
            initial = self._require_library().install_directory(game_id)
            return success(self._choose_native_path(directory=False, initial=initial))
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except (GameNotFoundError, InvalidGameConfiguration) as error:
            return failure("game_not_found", str(error))

    def task_snapshot(self, task_id: str) -> ApiResult:
        try:
            snapshot = self._tasks.get_snapshot(task_id)
        except KeyError:
            return failure("task_not_found", "没有找到对应的后台任务。")
        return success(self._snapshot_data(snapshot))

    def cancel_task(self, task_id: str) -> ApiResult:
        try:
            self._tasks.get_snapshot(task_id)
        except KeyError:
            return failure("task_not_found", "没有找到对应的后台任务。")
        return success({"cancelled": self._tasks.cancel(task_id)})

    def _choose_native_path(
        self,
        *,
        directory: bool,
        initial: Path | None = None,
        file_types: tuple[str, ...] | None = None,
    ) -> str | None:
        if self._window is None:
            return None
        import webview

        dialog_type = webview.FOLDER_DIALOG if directory else webview.OPEN_DIALOG
        options: dict[str, object] = {"allow_multiple": False}
        if initial is not None:
            options["directory"] = str(initial)
        if not directory:
            options["file_types"] = file_types or ("Windows 可执行文件 (*.exe)",)
        selected = self._window.create_file_dialog(dialog_type, **options)
        if not selected:
            return None
        return str(selected[0])

    def _game_dto(self, game: Game) -> dict[str, JSONValue]:
        engine_detection = self._engine_detection_or_none()
        install_path: str | None
        try:
            install_path = str(self._require_library().install_directory(game.id))
        except InvalidGameConfiguration:
            install_path = None
        return {
            "id": game.id,
            "scanRootId": game.scan_root_id,
            "relativeDir": game.relative_dir,
            "installPath": install_path,
            "title": game.title,
            "version": game.version,
            "status": game.status,
            "engineId": game.engine_id,
            "engineVariant": game.engine_variant,
            "engineLabel": self._engine_label(game.engine_id, engine_detection),
            "engineExperimental": (
                engine_detection.is_experimental(game.engine_id)
                if engine_detection is not None
                else False
            ),
            "engineIsManual": game.engine_is_manual,
            "detectedEngine": self._detected_engine_dto(game, engine_detection),
            "mainExeRelpath": game.main_exe_relpath,
            "mainExeIsManual": game.main_exe_is_manual,
            "workingDirRelpath": game.working_dir_relpath,
            "launchArgs": list(game.launch_args),
            "environment": dict(game.environment),
            "exeArch": game.exe_arch,
            "coverRevision": game.cover_revision,
            "coverThumbUrl": self._cover_url(game, "thumb"),
            "coverOriginalUrl": self._cover_url(game, "original"),
            "lastLaunchedAt": game.last_launched_at,
            "missingSince": game.missing_since,
            "groupIds": list(game.group_ids),
        }

    def _require_library(self) -> LibraryService:
        if self._library is None:
            raise RuntimeError("Library services are not configured.")
        return self._library

    def _require_groups(self) -> GroupService:
        if self._groups is None:
            raise RuntimeError("Game-group services are not configured.")
        return self._groups

    def _require_scanner(self) -> ScanService:
        if self._scanner is None:
            raise RuntimeError("Scan services are not configured.")
        return self._scanner

    def _require_launcher(self) -> GameLauncher:
        if self._launcher is None:
            raise RuntimeError("Launch services are not configured.")
        return self._launcher

    def _require_covers(self) -> CoverService:
        if self._covers is None:
            raise RuntimeError("Cover services are not configured.")
        return self._covers

    def _require_cover_wizard(self) -> CoverWizardService:
        if self._cover_wizard is None:
            raise RuntimeError("Cover wizard services are not configured.")
        return self._cover_wizard

    def _cover_candidate_dto(
        self, session_id: str, candidate: CoverCandidate
    ) -> dict[str, JSONValue]:
        preview_url = (
            None
            if self._asset_session_token is None
            else (f"/session/{self._asset_session_token}/candidate/{session_id}/{candidate.id}")
        )
        return {
            "id": candidate.id,
            "gameId": candidate.game_id,
            "source": candidate.source,
            "sourceLabel": candidate.source_label,
            "displayName": candidate.display_name,
            "width": candidate.width,
            "height": candidate.height,
            "matchKind": candidate.match_kind,
            "score": candidate.score,
            "evidence": list(candidate.evidence),
            "previewUrl": preview_url,
            "vndbId": candidate.vndb_id,
        }

    def _require_config(self) -> ConfigService:
        if self._config is None:
            raise RuntimeError("Portable configuration is not configured.")
        return self._config

    def _require_engine_detection(self) -> EngineDetectionService:
        engine_detection = self._engine_detection_or_none()
        if engine_detection is None:
            raise RuntimeError("Engine detection services are not configured.")
        return engine_detection

    def _engine_detection_or_none(self) -> EngineDetectionService | None:
        if self._rule_catalog is not None:
            return self._rule_catalog.snapshot().engine_detection
        return self._engine_detection

    def _require_save_locations(self) -> SaveLocationService:
        if self._save_locations is None:
            raise RuntimeError("Save-location services are not configured.")
        return self._save_locations

    def _require_guided_saves(self) -> GuidedSaveSessionService:
        if self._guided_saves is None:
            raise RuntimeError("Guided save services are not configured.")
        return self._guided_saves

    def _require_guided_repository(self) -> GuidedSaveRepository:
        if self._guided_repository is None:
            raise RuntimeError("Guided save repository is not configured.")
        return self._guided_repository

    def _require_guided_review(self) -> GuidedSaveReviewService:
        if self._guided_review is None:
            raise RuntimeError("Guided save review is not configured.")
        return self._guided_review

    def _require_batch_repository(self) -> BatchSaveRepository:
        if self._batch_repository is None:
            raise RuntimeError("Batch save repository is not configured.")
        return self._batch_repository

    def _require_batch_saves(self) -> BatchSaveDiscoveryService:
        if self._batch_saves is None:
            raise RuntimeError("Batch save discovery is not configured.")
        return self._batch_saves

    def _require_batch_review(self) -> BatchSaveReviewService:
        if self._batch_review is None:
            raise RuntimeError("Batch save review is not configured.")
        return self._batch_review

    def _require_batch_external(self) -> BatchExternalLookup:
        if self._batch_external is None:
            raise RuntimeError("Batch save external lookup is not configured.")
        return self._batch_external

    def _require_batch_candidate_opener(self) -> BatchCandidateOpener:
        if self._batch_candidate_opener is None:
            raise RuntimeError("Batch save candidate opener is not configured.")
        return self._batch_candidate_opener

    def _require_static_discovery(self) -> StaticSaveDiscovery:
        if self._static_discovery is None:
            raise RuntimeError("Static save discovery is not configured.")
        return self._static_discovery

    def _require_ludusavi_provider(self) -> LudusaviProvider:
        if self._ludusavi_provider is None:
            raise RuntimeError("Ludusavi provider is not configured.")
        return self._ludusavi_provider

    def _require_rule_controller(self) -> RuleBridgeController:
        if self._rule_controller is None:
            raise RuntimeError("Rule management is not configured.")
        return self._rule_controller

    def _engine_label(
        self,
        engine_id: str | None,
        engine_detection: EngineDetectionService | None,
    ) -> str:
        if engine_detection is not None:
            return engine_detection.label_for(engine_id)
        if engine_id is None:
            return "未知引擎"
        return engine_id.removeprefix("custom:")

    def _detected_engine_dto(
        self,
        game: Game,
        engine_detection: EngineDetectionService | None,
    ) -> dict[str, JSONValue] | None:
        candidate_evidence = tuple(
            item for item in game.engine_evidence if item.code.startswith("candidate:")
        )
        ambiguous = game.detected_engine_id is None and bool(candidate_evidence)
        if (
            game.detected_engine_id is None
            and game.engine_confidence is None
            and not game.engine_evidence
        ):
            return None
        alternatives: list[JSONValue] = [
            {
                "id": item.code.removeprefix("candidate:"),
                "label": self._engine_label(
                    item.code.removeprefix("candidate:"), engine_detection
                ),
            }
            for item in candidate_evidence
        ]
        evidence: list[JSONValue] = [
            {
                "code": item.code,
                "detail": item.detail,
                "path": item.path,
                "weight": item.weight,
            }
            for item in game.engine_evidence
            if not item.code.startswith("candidate:")
        ]
        detected_id = game.detected_engine_id
        experimental = False
        if engine_detection is not None:
            experimental = engine_detection.is_experimental(detected_id) or any(
                engine_detection.is_experimental(item.code.removeprefix("candidate:"))
                for item in candidate_evidence
            )
        return {
            "id": detected_id,
            "label": (
                "疑似多个引擎"
                if ambiguous
                else self._engine_label(detected_id, engine_detection)
            ),
            "variant": game.detected_engine_variant,
            "confidence": _confidence_label(game.engine_confidence),
            "evidence": evidence,
            "ambiguous": ambiguous,
            "experimental": experimental,
            "alternatives": alternatives,
        }

    def _require_game(self, game_id: str) -> Game:
        game = self._require_library().get_game(game_id)
        if game is None:
            raise GameNotFoundError(game_id)
        return game

    def _guided_session_dto(self, session: GuidedSaveSession) -> dict[str, JSONValue]:
        game = self._require_game(session.game_id)
        error: dict[str, JSONValue] | None = None
        if session.error_code is not None:
            error = {
                "code": session.error_code,
                "message": session.error_summary or "引导式寻找未能完成。",
            }
        return {
            "id": session.id,
            "gameId": session.game_id,
            "gameTitle": game.title,
            "status": session.status,
            "startedAt": session.started_at,
            "monitoringStartedAt": session.monitoring_started_at,
            "saveMarkedAt": session.save_marked_at,
            "finishedAt": session.finished_at,
            "changeCount": session.result_summary.get("eventCount", 0),
            "processTrackingDegraded": session.process_tracking_degraded,
            "overflowedScopes": list(session.overflowed_scopes),
            "truncatedScopes": list(session.truncated_scopes),
            "closeRequested": self._require_guided_saves().close_requested,
            "error": error,
        }

    def _cover_url(self, game: Game, variant: str) -> str | None:
        relative = game.cover_thumb_relpath if variant == "thumb" else game.cover_original_relpath
        if relative is None or self._asset_session_token is None:
            return None
        return (
            f"/session/{self._asset_session_token}/cover/{game.id}/{variant}"
            f"?v={game.cover_revision}"
        )

    @staticmethod
    def _snapshot_data(snapshot: TaskSnapshot) -> dict[str, JSONValue]:
        return {
            "id": snapshot.id,
            "kind": snapshot.kind,
            "status": snapshot.status,
            "progress": cast(dict[str, JSONValue], snapshot.progress),
            "message": snapshot.message,
            "details": cast(dict[str, JSONValue], snapshot.details),
            "result": cast(JSONValue, snapshot.result),
            "error": cast(JSONValue, snapshot.error),
        }


def _cover_wizard_settings_dto(config: AppConfig) -> dict[str, JSONValue]:
    return {
        "coverOnlineEnabled": config.cover_online_enabled,
        "coverVndbCandidateLimit": config.cover_vndb_candidate_limit,
        "coverLocalScanCandidateLimit": config.cover_local_scan_candidate_limit,
    }


def _library_scan_settings_dto(config: AppConfig) -> dict[str, JSONValue]:
    return {
        "startupQuickScan": config.startup_quick_scan,
        "scanConcurrency": config.scan_concurrency,
    }


def _batch_save_settings_dto(config: AppConfig) -> dict[str, JSONValue]:
    return {
        "customRoots": [
            _batch_save_custom_root_dto(root) for root in config.batch_save_custom_roots
        ]
    }


def _batch_save_custom_root_dto(root: BatchSaveCustomRoot) -> dict[str, JSONValue]:
    return {
        "id": root.id,
        "displayPath": root.display_path,
        "enabled": root.enabled,
        "maxDepth": root.max_depth,
    }


def _batch_candidate_page_dto(page: BatchCandidatePage) -> dict[str, JSONValue]:
    return {
        "items": [_batch_candidate_dto(item) for item in page.items],
        "total": page.total,
    }


def _batch_candidate_dto(candidate: PersistedBatchCandidate) -> dict[str, JSONValue]:
    return {
        "id": candidate.id,
        "scopeKey": candidate.scope_key,
        "kind": candidate.kind,
        "displayPath": candidate.display_path,
        "availability": candidate.availability,
        "classification": candidate.classification,
        "confidence": candidate.confidence,
        "suggestedGameId": candidate.suggested_game_id,
        "suggestedTitle": candidate.suggested_title,
        "externalProductId": candidate.external_product_id,
        "engineId": candidate.engine_id,
        "strongGroupKey": candidate.strong_group_key,
        "reviewGameId": candidate.review_game_id,
        "reviewStatus": candidate.review_status,
        "saveLocationId": candidate.save_location_id,
        "sources": [
            "旧自定义清单" if source == "custom" else source
            for source in candidate.sources
        ],
        "evidence": list(candidate.evidence),
        "representativeFiles": [
            {
                "name": item.name,
                "size": item.size,
                "modifiedTimeNs": item.modified_time_ns,
            }
            for item in candidate.representative_files
        ],
        "matchedFileCount": candidate.matched_file_count,
        "representativesTruncated": candidate.representatives_truncated,
        "alternatives": [
            {"title": item.title, "reason": item.reason, "gameId": item.game_id}
            for item in candidate.alternatives
        ],
        "lookupQuery": candidate.external_product_id or candidate.suggested_title,
        "firstSeenAt": candidate.first_seen_at,
        "lastSeenAt": candidate.last_seen_at,
    }


def _batch_scan_summary_dto(summary: BatchScanSummary) -> dict[str, JSONValue]:
    return {
        "sessionId": summary.session_id,
        "status": summary.status,
        "newCount": summary.new_count,
        "pendingCount": summary.pending_count,
        "recordedCount": summary.recorded_count,
        "ignoredCount": summary.ignored_count,
        "unavailableCount": summary.unavailable_count,
        "groupCount": summary.group_count,
        "inaccessibleScopeCount": summary.inaccessible_scope_count,
        "truncatedScopeCount": summary.truncated_scope_count,
        "totalEntries": summary.total_entries,
        "elapsedSeconds": summary.elapsed_seconds,
    }


def _cover_wizard_snapshot_dto(
    snapshot: CoverWizardSnapshot,
) -> dict[str, JSONValue]:
    return {
        "id": snapshot.id,
        "queue": [
            {
                "gameId": item.game_id,
                "title": item.title,
                "version": item.version,
                "initialHasCover": item.initial_has_cover,
                "status": item.status,
                "candidateCount": item.candidate_count,
                "error": item.error,
            }
            for item in snapshot.queue
        ],
        "currentGameId": snapshot.current_game_id,
        "includeExisting": snapshot.include_existing,
        "sourceOperationActive": snapshot.source_operation_active,
    }


def _root_dto(root: ScanRoot) -> dict[str, JSONValue]:
    return {
        "id": root.id,
        "displayPath": root.display_path,
        "pathKey": root.path_key,
        "enabled": root.enabled,
        "scanMode": root.scan_mode,
        "maxDepth": root.max_depth,
        "exclusions": list(root.exclusions),
        "lastScannedAt": root.last_scanned_at,
        "lastScanStatus": root.last_scan_status,
        "lastError": root.last_error,
        "createdAt": root.created_at,
    }


def _save_location_dto(location: SaveLocation) -> dict[str, JSONValue]:
    return {
        "id": location.id,
        "gameId": location.game_id,
        "kind": location.kind,
        "pathTemplate": location.path_template,
        "displayPath": location.display_path,
        "source": location.source,
        "confidence": location.confidence,
        "evidence": list(location.evidence),
        "confirmed": location.confirmed,
        "enabled": location.enabled,
        "lastVerifiedAt": location.last_verified_at,
        "exists": location.exists,
        "matchCount": location.match_count,
        "matchesTruncated": location.matches_truncated,
    }


def _save_suggestion_dto(suggestion: SaveLocationSuggestion) -> dict[str, JSONValue]:
    return {
        "suggestionId": suggestion.suggestion_id,
        "kind": suggestion.kind,
        "pathTemplate": suggestion.path_template,
        "displayPath": suggestion.display_path,
        "source": suggestion.source,
        "confidence": suggestion.confidence,
        "evidence": list(suggestion.evidence),
        "sourceEvidence": [
            {"source": item.source, "detail": item.detail} for item in suggestion.source_evidence
        ],
        "preselected": suggestion.preselected,
        "category": suggestion.category,
        "group": suggestion.group,
        "availability": suggestion.availability,
    }


def _guided_preview_dto(preview: GuidedSavePreview) -> dict[str, JSONValue]:
    return {
        "gameId": preview.game_id,
        "gameTitle": preview.game_title,
        "executable": preview.executable,
        "scopes": [
            {
                "id": scope.id,
                "label": scope.label,
                "displayPath": scope.display_path,
                "pathTemplate": scope.path_template,
                "source": scope.source,
                "defaultSelected": scope.default_selected,
                "available": scope.available,
                "unavailableReason": scope.unavailable_reason,
            }
            for scope in preview.scopes
        ],
        "registryTargets": [
            {
                "key": target.key,
                "source": target.source,
                "available": target.available,
            }
            for target in preview.registry_targets
        ],
        "privacyNotice": ("只读取文件路径、大小和修改时间等元数据，不读取或修改存档内容。"),
    }


def _guided_discovery_dto(discovery: GuidedSaveDiscovery) -> dict[str, JSONValue]:
    return {
        "id": discovery.id,
        "sessionId": discovery.detection_session_id,
        "candidateTemplate": discovery.candidate_template,
        "displayPath": discovery.display_path,
        "kind": discovery.kind,
        "confidence": discovery.confidence,
        "evidence": list(discovery.evidence),
        "representativeFiles": list(discovery.representative_files),
        "firstChangedAt": discovery.first_changed_at,
        "lastChangedAt": discovery.last_changed_at,
        "markOffsetMs": discovery.mark_offset_ms,
        "affectedByOverflow": discovery.affected_by_overflow,
        "affectedByTruncation": discovery.affected_by_truncation,
        "preselected": discovery.preselected,
        "reviewStatus": discovery.review_status,
        "saveLocationId": discovery.save_location_id,
    }


def _guided_service_failure(error: GuidedSaveError) -> ApiResult:
    messages = {
        "guided_service_closed": "引导式寻找服务已经关闭。",
        "guided_session_active": "已有游戏正在引导式寻找存档。",
        "guided_scope_empty": "至少选择一个监控范围。",
        "guided_start_failed": "引导式寻找启动失败。",
        "guided_session_not_found": "找不到引导式寻找会话。",
        "guided_session_not_active": "该引导式寻找会话当前不能执行此操作。",
        "invalid_close_resolution": "未知的关闭处理方式。",
    }
    return failure(
        error.code,
        messages.get(error.code, "引导式寻找操作失败。"),
    )


def _guided_review_failure(error: GuidedReviewError) -> ApiResult:
    messages = {
        "guided_discovery_empty": "至少选择一个引导式存档候选。",
        "guided_discovery_invalid": "引导式存档候选已经失效，请刷新后重试。",
        "guided_session_not_found": "找不到引导式寻找会话。",
        "guided_session_not_reviewable": "该引导式寻找会话尚不能审核。",
        "registry_confirmation_required": "注册表候选需要额外确认后才能接受。",
    }
    return failure(
        error.code,
        messages.get(error.code, "引导式存档候选审核失败。"),
    )


def _update_result_dto(result: UpdateResult) -> dict[str, JSONValue]:
    return {
        "status": result.status,
        "message": result.message,
        "metadata": (
            None
            if result.metadata is None
            else {
                "etag": result.metadata.etag,
                "sha256": result.metadata.sha256,
                "downloadedAt": result.metadata.downloaded_at,
                "sourceUrl": result.metadata.source_url,
                "upstreamCommit": result.metadata.upstream_commit,
            }
        ),
    }


def _scan_summary_dto(summary: ScanSummary) -> dict[str, JSONValue]:
    return {
        "sessionId": summary.session_id,
        "status": summary.status,
        "discovered": summary.discovered,
        "added": summary.added,
        "updated": summary.updated,
        "missing": summary.missing,
        "warnings": summary.warnings,
        "checked": summary.checked,
        "cacheHits": summary.cache_hits,
        "reanalyzed": summary.reanalyzed,
        "fullAnalyses": summary.full_analyses,
        "moveSuggestions": [
            {
                "existingGameId": suggestion.existing_game_id,
                "candidateRelativeDir": suggestion.candidate_relative_dir,
                "confidence": suggestion.confidence,
                "evidence": list(suggestion.evidence),
            }
            for suggestion in summary.move_suggestions
        ],
    }


def _payload(request: object) -> dict[str, object]:
    if not isinstance(request, dict) or not all(isinstance(key, str) for key in request):
        raise InvalidRequest("Request must be a JSON object.")
    return cast(dict[str, object], request)


def _batch_candidate_query(
    request: object,
    *,
    paginated: bool,
) -> BatchCandidateQuery:
    payload = _payload(request)
    filter_keys = {"status", "keyword", "confidence", "source"}
    _only_keys(
        payload,
        filter_keys | ({"offset", "limit"} if paginated else set()),
    )
    status = _optional_query_string(payload, "status", "all")
    keyword = _optional_query_string(payload, "keyword", "", allow_empty=True)
    confidence = _optional_query_string(payload, "confidence", "all")
    source = _optional_query_string(payload, "source", "all")
    offset = payload.get("offset", 0)
    limit = payload.get("limit", 100 if paginated else 500)
    if type(offset) is not int or offset < 0:
        raise InvalidRequest("offset must be a non-negative integer.")
    if type(limit) is not int or (paginated and not 20 <= limit <= 200):
        raise InvalidRequest("limit must be an integer from 20 to 200.")
    return BatchCandidateQuery(
        status=cast(Any, status),
        keyword=keyword,
        confidence=cast(Any, confidence),
        source=cast(Any, source),
        offset=offset,
        limit=limit,
    )


def _optional_query_string(
    payload: dict[str, object],
    key: str,
    default: str,
    *,
    allow_empty: bool = False,
) -> str:
    value = payload.get(key, default)
    if not isinstance(value, str) or "\x00" in value:
        raise InvalidRequest(f"{key} must be a string.")
    if not allow_empty and not value.strip():
        raise InvalidRequest(f"{key} must be a non-empty string.")
    return value.strip()


def _batch_candidate_ids(payload: dict[str, object]) -> tuple[str, ...]:
    values = _clean_string_list(payload, "candidateIds")
    if not values or len(values) > 500:
        raise InvalidRequest("candidateIds must contain 1 to 500 entries.")
    return tuple(dict.fromkeys(values))


def _nullable_string(payload: dict[str, object], key: str) -> str | None:
    if key not in payload:
        raise InvalidRequest(f"{key} is required.")
    value = payload[key]
    if value is None:
        return None
    if not isinstance(value, str) or "\x00" in value:
        raise InvalidRequest(f"{key} must be a string or null.")
    return value


def _game_group_dto(group: GameGroup) -> dict[str, JSONValue]:
    return {
        "id": group.id,
        "name": group.name,
        "gameCount": group.game_count,
        "createdAt": group.created_at,
        "updatedAt": group.updated_at,
    }


def _only_keys(payload: dict[str, object], allowed: set[str]) -> None:
    unexpected = sorted(set(payload) - allowed)
    if unexpected:
        raise InvalidRequest(f"Unexpected request fields: {', '.join(unexpected)}.")


def _string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InvalidRequest(f"{key} must be a non-empty string.")
    return value


def _integer(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise InvalidRequest(f"{key} must be an integer.")
    return value


def _boolean(payload: dict[str, object], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise InvalidRequest(f"{key} must be a boolean.")
    return value


def _optional_boolean(payload: dict[str, object], key: str, *, default: bool) -> bool:
    value = payload.get(key, default)
    if not isinstance(value, bool):
        raise InvalidRequest(f"{key} must be a boolean.")
    return value


def _string_list(payload: dict[str, object], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise InvalidRequest(f"{key} must be an array of strings.")
    return cast(list[str], value)


def _clean_string_list(payload: dict[str, object], key: str) -> list[str]:
    values = _string_list(payload, key)
    if any(not item.strip() for item in values):
        raise InvalidRequest(f"{key} entries must be non-empty strings.")
    return [item.strip() for item in values]


def _game_removal_requests(
    payload: dict[str, object],
) -> tuple[GameRemovalRequest, ...]:
    value = payload.get("items")
    if not isinstance(value, list) or not value:
        raise InvalidRequest("items must be a non-empty array.")
    if len(value) > LibraryService.MAX_BATCH_REMOVALS:
        raise InvalidRequest(
            f"items cannot contain more than {LibraryService.MAX_BATCH_REMOVALS} entries."
        )
    requests: list[GameRemovalRequest] = []
    for raw_item in value:
        if not isinstance(raw_item, dict) or not all(isinstance(key, str) for key in raw_item):
            raise InvalidRequest("Each items entry must be a JSON object.")
        item = cast(dict[str, object], raw_item)
        status = _string(item, "expectedStatus")
        if status not in {"installed", "missing"}:
            raise InvalidRequest("expectedStatus must be 'installed' or 'missing'.")
        requests.append(
            GameRemovalRequest(_string(item, "gameId"), cast(RemovableGameStatus, status))
        )
    return tuple(requests)


def _scan_mode(payload: dict[str, object]) -> Any:
    mode = _string(payload, "scanMode")
    if mode not in {"children", "recursive"}:
        raise InvalidRequest("scanMode must be 'children' or 'recursive'.")
    return mode


def _save_kind(payload: dict[str, object]) -> str:
    kind = _string(payload, "kind")
    if kind not in {"directory", "file", "glob", "registry"}:
        raise InvalidSaveLocation(f"未知的存档位置类型：{kind}")
    return kind


def _confidence_label(value: float | None) -> str | None:
    if value is None:
        return None
    if value >= 0.9:
        return "高"
    if value >= 0.75:
        return "中"
    return "低"
