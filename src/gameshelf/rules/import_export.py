"""Bounded rule import sessions and canonical single-rule export."""

from __future__ import annotations

import os
import stat
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Lock
from typing import Literal
from uuid import uuid4

import yaml

from gameshelf.engines.rule_schema import RuleSchemaError, parse_engine_rule_document
from gameshelf.rules.catalog import CatalogRule, RuleCatalogError, RuleCatalogService
from gameshelf.rules.repository import RuleFileError, UserRuleRepository
from gameshelf.rules.serialization import RuleDefinition, serialize_rule_document
from gameshelf.saves.rule_schema import (
    SaveRuleSchemaError,
    parse_save_rule_document,
)

MAX_IMPORT_FILES = 32
MAX_IMPORT_FILE_BYTES = 1024 * 1024
MAX_IMPORT_TOTAL_BYTES = 4 * 1024 * 1024
MAX_IMPORT_SESSIONS = 8
IMPORT_SESSION_TTL_SECONDS = 30 * 60
_RULE_EXTENSIONS = frozenset({".yaml", ".yml"})
_REPARSE_FLAG = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)

type RuleImportAction = Literal["import", "replace", "new_id", "skip"]
type RuleImportConflict = Literal["none", "builtin", "user", "invalid"]


class RuleImportExportError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class RuleImportPreviewItem:
    item_id: str
    file_name: str
    valid: bool
    errors: tuple[str, ...]
    qualified_id: str | None
    rule_type: str | None
    status: str | None
    conflict: RuleImportConflict
    allowed_decisions: tuple[RuleImportAction, ...]


@dataclass(frozen=True, slots=True)
class RuleImportPreview:
    session_id: str
    items: tuple[RuleImportPreviewItem, ...]


@dataclass(frozen=True, slots=True)
class RuleImportDecision:
    item_id: str
    action: RuleImportAction
    new_rule_id: str | None


@dataclass(frozen=True, slots=True)
class RuleImportResult:
    imported_qualified_ids: tuple[str, ...]
    skipped_count: int
    generation: int


@dataclass(frozen=True, slots=True)
class RuleExportResult:
    file_name: str


@dataclass(frozen=True, slots=True)
class _ImportItem:
    preview: RuleImportPreviewItem
    rule: RuleDefinition | None
    conflict_rule: CatalogRule | None


@dataclass(frozen=True, slots=True)
class _ImportSession:
    session_id: str
    generation: int
    created_at: float
    items: tuple[_ImportItem, ...]


class RuleImportExportService:
    def __init__(
        self,
        *,
        catalog: RuleCatalogService,
        repository: UserRuleRepository,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._catalog = catalog
        self._repository = repository
        self._monotonic = monotonic
        self._sessions: dict[str, _ImportSession] = {}
        self._lock = Lock()

    def begin_import(self, paths: Sequence[Path]) -> RuleImportPreview:
        if not 1 <= len(paths) <= MAX_IMPORT_FILES:
            raise RuleImportExportError(
                "rule_import_file_count",
                f"一次只能导入 1～{MAX_IMPORT_FILES} 个规则文件。",
            )
        snapshot = self._catalog.snapshot()
        existing = {item.rule.metadata.rule_id: item for item in snapshot.rules}
        total = 0
        items: list[_ImportItem] = []
        for path in paths:
            if path.suffix.casefold() not in _RULE_EXTENSIONS:
                raise RuleImportExportError(
                    "rule_import_extension",
                    "只允许导入 .yaml 或 .yml 规则文件。",
                )
            if _is_link_or_reparse(path) or not path.is_file():
                raise RuleImportExportError(
                    "rule_import_file_unavailable",
                    f"无法读取规则文件：{path.name}",
                )
            try:
                size = path.stat(follow_symlinks=False).st_size
            except OSError as error:
                raise RuleImportExportError(
                    "rule_import_file_unavailable",
                    f"无法读取规则文件：{path.name}",
                ) from error
            if size > MAX_IMPORT_FILE_BYTES:
                raise RuleImportExportError(
                    "rule_import_file_too_large",
                    f"单个导入文件不能超过 1 MiB：{path.name}",
                )
            total += size
            if total > MAX_IMPORT_TOTAL_BYTES:
                raise RuleImportExportError(
                    "rule_import_total_too_large",
                    "导入文件总大小不能超过 4 MiB。",
                )
            try:
                content = path.read_bytes()
            except OSError as error:
                raise RuleImportExportError(
                    "rule_import_file_unavailable",
                    f"无法读取规则文件：{path.name}",
                ) from error
            if len(content) != size:
                raise RuleImportExportError(
                    "rule_import_file_changed",
                    f"规则文件在读取期间发生变化：{path.name}",
                )
            items.append(self._read_item(path.name, content, existing))

        now = self._monotonic()
        session_id = str(uuid4())
        session = _ImportSession(session_id, snapshot.generation, now, tuple(items))
        with self._lock:
            self._purge_expired(now)
            while len(self._sessions) >= MAX_IMPORT_SESSIONS:
                oldest = min(
                    self._sessions.values(),
                    key=lambda value: value.created_at,
                )
                self._sessions.pop(oldest.session_id, None)
            self._sessions[session_id] = session
        return RuleImportPreview(session_id, tuple(item.preview for item in items))

    def confirm_import(
        self,
        session_id: str,
        decisions: Sequence[RuleImportDecision],
    ) -> RuleImportResult:
        session = self._require_session(session_id)
        by_id = {decision.item_id: decision for decision in decisions}
        if len(by_id) != len(decisions) or set(by_id) != {
            item.preview.item_id for item in session.items
        }:
            raise RuleImportExportError(
                "invalid_rule_import_decisions",
                "必须为每个导入文件提供且只提供一个处理决定。",
            )
        if self._catalog.snapshot().generation != session.generation:
            raise RuleImportExportError(
                "stale_rule_import_session",
                "规则目录已经改变，请重新选择文件并预览。",
            )

        changes: dict[Path, bytes | None] = {}
        imported: list[str] = []
        skipped = 0
        targets: set[Path] = set()
        for item in session.items:
            decision = by_id[item.preview.item_id]
            if decision.action not in item.preview.allowed_decisions:
                raise RuleImportExportError(
                    "invalid_rule_import_decision",
                    f"文件 {item.preview.file_name} 不允许该处理决定。",
                )
            if decision.action == "skip":
                skipped += 1
                continue
            if item.rule is None:
                raise RuleImportExportError(
                    "invalid_rule_import_item",
                    f"文件 {item.preview.file_name} 不是有效规则。",
                )
            rule = item.rule
            if decision.action == "new_id":
                if not decision.new_rule_id:
                    raise RuleImportExportError(
                        "invalid_rule_import_new_id",
                        "另存为新规则时必须提供新 ID。",
                    )
                rule = replace(
                    rule,
                    metadata=replace(
                        rule.metadata,
                        rule_id=decision.new_rule_id,
                        source="user",
                    ),
                )
                try:
                    target = self._repository.rule_path(
                        rule.metadata.rule_type,
                        decision.new_rule_id,
                    )
                except RuleFileError as error:
                    raise RuleImportExportError(
                        "invalid_rule_import_new_id",
                        "导入规则的新 ID 无效。",
                    ) from error
            elif decision.action == "replace":
                conflict = item.conflict_rule
                if conflict is None or conflict.rule.metadata.source != "user":
                    raise RuleImportExportError(
                        "invalid_rule_import_decision",
                        "只能替换已有用户规则。",
                    )
                if conflict.rule.metadata.rule_type != rule.metadata.rule_type:
                    changes[conflict.source_path] = None
                    target = self._repository.rule_path(
                        rule.metadata.rule_type,
                        rule.metadata.rule_id,
                    )
                else:
                    target = conflict.source_path
            else:
                target = self._repository.rule_path(
                    rule.metadata.rule_type,
                    rule.metadata.rule_id,
                )
            if target in targets:
                raise RuleImportExportError(
                    "rule_import_target_conflict",
                    "多个导入项将写入同一个规则文件。",
                )
            targets.add(target)
            changes[target] = serialize_rule_document(rule)
            imported.append(rule.metadata.qualified_id)

        try:
            if changes:
                published = self._catalog.apply_user_changes(
                    changes,
                    self._catalog.current_settings(),
                    expected_generation=session.generation,
                )
            else:
                published = self._catalog.snapshot()
        except (RuleCatalogError, RuleFileError, OSError) as error:
            code = (
                error.diagnostics[0].code
                if isinstance(error, RuleCatalogError) and error.diagnostics
                else "rule_import_failed"
            )
            raise RuleImportExportError(code, "规则导入未写入任何文件。") from error
        with self._lock:
            self._sessions.pop(session_id, None)
        return RuleImportResult(tuple(imported), skipped, published.generation)

    def export_rule(self, qualified_id: str, destination: Path) -> RuleExportResult:
        item = next(
            (
                entry
                for entry in self._catalog.snapshot().rules
                if entry.rule.metadata.qualified_id == qualified_id
            ),
            None,
        )
        if item is None:
            raise RuleImportExportError("rule_not_found", "没有找到对应的规则。")
        if destination.suffix.casefold() not in _RULE_EXTENSIONS:
            raise RuleImportExportError(
                "rule_export_extension",
                "规则导出文件必须使用 .yaml 或 .yml 扩展名。",
            )
        if destination.exists() and _is_link_or_reparse(destination):
            raise RuleImportExportError(
                "rule_export_target_invalid",
                "规则导出目标不能是链接或重解析点。",
            )
        content = serialize_rule_document(item.rule)
        temporary = destination.parent / f".{destination.name}.{uuid4()}.tmp"
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with temporary.open("xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        except OSError as error:
            temporary.unlink(missing_ok=True)
            raise RuleImportExportError(
                "rule_export_failed",
                "规则文件导出失败。",
            ) from error
        return RuleExportResult(destination.name)

    def _read_item(
        self,
        file_name: str,
        content: bytes,
        existing: dict[str, CatalogRule],
    ) -> _ImportItem:
        item_id = str(uuid4())
        try:
            raw = yaml.safe_load(content.decode("utf-8"))
            rule = _parse_import_rule(raw)
        except (
            UnicodeError,
            yaml.YAMLError,
            RuleSchemaError,
            SaveRuleSchemaError,
        ) as error:
            preview = RuleImportPreviewItem(
                item_id,
                file_name,
                False,
                (str(error),),
                None,
                None,
                None,
                "invalid",
                ("skip",),
            )
            return _ImportItem(preview, None, None)
        conflict_rule = existing.get(rule.metadata.rule_id)
        if conflict_rule is None:
            conflict: RuleImportConflict = "none"
            allowed: tuple[RuleImportAction, ...] = ("import", "skip")
        elif conflict_rule.rule.metadata.source == "builtin":
            conflict = "builtin"
            allowed = ("new_id", "skip")
        else:
            conflict = "user"
            allowed = ("replace", "new_id", "skip")
        preview = RuleImportPreviewItem(
            item_id,
            file_name,
            True,
            (),
            rule.metadata.qualified_id,
            rule.metadata.rule_type,
            rule.metadata.status,
            conflict,
            allowed,
        )
        return _ImportItem(preview, rule, conflict_rule)

    def _require_session(self, session_id: str) -> _ImportSession:
        now = self._monotonic()
        with self._lock:
            self._purge_expired(now)
            session = self._sessions.get(session_id)
        if session is None:
            raise RuleImportExportError(
                "rule_import_session_not_found",
                "导入会话不存在或已经过期。",
            )
        return session

    def _purge_expired(self, now: float) -> None:
        expired = tuple(
            session_id
            for session_id, session in self._sessions.items()
            if now - session.created_at >= IMPORT_SESSION_TTL_SECONDS
        )
        for session_id in expired:
            self._sessions.pop(session_id, None)


def _parse_import_rule(raw: object) -> RuleDefinition:
    if not isinstance(raw, dict):
        raise RuleSchemaError("规则文件顶层必须是对象。")
    entries = raw.get("rules")
    if not isinstance(entries, list) or len(entries) != 1 or not isinstance(entries[0], dict):
        raise RuleSchemaError("每个导入文件必须恰好包含一条规则。")
    if entries[0].get("type") == "engine":
        return parse_engine_rule_document(
            raw,
            source="user",
            require_single=True,
        )[0]
    return parse_save_rule_document(
        raw,
        source="user",
        require_single=True,
    )[0]


def _is_link_or_reparse(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    return path.is_symlink() or bool(
        getattr(metadata, "st_file_attributes", 0) & _REPARSE_FLAG
    )
