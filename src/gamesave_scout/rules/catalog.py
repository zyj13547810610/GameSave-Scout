"""Compile immutable runtime snapshots from bundled and user rule files."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Lock, RLock

import yaml

from gamesave_scout.engines.rule_schema import (
    EngineRule,
    RuleSchemaError,
    load_engine_rules,
    parse_engine_rule_document,
)
from gamesave_scout.engines.service import BUILTIN_ENGINE_IDS, EngineDetectionService
from gamesave_scout.rules.models import RuleDiagnostic
from gamesave_scout.rules.repository import RuleFileError, UserRuleRepository
from gamesave_scout.rules.serialization import RuleDefinition, serialize_rule_document
from gamesave_scout.rules.settings import RuleSettings, RuleSettingsStore
from gamesave_scout.saves.builtin_rules import SaveRuleProvider
from gamesave_scout.saves.rule_schema import (
    SaveRule,
    SaveRuleSchemaError,
    load_save_rules,
    parse_save_rule_document,
)
from gamesave_scout.saves.templates import PathTemplateResolver


@dataclass(frozen=True, slots=True)
class CatalogRule:
    rule: RuleDefinition
    source_path: Path


@dataclass(frozen=True, slots=True)
class RuleSnapshot:
    generation: int
    catalog_version: str
    engine_detection: EngineDetectionService
    save_rules: SaveRuleProvider
    rules: tuple[CatalogRule, ...]
    diagnostics: tuple[RuleDiagnostic, ...]


@dataclass(frozen=True, slots=True)
class RuleRefreshResult:
    applied: bool
    snapshot: RuleSnapshot
    diagnostics: tuple[RuleDiagnostic, ...]


class RuleCatalogError(ValueError):
    def __init__(
        self,
        message: str,
        diagnostics: Sequence[RuleDiagnostic] = (),
    ) -> None:
        super().__init__(message)
        self.diagnostics = tuple(diagnostics)


@dataclass(frozen=True, slots=True)
class _BuiltinRules:
    engines: tuple[EngineRule, ...]
    saves: tuple[SaveRule, ...]
    diagnostics: tuple[RuleDiagnostic, ...]


class RuleCatalogService:
    """Own one current snapshot and replace it only after complete compilation."""

    def __init__(
        self,
        *,
        builtin_engine_file: Path,
        builtin_save_file: Path,
        repository: UserRuleRepository,
        settings_store: RuleSettingsStore,
        resolver: PathTemplateResolver,
        legacy_manifest_dir: Path,
        logger: logging.Logger | None = None,
    ) -> None:
        self.builtin_engine_file = builtin_engine_file
        self.builtin_save_file = builtin_save_file
        self.legacy_manifest_dir = legacy_manifest_dir
        self._repository = repository
        self._settings_store = settings_store
        self._resolver = resolver
        self._logger = logger or logging.getLogger(__name__)
        self._snapshot_lock = RLock()
        self._mutation_lock = Lock()

        files = self._repository.read_all()
        builtins = self._load_builtins()
        settings_result = self._settings_store.load(_builtin_ids(builtins))
        self._snapshot = self._compile_loaded(
            files,
            settings_result.settings,
            builtins,
            generation=1,
            extra_diagnostics=settings_result.diagnostics,
        )

    def snapshot(self) -> RuleSnapshot:
        with self._snapshot_lock:
            return self._snapshot

    @property
    def repository(self) -> UserRuleRepository:
        return self._repository

    def refresh(self) -> RuleRefreshResult:
        with self._mutation_lock:
            try:
                files = self._repository.read_all()
                builtins = self._load_builtins()
                settings_result = self._settings_store.load(_builtin_ids(builtins))
                candidate = self._compile_loaded(
                    files,
                    settings_result.settings,
                    builtins,
                    generation=self.snapshot().generation + 1,
                    extra_diagnostics=settings_result.diagnostics,
                )
            except (RuleFileError, RuleCatalogError, RuleSchemaError, SaveRuleSchemaError) as error:
                current = self.snapshot()
                diagnostics = _error_diagnostics(error)
                return RuleRefreshResult(False, current, diagnostics)
            published = self.publish(candidate)
            return RuleRefreshResult(True, published, published.diagnostics)

    def compile_candidate(
        self,
        files: Mapping[Path, bytes],
        settings: RuleSettings,
    ) -> RuleSnapshot:
        builtins = self._load_builtins()
        return self._compile_loaded(
            files,
            settings,
            builtins,
            generation=self.snapshot().generation + 1,
        )

    def apply_user_changes(
        self,
        changes: Mapping[Path, bytes | None],
        settings: RuleSettings,
        *,
        expected_generation: int | None = None,
    ) -> RuleSnapshot:
        with self._mutation_lock:
            if (
                expected_generation is not None
                and self.snapshot().generation != expected_generation
            ):
                diagnostic = RuleDiagnostic(
                    "error",
                    "stale_rule_catalog",
                    "规则目录已被其他操作更新，请刷新后重试。",
                    "rules",
                )
                raise RuleCatalogError(diagnostic.message, (diagnostic,))
            original = dict(self._repository.read_all())
            candidate_files = dict(original)
            for path, content in changes.items():
                if content is None:
                    candidate_files.pop(path, None)
                else:
                    candidate_files[path] = content
            builtins = self._load_builtins()
            candidate = self._compile_loaded(
                candidate_files,
                settings,
                builtins,
                generation=self.snapshot().generation + 1,
            )
            self._repository.apply_batch(changes)
            try:
                self._settings_store.save(settings)
            except OSError:
                rollback = {
                    path: original.get(path)
                    for path in changes
                }
                self._repository.apply_batch(rollback)
                raise
            return self.publish(candidate)

    def current_settings(self) -> RuleSettings:
        builtins = self._load_builtins()
        return self._settings_store.load(_builtin_ids(builtins)).settings

    def publish(self, snapshot: RuleSnapshot) -> RuleSnapshot:
        with self._snapshot_lock:
            self._snapshot = snapshot
            return self._snapshot

    def _load_builtins(self) -> _BuiltinRules:
        diagnostics: list[RuleDiagnostic] = []
        try:
            engines = load_engine_rules(self.builtin_engine_file)
        except (RuleSchemaError, UnicodeError) as error:
            if not self.builtin_engine_file.is_file() or isinstance(error.__cause__, OSError):
                raise
            engines = ()
            diagnostics.append(
                RuleDiagnostic(
                    "warning",
                    "invalid_builtin_engine_rules",
                    f"声明式引擎规则加载失败，已仅启用内置检测器：{error}",
                    "builtin/engines.yaml",
                )
            )
        try:
            saves = load_save_rules(self.builtin_save_file)
        except (SaveRuleSchemaError, UnicodeError) as error:
            if not self.builtin_save_file.is_file() or isinstance(error.__cause__, OSError):
                raise
            saves = ()
            diagnostics.append(
                RuleDiagnostic(
                    "warning",
                    "invalid_builtin_save_rules",
                    f"内置存档规则加载失败，已禁用该建议来源：{error}",
                    "builtin/saves.yaml",
                )
            )
        return _BuiltinRules(engines, saves, tuple(diagnostics))

    def _compile_loaded(
        self,
        files: Mapping[Path, bytes],
        settings: RuleSettings,
        builtins: _BuiltinRules,
        *,
        generation: int,
        extra_diagnostics: Sequence[RuleDiagnostic] = (),
    ) -> RuleSnapshot:
        known_builtin_ids = _builtin_ids(builtins)
        invalid_disabled = settings.disabled_builtin_rule_ids - known_builtin_ids
        if settings.version != 1 or invalid_disabled:
            diagnostic = RuleDiagnostic(
                "error",
                "invalid_rule_settings",
                "规则设置包含不受支持的版本或未知内置规则。",
                "settings.json",
            )
            raise RuleCatalogError(diagnostic.message, (diagnostic,))

        diagnostics = [*builtins.diagnostics, *extra_diagnostics]
        catalog_rules: list[CatalogRule] = [
            *(CatalogRule(rule, self.builtin_engine_file) for rule in builtins.engines),
            *(CatalogRule(rule, self.builtin_save_file) for rule in builtins.saves),
        ]
        for path, content in _ordered_files(files):
            try:
                raw = yaml.safe_load(content.decode("utf-8"))
                kind = self._user_rule_kind(path)
                parsed: tuple[RuleDefinition, ...]
                if kind == "engine":
                    parsed = parse_engine_rule_document(
                        raw,
                        source="user",
                        require_single=True,
                    )
                else:
                    parsed = parse_save_rule_document(
                        raw,
                        source="user",
                        require_single=True,
                    )
            except (UnicodeError, yaml.YAMLError, RuleSchemaError, SaveRuleSchemaError) as error:
                diagnostics.append(
                    RuleDiagnostic(
                        "warning",
                        "invalid_user_rule",
                        f"用户规则无效，已隔离该文件：{error}",
                        self._source_name(path),
                    )
                )
                continue
            catalog_rules.extend(CatalogRule(rule, path) for rule in parsed)

        self._validate_global_ids(catalog_rules)
        disabled = settings.disabled_builtin_rule_ids
        adjusted = tuple(
            CatalogRule(_with_builtin_enabled(item.rule, disabled), item.source_path)
            for item in catalog_rules
        )
        adjusted = tuple(sorted(adjusted, key=_catalog_rule_order))
        engine_rules = tuple(
            item.rule for item in adjusted if isinstance(item.rule, EngineRule)
        )
        save_rules = tuple(
            item.rule for item in adjusted if isinstance(item.rule, SaveRule)
        )
        if self.legacy_manifest_dir.exists():
            diagnostics.append(
                RuleDiagnostic(
                    "warning",
                    "legacy_manifest_detected",
                    "检测到已废弃的 data/manifests 目录；程序不会加载其中内容。",
                    "data/manifests",
                )
            )
        catalog_version = _catalog_version(adjusted, disabled)
        return RuleSnapshot(
            generation=generation,
            catalog_version=catalog_version,
            engine_detection=EngineDetectionService.from_rules(engine_rules),
            save_rules=SaveRuleProvider(save_rules, self._resolver, self._logger),
            rules=adjusted,
            diagnostics=tuple(diagnostics),
        )

    def _user_rule_kind(self, path: Path) -> str:
        parent = path.parent.resolve(strict=False)
        if parent == self._repository.engine_dir.resolve(strict=False):
            return "engine"
        if parent == self._repository.save_dir.resolve(strict=False):
            return "save"
        diagnostic = RuleDiagnostic(
            "error",
            "invalid_user_rule_path",
            "规则文件不在用户规则目录内。",
            path.name,
        )
        raise RuleCatalogError(diagnostic.message, (diagnostic,))

    def _source_name(self, path: Path) -> str:
        kind = self._user_rule_kind(path)
        return f"user/{'engines' if kind == 'engine' else 'saves'}/{path.name}"

    @staticmethod
    def _validate_global_ids(rules: Sequence[CatalogRule]) -> None:
        seen: dict[str, CatalogRule] = {}
        for item in rules:
            rule_id = item.rule.metadata.rule_id
            if item.rule.metadata.source == "user" and rule_id in BUILTIN_ENGINE_IDS:
                diagnostic = RuleDiagnostic(
                    "error",
                    "rule_id_conflict",
                    f"用户规则不能复用专用内置引擎 ID：{rule_id}",
                    item.source_path.name,
                )
                raise RuleCatalogError(diagnostic.message, (diagnostic,))
            previous = seen.get(rule_id)
            if previous is not None:
                diagnostic = RuleDiagnostic(
                    "error",
                    "rule_id_conflict",
                    f"规则 ID 必须在所有类型和来源中唯一：{rule_id}",
                    item.source_path.name,
                )
                raise RuleCatalogError(diagnostic.message, (diagnostic,))
            seen[rule_id] = item


def _builtin_ids(builtins: _BuiltinRules) -> frozenset[str]:
    engine_ids = frozenset(rule.metadata.qualified_id for rule in builtins.engines)
    save_ids = frozenset(rule.metadata.qualified_id for rule in builtins.saves)
    return engine_ids | save_ids


def _with_builtin_enabled(
    rule: RuleDefinition,
    disabled: frozenset[str],
) -> RuleDefinition:
    if rule.metadata.qualified_id not in disabled:
        return rule
    return replace(rule, metadata=replace(rule.metadata, enabled=False))


def _ordered_files(files: Mapping[Path, bytes]) -> tuple[tuple[Path, bytes], ...]:
    return tuple(
        sorted(
            files.items(),
            key=lambda item: (str(item[0].parent).casefold(), item[0].name.casefold()),
        )
    )


def _catalog_rule_order(item: CatalogRule) -> tuple[int, int, str]:
    metadata = item.rule.metadata
    type_order = {"engine": 0, "save_game": 1, "save_engine": 2}
    return (
        0 if metadata.source == "builtin" else 1,
        type_order[metadata.rule_type],
        metadata.rule_id,
    )


def _catalog_version(
    rules: Sequence[CatalogRule],
    disabled: frozenset[str],
) -> str:
    content = b"\0".join(serialize_rule_document(item.rule) for item in rules)
    content += b"\0disabled\0" + "\n".join(sorted(disabled)).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _error_diagnostics(error: Exception) -> tuple[RuleDiagnostic, ...]:
    if isinstance(error, RuleCatalogError) and error.diagnostics:
        return error.diagnostics
    return (
        RuleDiagnostic(
            "error",
            "rule_catalog_refresh_failed",
            f"规则目录刷新失败：{error}",
            "rules",
        ),
    )
