"""Strict YAML schema for declarative engine evidence."""

from __future__ import annotations

import ntpath
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

import yaml

from gamesave_scout.engines.bounded_reader import MAX_BINARY_REGION
from gamesave_scout.rules.models import RuleMetadata, RuleSource
from gamesave_scout.rules.validation import RuleMetadataError, build_rule_metadata

type EvidenceOp = Literal[
    "path_exists",
    "glob_exists",
    "glob_magic_at",
    "magic_at",
    "magic_from_end",
    "edge_contains",
    "text_contains",
    "pe_field_contains",
]
type EngineCategory = Literal["general", "visual_novel_doujin"]

_TOP_KEYS = {"version", "rules"}
_RULE_KEYS = {
    "id",
    "label",
    "type",
    "variant",
    "category",
    "status",
    "priority",
    "enabled",
    "notes",
    "references",
    "threshold",
    "all",
    "any",
    "negative",
}
_EVIDENCE_KEYS = {"op", "path", "value", "offset", "weight", "field"}
_OPS = {
    "path_exists",
    "glob_exists",
    "glob_magic_at",
    "magic_at",
    "magic_from_end",
    "edge_contains",
    "text_contains",
    "pe_field_contains",
}
_PE_FIELDS = {"product_name", "file_description", "company_name", "architecture"}
_SOURCES = {"builtin", "user"}
MAX_RULES = 256
MAX_EVIDENCE_PER_RULE = 64
MAX_PATH_LENGTH = 1024
MAX_NOTES_LENGTH = 4096


class RuleSchemaError(ValueError):
    """Raised when bundled or user-supplied engine rules are malformed."""


@dataclass(frozen=True)
class EvidenceRule:
    op: EvidenceOp
    path: str
    weight: float
    value: str | None = None
    offset: int = 0
    field: str | None = None


@dataclass(frozen=True)
class EngineRule:
    metadata: RuleMetadata
    label: str
    notes: str | None
    category: EngineCategory | None
    variant: str | None
    threshold: float
    required: tuple[EvidenceRule, ...]
    optional: tuple[EvidenceRule, ...]
    negative: tuple[EvidenceRule, ...]

    @property
    def engine_id(self) -> str:
        return self.metadata.rule_id

    @property
    def experimental(self) -> bool:
        return self.metadata.status == "experimental"

    @property
    def version(self) -> str:
        return self.metadata.version


def load_engine_rules(path: Path) -> tuple[EngineRule, ...]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise RuleSchemaError(f"Cannot read engine rules: {error}") from error
    return parse_engine_rule_document(raw, source="builtin", require_single=False)


def parse_engine_rule_document(
    raw: object,
    *,
    source: RuleSource,
    require_single: bool,
) -> tuple[EngineRule, ...]:
    if source not in _SOURCES:
        raise RuleSchemaError(f"unsupported rule source: {source}")
    document = _mapping(raw, "document")
    _reject_unknown(document, _TOP_KEYS, "document")
    version = _string(document.get("version"), "version")
    entries = document.get("rules")
    if not isinstance(entries, list):
        raise RuleSchemaError("rules must be a list")
    if require_single and len(entries) != 1:
        raise RuleSchemaError("用户规则文件必须恰好包含一条规则。")
    if len(entries) > MAX_RULES:
        raise RuleSchemaError(f"规则文件最多 {MAX_RULES} 条规则。")
    rules = tuple(
        _parse_rule(_mapping(entry, "rule"), version, source) for entry in entries
    )
    seen: set[str] = set()
    for rule in rules:
        qualified_id = rule.metadata.qualified_id
        if qualified_id in seen:
            raise RuleSchemaError(f"duplicate engine rule id: {qualified_id}")
        seen.add(qualified_id)
    return rules


def _parse_rule(
    raw: dict[str, Any],
    version: str,
    source: RuleSource,
) -> EngineRule:
    _reject_unknown(raw, _RULE_KEYS, f"rule {raw.get('id', '?')}")
    engine_id = _string(raw.get("id"), "rule id")
    label = _string(raw.get("label", engine_id), "rule label")
    rule_type = raw.get("type", "engine")
    if rule_type != "engine":
        raise RuleSchemaError(f"unsupported engine rule type: {rule_type}")
    notes = _optional_notes(raw.get("notes"))
    category = _engine_category(raw.get("category"))
    variant_raw = raw.get("variant")
    if variant_raw is not None and not isinstance(variant_raw, str):
        raise RuleSchemaError("variant must be a string or null")
    status = raw.get("status", "formal" if source == "builtin" else "experimental")
    experimental = status == "experimental"
    threshold = _number(raw.get("threshold", 0.8 if experimental else 0.7), "threshold")
    if not 0 <= threshold <= 1:
        raise RuleSchemaError("threshold must be between 0 and 1")
    try:
        metadata = build_rule_metadata(
            rule_id=engine_id,
            rule_type="engine",
            source=source,
            status=status,
            version=version,
            references=raw.get("references", []),
            priority=raw.get("priority", 0),
            enabled=raw.get("enabled", True),
        )
    except RuleMetadataError as error:
        raise RuleSchemaError(f"invalid metadata for rule {engine_id}: {error}") from error
    if source == "builtin" and metadata.status == "formal" and not metadata.references:
        raise RuleSchemaError(
            f"正式规则 {metadata.qualified_id} 必须提供公开依据。"
        )
    required = _parse_evidence_list(raw.get("all", []), "all", source)
    optional = _parse_evidence_list(raw.get("any", []), "any", source)
    negative = _parse_evidence_list(raw.get("negative", []), "negative", source)
    if len(required) + len(optional) + len(negative) > MAX_EVIDENCE_PER_RULE:
        raise RuleSchemaError(f"每条规则最多 {MAX_EVIDENCE_PER_RULE} 项证据。")
    return EngineRule(
        metadata,
        label,
        notes,
        category,
        variant_raw,
        threshold,
        required,
        optional,
        negative,
    )


def _parse_evidence_list(
    raw: object,
    label: str,
    source: RuleSource,
) -> tuple[EvidenceRule, ...]:
    if not isinstance(raw, list):
        raise RuleSchemaError(f"{label} must be a list")
    result: list[EvidenceRule] = []
    for entry in raw:
        item = _mapping(entry, f"{label} evidence")
        _reject_unknown(item, _EVIDENCE_KEYS, f"{label} evidence")
        op = _string(item.get("op"), "evidence op")
        if op not in _OPS:
            raise RuleSchemaError(f"unsupported evidence operator: {op}")
        path = _relative_path(
            _string(item.get("path"), "evidence path"),
            source=source,
            allow_glob=op in {"glob_exists", "glob_magic_at"},
        )
        weight = _number(item.get("weight"), "evidence weight")
        value = item.get("value")
        if value is not None and not isinstance(value, str):
            raise RuleSchemaError("evidence value must be a string")
        if isinstance(value, str) and (len(value) > 4096 or "\x00" in value):
            raise RuleSchemaError("evidence value is too long or contains a null byte")
        offset = item.get("offset", 0)
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise RuleSchemaError("evidence offset must be a non-negative integer")
        if op == "magic_from_end" and not 0 < offset <= MAX_BINARY_REGION:
            raise RuleSchemaError(
                "magic_from_end offset must be between 1 and 65536 bytes"
            )
        field = item.get("field")
        if field is not None and not isinstance(field, str):
            raise RuleSchemaError("evidence field must be a string")
        if op == "pe_field_contains":
            if field is not None and field not in _PE_FIELDS:
                raise RuleSchemaError(f"unsupported PE metadata field: {field}")
        elif field is not None:
            raise RuleSchemaError(f"{op} does not support field")
        value_ops = {
            "glob_magic_at",
            "magic_at",
            "magic_from_end",
            "edge_contains",
            "text_contains",
            "pe_field_contains",
        }
        if op in value_ops and value is None:
            raise RuleSchemaError(f"{op} requires value")
        result.append(EvidenceRule(cast(EvidenceOp, op), path, weight, value, offset, field))
    return tuple(result)


def _relative_path(
    value: str,
    *,
    source: RuleSource,
    allow_glob: bool,
) -> str:
    clean = value.replace("\\", "/")
    drive, _ = ntpath.splitdrive(clean)
    parts = clean.split("/")
    if (
        len(clean) > MAX_PATH_LENGTH
        or "\x00" in clean
        or drive
        or clean.startswith("/")
        or ".." in parts
        or any(ord(character) < 32 for character in clean)
    ):
        raise RuleSchemaError(f"evidence path must be relative: {value}")
    if not allow_glob and any("*" in part or "?" in part for part in parts):
        raise RuleSchemaError("只有 glob 证据允许通配符路径。")
    if source == "user" and parts[0] == "**":
        raise RuleSchemaError("用户规则不允许从游戏目录根开始无界 ** glob。")
    return clean


def _optional_notes(value: object) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or len(value) > MAX_NOTES_LENGTH
        or "\x00" in value
    ):
        raise RuleSchemaError("notes must be a bounded string or null")
    return value


def _engine_category(value: object) -> EngineCategory | None:
    if value is None:
        return None
    if not isinstance(value, str) or value not in {
        "general",
        "visual_novel_doujin",
    }:
        raise RuleSchemaError(
            "category must be general or visual_novel_doujin"
        )
    return cast(EngineCategory, value)


def _reject_unknown(raw: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise RuleSchemaError(f"unknown key in {label}: {', '.join(unknown)}")


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise RuleSchemaError(f"{label} must be a mapping")
    return cast(dict[str, Any], value)


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise RuleSchemaError(f"{label} must be a non-empty string")
    return value


def _number(value: object, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise RuleSchemaError(f"{label} must be a number")
    return float(value)
