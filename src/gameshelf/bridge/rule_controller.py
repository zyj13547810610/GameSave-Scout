"""Strict bridge adapter for rule management and native rule file dialogs."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from gameshelf.bridge.contracts import ApiResult, JSONValue, failure, success
from gameshelf.rules.catalog import RuleCatalogService
from gameshelf.rules.import_export import (
    RuleImportDecision,
    RuleImportExportError,
    RuleImportExportService,
    RuleImportPreview,
)
from gameshelf.rules.management import (
    GameSaveRulePrefill,
    RuleDetail,
    RuleDraftValidation,
    RuleListFilters,
    RuleManagementError,
    RuleManagementService,
    RuleMutationResult,
    RuleTestResult,
)
from gameshelf.rules.models import RuleDiagnostic

_RULE_FILE_TYPES = ("GameShelf 规则 (*.yaml;*.yml)",)


class InvalidRuleRequest(ValueError):
    pass


class RuleBridgeController:
    def __init__(
        self,
        *,
        management: RuleManagementService,
        catalog: RuleCatalogService,
        import_export: RuleImportExportService,
        user_rule_directory: Path,
        legacy_manifest_directory: Path,
        directory_opener: Callable[[Path], None],
    ) -> None:
        self._management = management
        self._catalog = catalog
        self._import_export = import_export
        self._user_rule_directory = user_rule_directory
        self._legacy_manifest_directory = legacy_manifest_directory
        self._directory_opener = directory_opener
        self._window: Any | None = None

    def attach_window(self, window: object) -> None:
        self._window = window

    def list_rules(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(
                payload,
                {"kind", "source", "status", "enabled", "query", "offset", "limit"},
            )
            result = self._management.list_rules(
                RuleListFilters(
                    kind=cast(Any, _optional_string(payload, "kind", "all")),
                    source=cast(Any, _optional_string(payload, "source", "all")),
                    status=cast(Any, _optional_string(payload, "status", "all")),
                    enabled=cast(Any, _optional_string(payload, "enabled", "all")),
                    query=_optional_string(payload, "query", ""),
                    offset=_optional_int(payload, "offset", 0),
                    limit=_optional_int(payload, "limit", 100),
                )
            )
            return success(
                {
                    "items": [_summary_dto(item) for item in result.items],
                    "total": result.total,
                }
            )
        except (InvalidRuleRequest, ValueError) as error:
            return failure("invalid_request", str(error))

    def get_rule(self, request: object) -> ApiResult:
        return self._qualified_command(request, self._management.get_rule, _detail_dto)

    def validate_rule_draft(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"draft"})
            return success(_validation_dto(self._management.validate_draft(_draft(payload))))
        except InvalidRuleRequest as error:
            return failure("invalid_request", str(error))

    def test_rule_draft(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"draft", "gameId"})
            return success(
                _test_result_dto(
                    self._management.test_draft(
                        _draft(payload),
                        _string(payload, "gameId"),
                    )
                )
            )
        except InvalidRuleRequest as error:
            return failure("invalid_request", str(error))
        except RuleManagementError as error:
            return failure(error.code, str(error))

    def save_rule(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(
                payload,
                {"originalQualifiedId", "draft", "verificationToken"},
            )
            result = self._management.save_rule(
                _nullable_string(payload, "originalQualifiedId"),
                _draft(payload),
                _nullable_string(payload, "verificationToken"),
            )
            return success(_mutation_dto(result))
        except InvalidRuleRequest as error:
            return failure("invalid_request", str(error))
        except RuleManagementError as error:
            return failure(error.code, str(error))

    def copy_rule(self, request: object) -> ApiResult:
        return self._qualified_command(request, self._management.copy_rule, _mutation_dto)

    def set_rule_enabled(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"qualifiedId", "enabled"})
            enabled = payload.get("enabled")
            if not isinstance(enabled, bool):
                raise InvalidRuleRequest("enabled 必须是布尔值。")
            return success(
                _mutation_dto(
                    self._management.set_enabled(
                        _string(payload, "qualifiedId"),
                        enabled,
                    )
                )
            )
        except InvalidRuleRequest as error:
            return failure("invalid_request", str(error))
        except RuleManagementError as error:
            return failure(error.code, str(error))

    def delete_rule(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"qualifiedId"})
            result = self._management.delete_user_rule(
                _string(payload, "qualifiedId")
            )
            return success(
                {
                    "qualifiedId": result.qualified_id,
                    "generation": result.generation,
                }
            )
        except InvalidRuleRequest as error:
            return failure("invalid_request", str(error))
        except RuleManagementError as error:
            return failure(error.code, str(error))

    def refresh_rules(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, set())
        except InvalidRuleRequest as error:
            return failure("invalid_request", str(error))
        result = self._catalog.refresh()
        return success(
            {
                "applied": result.applied,
                "generation": result.snapshot.generation,
                "catalogVersion": result.snapshot.catalog_version,
                "diagnostics": [_diagnostic_dto(item) for item in result.diagnostics],
            }
        )

    def get_game_save_rule_prefill(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"gameId"})
            return success(
                _prefill_dto(
                    self._management.prefill_game_save_rule(
                        _string(payload, "gameId")
                    )
                )
            )
        except InvalidRuleRequest as error:
            return failure("invalid_request", str(error))
        except RuleManagementError as error:
            return failure(error.code, str(error))

    def begin_rule_import(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, set())
            paths = self._choose_import_paths()
            if not paths:
                return success({"cancelled": True})
            preview = self._import_export.begin_import(paths)
            return success({"cancelled": False, **_preview_dto(preview)})
        except InvalidRuleRequest as error:
            return failure("invalid_request", str(error))
        except RuleImportExportError as error:
            return failure(error.code, str(error))

    def confirm_rule_import(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"sessionId", "decisions"})
            result = self._import_export.confirm_import(
                _string(payload, "sessionId"),
                _decisions(payload),
            )
            return success(
                {
                    "importedQualifiedIds": list(result.imported_qualified_ids),
                    "skippedCount": result.skipped_count,
                    "generation": result.generation,
                }
            )
        except InvalidRuleRequest as error:
            return failure("invalid_request", str(error))
        except RuleImportExportError as error:
            return failure(error.code, str(error))

    def export_rule(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"qualifiedId"})
            qualified_id = _string(payload, "qualifiedId")
            rule_id = qualified_id.partition(":")[2] or "gameshelf-rule"
            destination = self._choose_export_path(f"{rule_id}.yaml")
            if destination is None:
                return success({"cancelled": True})
            result = self._import_export.export_rule(qualified_id, destination)
            return success({"cancelled": False, "fileName": result.file_name})
        except InvalidRuleRequest as error:
            return failure("invalid_request", str(error))
        except RuleImportExportError as error:
            return failure(error.code, str(error))

    def open_rule_directory(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"target"})
            target = _string(payload, "target")
            if target == "user":
                directory = self._user_rule_directory
                directory.mkdir(parents=True, exist_ok=True)
            elif target == "legacy":
                directory = self._legacy_manifest_directory
                if not directory.is_dir():
                    return failure(
                        "legacy_manifest_not_found",
                        "未检测到旧 data/manifests 目录。",
                    )
            else:
                raise InvalidRuleRequest("target 只允许 user 或 legacy。")
            self._directory_opener(directory)
            return success({"opened": True})
        except InvalidRuleRequest as error:
            return failure("invalid_request", str(error))
        except OSError:
            return failure("open_failed", "规则目录打开失败。")

    def _qualified_command(
        self,
        request: object,
        command: Callable[[str], object],
        dto: Callable[[Any], JSONValue],
    ) -> ApiResult:
        try:
            payload = _payload(request)
            _only_keys(payload, {"qualifiedId"})
            return success(dto(command(_string(payload, "qualifiedId"))))
        except InvalidRuleRequest as error:
            return failure("invalid_request", str(error))
        except RuleManagementError as error:
            return failure(error.code, str(error))

    def _choose_import_paths(self) -> tuple[Path, ...]:
        if self._window is None:
            return ()
        import webview

        selected = self._window.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=True,
            file_types=_RULE_FILE_TYPES,
        )
        return _selected_paths(selected)

    def _choose_export_path(self, default_name: str) -> Path | None:
        if self._window is None:
            return None
        import webview

        selected = self._window.create_file_dialog(
            webview.SAVE_DIALOG,
            allow_multiple=False,
            file_types=_RULE_FILE_TYPES,
            save_filename=default_name,
        )
        paths = _selected_paths(selected)
        return paths[0] if paths else None


def _payload(request: object) -> dict[str, object]:
    if not isinstance(request, dict) or not all(
        isinstance(key, str) for key in request
    ):
        raise InvalidRuleRequest("请求必须是对象。")
    return cast(dict[str, object], request)


def _only_keys(payload: dict[str, object], allowed: set[str]) -> None:
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise InvalidRuleRequest(f"请求包含不受支持的字段：{', '.join(unknown)}")


def _string(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise InvalidRuleRequest(f"{key} 必须是非空字符串。")
    return value


def _optional_string(payload: Mapping[str, object], key: str, default: str) -> str:
    value = payload.get(key, default)
    if not isinstance(value, str):
        raise InvalidRuleRequest(f"{key} 必须是字符串。")
    return value


def _nullable_string(payload: Mapping[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise InvalidRuleRequest(f"{key} 必须是非空字符串或 null。")
    return value


def _optional_int(payload: Mapping[str, object], key: str, default: int) -> int:
    value = payload.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise InvalidRuleRequest(f"{key} 必须是整数。")
    return value


def _draft(payload: Mapping[str, object]) -> Mapping[str, object]:
    value = payload.get("draft")
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise InvalidRuleRequest("draft 必须是对象。")
    return cast(dict[str, object], value)


def _decisions(payload: Mapping[str, object]) -> tuple[RuleImportDecision, ...]:
    raw = payload.get("decisions")
    if not isinstance(raw, list) or len(raw) > 32:
        raise InvalidRuleRequest("decisions 必须是最多 32 项的数组。")
    result: list[RuleImportDecision] = []
    for value in raw:
        item = _payload(value)
        _only_keys(item, {"itemId", "action", "newRuleId"})
        action = _string(item, "action")
        if action not in {"import", "replace", "new_id", "skip"}:
            raise InvalidRuleRequest("导入决定 action 无效。")
        result.append(
            RuleImportDecision(
                _string(item, "itemId"),
                cast(Any, action),
                _nullable_string(item, "newRuleId"),
            )
        )
    return tuple(result)


def _selected_paths(selected: object) -> tuple[Path, ...]:
    if not selected:
        return ()
    if isinstance(selected, str):
        return (Path(selected),)
    if isinstance(selected, Sequence):
        return tuple(Path(value) for value in selected if isinstance(value, str))
    return ()


def _summary_dto(summary: object) -> dict[str, JSONValue]:
    value = cast(Any, summary)
    return {
        "qualifiedId": value.qualified_id,
        "ruleId": value.rule_id,
        "label": value.label,
        "ruleType": value.rule_type,
        "source": value.source,
        "status": value.status,
        "enabled": value.enabled,
        "priority": value.priority,
    }


def _detail_dto(detail: RuleDetail) -> dict[str, JSONValue]:
    return {
        **_summary_dto(detail),
        "notes": detail.notes,
        "references": list(detail.references),
        "sourceFile": detail.source_file,
        "yamlPreview": detail.yaml_preview,
        "draft": cast(dict[str, JSONValue], dict(detail.draft)),
        "capabilities": {
            "edit": detail.capabilities.edit,
            "copy": detail.capabilities.copy,
            "test": detail.capabilities.test,
            "toggle": detail.capabilities.toggle,
            "delete": detail.capabilities.delete,
            "export": detail.capabilities.export,
        },
    }


def _validation_dto(result: RuleDraftValidation) -> dict[str, JSONValue]:
    return {
        "valid": result.valid,
        "normalizedDraft": (
            None
            if result.normalized_draft is None
            else cast(dict[str, JSONValue], dict(result.normalized_draft))
        ),
        "yamlPreview": result.yaml_preview,
        "errorCode": result.error_code,
        "message": result.message,
    }


def _test_result_dto(result: RuleTestResult) -> dict[str, JSONValue]:
    return {
        "matched": result.matched,
        "summary": result.summary,
        "evidence": list(result.evidence),
        "expandedLocations": [
            {
                "kind": item.kind,
                "pathTemplate": item.path_template,
                "displayPath": item.display_path,
                "exists": item.exists,
                "truncated": item.truncated,
                "diagnostics": list(item.diagnostics),
            }
            for item in result.expanded_locations
        ],
        "verificationToken": result.verification_token,
    }


def _mutation_dto(result: RuleMutationResult) -> dict[str, JSONValue]:
    return {"detail": _detail_dto(result.detail), "generation": result.generation}


def _prefill_dto(prefill: GameSaveRulePrefill) -> dict[str, JSONValue]:
    return {
        "gameId": prefill.game_id,
        "title": prefill.title,
        "aliases": list(prefill.aliases),
        "productIds": list(prefill.product_ids),
        "locations": [
            {
                "kind": item.kind,
                "pathTemplate": item.path_template,
                "category": item.category,
                "confidence": item.confidence,
            }
            for item in prefill.locations
        ],
        "engineId": prefill.engine_id,
    }


def _preview_dto(preview: RuleImportPreview) -> dict[str, JSONValue]:
    return {
        "sessionId": preview.session_id,
        "items": [
            {
                "itemId": item.item_id,
                "fileName": item.file_name,
                "valid": item.valid,
                "errors": list(item.errors),
                "qualifiedId": item.qualified_id,
                "ruleType": item.rule_type,
                "status": item.status,
                "conflict": item.conflict,
                "allowedDecisions": list(item.allowed_decisions),
            }
            for item in preview.items
        ],
    }


def _diagnostic_dto(diagnostic: RuleDiagnostic) -> dict[str, JSONValue]:
    return {
        "severity": diagnostic.severity,
        "code": diagnostic.code,
        "message": diagnostic.message,
        "sourceName": diagnostic.source_name,
    }
