"""Transactional management and read-only testing for declarative rules."""

from __future__ import annotations

import secrets
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path, PureWindowsPath
from threading import Lock
from types import MappingProxyType
from typing import Literal, Protocol, cast

import yaml

from gameshelf.engines.base import DetectionContext
from gameshelf.engines.rule_detector import RuleDetector
from gameshelf.engines.rule_schema import (
    EngineRule,
    RuleSchemaError,
    parse_engine_rule_document,
)
from gameshelf.library.models import Game
from gameshelf.rules.catalog import (
    CatalogRule,
    RuleCatalogError,
    RuleCatalogService,
    RuleSnapshot,
)
from gameshelf.rules.models import RuleSource, RuleStatus, RuleType
from gameshelf.rules.repository import RuleFileError, UserRuleRepository
from gameshelf.rules.serialization import (
    RuleDefinition,
    serialize_rule_document,
    verification_fingerprint,
)
from gameshelf.saves.builtin_rules import SaveRuleProvider
from gameshelf.saves.engine_hints import load_engine_metadata
from gameshelf.saves.models import SaveLocation, SaveLocationKind, SuggestionCategory
from gameshelf.saves.rule_identity import collect_rule_identity
from gameshelf.saves.rule_probe import BoundedRuleProbe, RegistryKeyProbe
from gameshelf.saves.rule_schema import (
    SaveRule,
    SaveRuleSchemaError,
    parse_save_rule_document,
)
from gameshelf.saves.templates import PathTemplateResolver

type RuleKindFilter = Literal["all", "engine", "save"]
type RuleSourceFilter = Literal["all", "builtin", "user"]
type RuleStatusFilter = Literal["all", "formal", "experimental"]
type RuleEnabledFilter = Literal["all", "enabled", "disabled"]


class RuleManagementError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class RuleListFilters:
    kind: RuleKindFilter = "all"
    source: RuleSourceFilter = "all"
    status: RuleStatusFilter = "all"
    enabled: RuleEnabledFilter = "all"
    query: str = ""
    offset: int = 0
    limit: int = 100

    def __post_init__(self) -> None:
        if self.kind not in {"all", "engine", "save"}:
            raise ValueError("规则类型筛选无效。")
        if self.source not in {"all", "builtin", "user"}:
            raise ValueError("规则来源筛选无效。")
        if self.status not in {"all", "formal", "experimental"}:
            raise ValueError("规则状态筛选无效。")
        if self.enabled not in {"all", "enabled", "disabled"}:
            raise ValueError("规则启用筛选无效。")
        if self.offset < 0 or not 1 <= self.limit <= 200:
            raise ValueError("规则分页参数无效。")
        if len(self.query) > 200:
            raise ValueError("规则搜索文本不能超过 200 个字符。")


@dataclass(frozen=True, slots=True)
class RuleSummary:
    qualified_id: str
    rule_id: str
    label: str
    rule_type: RuleType
    source: RuleSource
    status: RuleStatus
    enabled: bool
    priority: int


@dataclass(frozen=True, slots=True)
class RuleListResult:
    items: tuple[RuleSummary, ...]
    total: int


@dataclass(frozen=True, slots=True)
class RuleCapabilities:
    edit: bool
    copy: bool
    test: bool
    toggle: bool
    delete: bool
    export: bool


@dataclass(frozen=True, slots=True)
class RuleDetail(RuleSummary):
    notes: str | None
    references: tuple[str, ...]
    source_file: str
    yaml_preview: str
    draft: Mapping[str, object]
    capabilities: RuleCapabilities


@dataclass(frozen=True, slots=True)
class RuleDraftValidation:
    valid: bool
    normalized_draft: Mapping[str, object] | None
    yaml_preview: str | None
    error_code: str | None
    message: str


@dataclass(frozen=True, slots=True)
class RuleTestLocation:
    kind: SaveLocationKind
    path_template: str
    display_path: str
    exists: bool
    truncated: bool
    diagnostics: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RuleTestResult:
    matched: bool
    summary: str
    evidence: tuple[str, ...]
    expanded_locations: tuple[RuleTestLocation, ...]
    verification_token: str | None


@dataclass(frozen=True, slots=True)
class RuleMutationResult:
    detail: RuleDetail
    generation: int


@dataclass(frozen=True, slots=True)
class RuleDeleteResult:
    qualified_id: str
    generation: int


@dataclass(frozen=True, slots=True)
class GameSaveRulePrefillLocation:
    kind: SaveLocationKind
    path_template: str
    category: SuggestionCategory = "save"
    confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class GameSaveRulePrefill:
    game_id: str
    title: str
    aliases: tuple[str, ...]
    product_ids: tuple[str, ...]
    locations: tuple[GameSaveRulePrefillLocation, ...]
    engine_id: str | None


class RuleLibrary(Protocol):
    def get_game(self, game_id: str) -> Game | None: ...

    def install_directory(self, game_id: str) -> Path: ...


class RuleSaveLocations(Protocol):
    def list_for_game(self, game_id: str) -> tuple[SaveLocation, ...]: ...


class RuleManagementService:
    def __init__(
        self,
        *,
        catalog: RuleCatalogService,
        repository: UserRuleRepository,
        resolver: PathTemplateResolver,
        library: RuleLibrary,
        save_repository: RuleSaveLocations,
        registry: RegistryKeyProbe,
    ) -> None:
        self._catalog = catalog
        self._repository = repository
        self._resolver = resolver
        self._library = library
        self._save_repository = save_repository
        self._probe = BoundedRuleProbe(resolver, registry)
        self._tokens: dict[str, str] = {}
        self._token_lock = Lock()

    def list_rules(self, filters: RuleListFilters) -> RuleListResult:
        items = [
            self._summary(item.rule)
            for item in self._catalog.snapshot().rules
            if _matches_filters(item.rule, filters)
        ]
        items.sort(key=_summary_order)
        return RuleListResult(
            tuple(items[filters.offset : filters.offset + filters.limit]),
            len(items),
        )

    def get_rule(self, qualified_id: str) -> RuleDetail:
        item = self._find(qualified_id)
        return self._detail(item)

    def validate_draft(self, draft: Mapping[str, object]) -> RuleDraftValidation:
        try:
            rule = _parse_draft(draft)
        except (RuleSchemaError, SaveRuleSchemaError, UnicodeError, yaml.YAMLError) as error:
            return RuleDraftValidation(
                False,
                None,
                None,
                "invalid_rule_draft",
                str(error),
            )
        content = serialize_rule_document(rule)
        return RuleDraftValidation(
            True,
            MappingProxyType(_draft_from_rule(rule)),
            content.decode("utf-8"),
            None,
            "规则草稿有效。",
        )

    def test_draft(
        self,
        draft: Mapping[str, object],
        game_id: str,
    ) -> RuleTestResult:
        rule = self._require_draft(draft)
        game, install_dir = self._require_installed_game(game_id)
        if isinstance(rule, EngineRule):
            return self._test_engine_rule(rule, game, install_dir)
        return self._test_save_rule(rule, game, install_dir)

    def save_rule(
        self,
        original_qualified_id: str | None,
        draft: Mapping[str, object],
        verification_token: str | None,
    ) -> RuleMutationResult:
        rule = self._require_draft(draft)
        snapshot = self._catalog.snapshot()
        original = (
            None
            if original_qualified_id is None
            else self._find(original_qualified_id, snapshot)
        )
        if original is not None:
            if original.rule.metadata.source != "user":
                raise RuleManagementError(
                    "builtin_rule_readonly",
                    "内置规则不可编辑，请先复制为用户规则。",
                )
            if original.rule.metadata.rule_id != rule.metadata.rule_id:
                raise RuleManagementError(
                    "rule_id_change_requires_copy",
                    "已有用户规则的 ID 不可修改，请使用复制功能。",
                )
            if original.rule.metadata.rule_type != rule.metadata.rule_type:
                raise RuleManagementError(
                    "rule_type_change_requires_copy",
                    "已有用户规则的类型不可修改，请使用复制功能。",
                )
            old_fingerprint = verification_fingerprint(original.rule)
            new_fingerprint = verification_fingerprint(rule)
            if (
                original.rule.metadata.status == "formal"
                and old_fingerprint != new_fingerprint
            ):
                rule = _with_status(rule, "experimental")
            elif rule.metadata.status == "formal" and original.rule.metadata.status != "formal":
                self._consume_verification(verification_token, new_fingerprint)
        elif rule.metadata.status == "formal":
            self._consume_verification(
                verification_token,
                verification_fingerprint(rule),
            )

        existing = _rules_by_id(snapshot)
        collision = existing.get(rule.metadata.rule_id)
        if collision is not None and collision is not original:
            raise RuleManagementError("rule_id_conflict", "规则 ID 已被占用。")
        target = (
            original.source_path
            if original is not None
            else self._repository.rule_path(
                rule.metadata.rule_type,
                rule.metadata.rule_id,
            )
        )
        settings = self._catalog.current_settings()
        try:
            published = self._catalog.apply_user_changes(
                {target: serialize_rule_document(rule)},
                settings,
                expected_generation=snapshot.generation,
            )
        except (RuleCatalogError, RuleFileError, OSError) as error:
            raise _mutation_error(error) from error
        return RuleMutationResult(
            self._detail(self._find(rule.metadata.qualified_id, published)),
            published.generation,
        )

    def copy_rule(self, qualified_id: str) -> RuleMutationResult:
        snapshot = self._catalog.snapshot()
        source = self._find(qualified_id, snapshot).rule
        occupied = set(_rules_by_id(snapshot))
        rule_id = _copy_id(source.metadata.rule_id, occupied)
        copied = _with_identity(source, rule_id, "user", "experimental")
        target = self._repository.rule_path(copied.metadata.rule_type, rule_id)
        try:
            published = self._catalog.apply_user_changes(
                {target: serialize_rule_document(copied)},
                self._catalog.current_settings(),
                expected_generation=snapshot.generation,
            )
        except (RuleCatalogError, RuleFileError, OSError) as error:
            raise _mutation_error(error) from error
        return RuleMutationResult(
            self._detail(self._find(copied.metadata.qualified_id, published)),
            published.generation,
        )

    def set_enabled(self, qualified_id: str, enabled: bool) -> RuleMutationResult:
        snapshot = self._catalog.snapshot()
        item = self._find(qualified_id, snapshot)
        if not isinstance(enabled, bool):
            raise RuleManagementError("invalid_enabled", "启用状态必须是布尔值。")
        settings = self._catalog.current_settings()
        changes: dict[Path, bytes | None] = {}
        if item.rule.metadata.source == "builtin":
            disabled = set(settings.disabled_builtin_rule_ids)
            if enabled:
                disabled.discard(qualified_id)
            else:
                disabled.add(qualified_id)
            settings = replace(settings, disabled_builtin_rule_ids=frozenset(disabled))
        else:
            updated = replace(
                item.rule,
                metadata=replace(item.rule.metadata, enabled=enabled),
            )
            changes[item.source_path] = serialize_rule_document(updated)
        try:
            published = self._catalog.apply_user_changes(
                changes,
                settings,
                expected_generation=snapshot.generation,
            )
        except (RuleCatalogError, RuleFileError, OSError) as error:
            raise _mutation_error(error) from error
        return RuleMutationResult(
            self._detail(self._find(qualified_id, published)),
            published.generation,
        )

    def delete_user_rule(self, qualified_id: str) -> RuleDeleteResult:
        snapshot = self._catalog.snapshot()
        item = self._find(qualified_id, snapshot)
        if item.rule.metadata.source != "user":
            raise RuleManagementError(
                "builtin_rule_readonly",
                "内置规则不可删除。",
            )
        try:
            published = self._catalog.apply_user_changes(
                {item.source_path: None},
                self._catalog.current_settings(),
                expected_generation=snapshot.generation,
            )
        except (RuleCatalogError, RuleFileError, OSError) as error:
            raise _mutation_error(error) from error
        return RuleDeleteResult(qualified_id, published.generation)

    def prefill_game_save_rule(self, game_id: str) -> GameSaveRulePrefill:
        game = self._library.get_game(game_id)
        if game is None:
            raise RuleManagementError("game_not_found", "没有找到对应的游戏。")
        locations = self._save_repository.list_for_game(game_id)
        identity = collect_rule_identity(game, locations)
        aliases = tuple(
            title
            for title in identity.exact_titles
            if title.casefold() != game.title.casefold()
        )
        templates = tuple(
            GameSaveRulePrefillLocation(kind, template)
            for kind, template in dict.fromkeys(
                (location.kind, location.path_template)
                for location in locations
                if location.confirmed and location.enabled
            )
        )
        return GameSaveRulePrefill(
            game.id,
            game.title,
            aliases,
            identity.product_ids,
            templates,
            game.engine_id,
        )

    def _test_engine_rule(
        self,
        rule: EngineRule,
        game: Game,
        install_dir: Path,
    ) -> RuleTestResult:
        executable = None
        if game.main_exe_relpath:
            executable = install_dir.joinpath(
                *PureWindowsPath(game.main_exe_relpath).parts
            )
        match = RuleDetector(rule).inspect(DetectionContext(install_dir, executable))
        evidence = () if match is None else tuple(item.detail for item in match.evidence)
        token = None if match is None else self._issue_verification(rule)
        return RuleTestResult(
            match is not None,
            "规则达到检测阈值。" if match is not None else "规则未达到检测阈值。",
            evidence,
            (),
            token,
        )

    def _test_save_rule(
        self,
        rule: SaveRule,
        game: Game,
        install_dir: Path,
    ) -> RuleTestResult:
        locations = self._save_repository.list_for_game(game.id)
        identity = collect_rule_identity(game, locations)
        engine_metadata = load_engine_metadata(game, install_dir)
        metadata = {**engine_metadata, **identity.as_rule_metadata()}
        test_rule = replace(
            rule,
            metadata=replace(rule.metadata, enabled=True),
        )
        provider = SaveRuleProvider((test_rule,), self._resolver)
        suggestions = (
            provider.suggest_game_specific(game, install_dir, metadata)
            if rule.metadata.rule_type == "save_game"
            else provider.suggest_engine(game, install_dir, metadata)
        )
        expanded: list[RuleTestLocation] = []
        evidence: list[str] = []
        found = False
        for suggestion in suggestions:
            probe = self._probe.probe(
                suggestion.kind,
                suggestion.path_template,
                install_dir,
            )
            found = found or probe.found
            expanded.append(
                RuleTestLocation(
                    suggestion.kind,
                    suggestion.path_template,
                    suggestion.display_path,
                    probe.found,
                    probe.truncated,
                    probe.diagnostics,
                )
            )
            evidence.extend(suggestion.evidence)
        matched = bool(suggestions)
        token = self._issue_verification(rule) if matched and found else None
        if not matched:
            summary = "规则与所选游戏的精确身份或引擎不匹配。"
        elif found:
            summary = "规则匹配，且至少一个存档位置当前存在。"
        else:
            summary = "规则匹配，但当前只推导出尚不存在的位置。"
        return RuleTestResult(
            matched,
            summary,
            tuple(dict.fromkeys(evidence)),
            tuple(expanded),
            token,
        )

    def _require_draft(self, draft: Mapping[str, object]) -> RuleDefinition:
        try:
            return _parse_draft(draft)
        except (RuleSchemaError, SaveRuleSchemaError, UnicodeError, yaml.YAMLError) as error:
            raise RuleManagementError("invalid_rule_draft", str(error)) from error

    def _require_installed_game(self, game_id: str) -> tuple[Game, Path]:
        game = self._library.get_game(game_id)
        if game is None:
            raise RuleManagementError("game_not_found", "没有找到对应的游戏。")
        if game.status != "installed":
            raise RuleManagementError(
                "game_not_installed",
                "只允许使用当前已安装的游戏测试规则。",
            )
        try:
            return game, self._library.install_directory(game_id)
        except (OSError, ValueError, LookupError) as error:
            raise RuleManagementError(
                "game_directory_unavailable",
                "所选游戏目录当前不可访问。",
            ) from error

    def _issue_verification(self, rule: RuleDefinition) -> str:
        token = secrets.token_urlsafe(32)
        with self._token_lock:
            while len(self._tokens) >= 128:
                self._tokens.pop(next(iter(self._tokens)))
            self._tokens[token] = verification_fingerprint(rule)
        return token

    def _consume_verification(
        self,
        token: str | None,
        fingerprint: str,
    ) -> None:
        with self._token_lock:
            valid = token is not None and self._tokens.get(token) == fingerprint
            if valid:
                self._tokens.pop(cast(str, token), None)
        if not valid:
            raise RuleManagementError(
                "rule_verification_required",
                "保存为已验证规则前，必须用相同内容完成一次成功测试。",
            )

    def _find(
        self,
        qualified_id: str,
        snapshot: RuleSnapshot | None = None,
    ) -> CatalogRule:
        current = snapshot or self._catalog.snapshot()
        try:
            return next(
                item
                for item in current.rules
                if item.rule.metadata.qualified_id == qualified_id
            )
        except StopIteration as error:
            raise RuleManagementError("rule_not_found", "没有找到对应的规则。") from error

    def _summary(self, rule: RuleDefinition) -> RuleSummary:
        metadata = rule.metadata
        return RuleSummary(
            metadata.qualified_id,
            metadata.rule_id,
            rule.label,
            metadata.rule_type,
            metadata.source,
            metadata.status,
            metadata.enabled,
            metadata.priority,
        )

    def _detail(self, item: CatalogRule) -> RuleDetail:
        rule = item.rule
        summary = self._summary(rule)
        source_file = _source_display_name(rule, item.source_path)
        user = rule.metadata.source == "user"
        return RuleDetail(
            **{
                field: getattr(summary, field)
                for field in RuleSummary.__dataclass_fields__
            },
            notes=rule.notes,
            references=rule.metadata.references,
            source_file=source_file,
            yaml_preview=serialize_rule_document(rule).decode("utf-8"),
            draft=MappingProxyType(_draft_from_rule(rule)),
            capabilities=RuleCapabilities(
                edit=user,
                copy=True,
                test=True,
                toggle=True,
                delete=user,
                export=True,
            ),
        )


def _parse_draft(draft: Mapping[str, object]) -> RuleDefinition:
    if not isinstance(draft, Mapping) or not all(
        isinstance(key, str) for key in draft
    ):
        raise RuleSchemaError("规则草稿必须是字符串键对象。")
    raw = dict(draft)
    version = raw.pop("version", None)
    if not isinstance(version, str):
        raise RuleSchemaError("规则草稿缺少 version。")
    rule_type = raw.get("type")
    document = {"version": version, "rules": [raw]}
    if rule_type == "engine":
        return parse_engine_rule_document(
            document,
            source="user",
            require_single=True,
        )[0]
    return parse_save_rule_document(
        document,
        source="user",
        require_single=True,
    )[0]


def _draft_from_rule(rule: RuleDefinition) -> dict[str, object]:
    document = yaml.safe_load(serialize_rule_document(rule))
    assert isinstance(document, dict)
    entries = document["rules"]
    assert isinstance(entries, list) and isinstance(entries[0], dict)
    return {"version": document["version"], **entries[0]}


def _matches_filters(rule: RuleDefinition, filters: RuleListFilters) -> bool:
    metadata = rule.metadata
    if filters.kind == "engine" and metadata.rule_type != "engine":
        return False
    if filters.kind == "save" and metadata.rule_type == "engine":
        return False
    if filters.source != "all" and metadata.source != filters.source:
        return False
    if filters.status != "all" and metadata.status != filters.status:
        return False
    if filters.enabled == "enabled" and not metadata.enabled:
        return False
    if filters.enabled == "disabled" and metadata.enabled:
        return False
    query = " ".join(filters.query.casefold().split())
    haystack = " ".join(
        f"{metadata.qualified_id} {rule.label}".casefold().split()
    )
    return not query or query in haystack


def _summary_order(summary: RuleSummary) -> tuple[int, int, int, str, str]:
    type_rank = {"engine": 0, "save_game": 1, "save_engine": 2}
    return (
        type_rank[summary.rule_type],
        0 if summary.source == "user" else 1,
        0 if summary.status == "formal" else 1,
        summary.label.casefold(),
        summary.qualified_id,
    )


def _rules_by_id(snapshot: RuleSnapshot) -> dict[str, CatalogRule]:
    return {item.rule.metadata.rule_id: item for item in snapshot.rules}


def _copy_id(rule_id: str, occupied: set[str]) -> str:
    index = 1
    while True:
        suffix = "_copy" if index == 1 else f"_copy_{index}"
        prefix = rule_id[: 80 - len(suffix)].rstrip("_") or "rule"
        candidate = f"{prefix}{suffix}"
        if candidate not in occupied:
            return candidate
        index += 1


def _with_identity(
    rule: RuleDefinition,
    rule_id: str,
    source: RuleSource,
    status: RuleStatus,
) -> RuleDefinition:
    return replace(
        rule,
        metadata=replace(
            rule.metadata,
            rule_id=rule_id,
            source=source,
            status=status,
        ),
    )


def _with_status(rule: RuleDefinition, status: RuleStatus) -> RuleDefinition:
    return replace(rule, metadata=replace(rule.metadata, status=status))


def _source_display_name(rule: RuleDefinition, path: Path) -> str:
    if rule.metadata.source == "builtin":
        category = "engines" if rule.metadata.rule_type == "engine" else "saves"
        return f"builtin/{category}.yaml"
    category = "engines" if rule.metadata.rule_type == "engine" else "saves"
    return f"user/{category}/{path.name}"


def _mutation_error(error: Exception) -> RuleManagementError:
    if isinstance(error, RuleCatalogError) and error.diagnostics:
        diagnostic = error.diagnostics[0]
        return RuleManagementError(diagnostic.code, diagnostic.message)
    return RuleManagementError("rule_write_failed", "规则文件写入失败。")
