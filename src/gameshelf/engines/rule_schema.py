"""Strict YAML schema for declarative engine evidence."""

from __future__ import annotations

import ntpath
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

import yaml

from gameshelf.engines.bounded_reader import MAX_BINARY_REGION
from gameshelf.rules.models import RuleMetadata
from gameshelf.rules.validation import RuleMetadataError, build_rule_metadata

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

_TOP_KEYS = {"version", "rules"}
_RULE_KEYS = {
    "id",
    "label",
    "variant",
    "status",
    "priority",
    "enabled",
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
    document = _mapping(raw, "document")
    _reject_unknown(document, _TOP_KEYS, "document")
    version = _string(document.get("version"), "version")
    entries = document.get("rules")
    if not isinstance(entries, list):
        raise RuleSchemaError("rules must be a list")
    rules = tuple(_parse_rule(_mapping(entry, "rule"), version) for entry in entries)
    seen: set[str] = set()
    for rule in rules:
        qualified_id = rule.metadata.qualified_id
        if qualified_id in seen:
            raise RuleSchemaError(f"duplicate engine rule id: {qualified_id}")
        seen.add(qualified_id)
    return rules


def _parse_rule(raw: dict[str, Any], version: str) -> EngineRule:
    _reject_unknown(raw, _RULE_KEYS, f"rule {raw.get('id', '?')}")
    engine_id = _string(raw.get("id"), "rule id")
    label = _string(raw.get("label", engine_id), "rule label")
    variant_raw = raw.get("variant")
    if variant_raw is not None and not isinstance(variant_raw, str):
        raise RuleSchemaError("variant must be a string or null")
    status = raw.get("status", "formal")
    experimental = status == "experimental"
    threshold = _number(raw.get("threshold", 0.8 if experimental else 0.7), "threshold")
    if not 0 <= threshold <= 1:
        raise RuleSchemaError("threshold must be between 0 and 1")
    try:
        metadata = build_rule_metadata(
            rule_id=engine_id,
            rule_type="engine",
            source="builtin",
            status=status,
            version=version,
            references=raw.get("references", []),
            priority=raw.get("priority", 0),
            enabled=raw.get("enabled", True),
        )
    except RuleMetadataError as error:
        raise RuleSchemaError(f"invalid metadata for rule {engine_id}: {error}") from error
    return EngineRule(
        metadata,
        label,
        variant_raw,
        threshold,
        _parse_evidence_list(raw.get("all", []), "all"),
        _parse_evidence_list(raw.get("any", []), "any"),
        _parse_evidence_list(raw.get("negative", []), "negative"),
    )


def _parse_evidence_list(raw: object, label: str) -> tuple[EvidenceRule, ...]:
    if not isinstance(raw, list):
        raise RuleSchemaError(f"{label} must be a list")
    result: list[EvidenceRule] = []
    for entry in raw:
        item = _mapping(entry, f"{label} evidence")
        _reject_unknown(item, _EVIDENCE_KEYS, f"{label} evidence")
        op = _string(item.get("op"), "evidence op")
        if op not in _OPS:
            raise RuleSchemaError(f"unsupported evidence operator: {op}")
        path = _relative_path(_string(item.get("path"), "evidence path"))
        weight = _number(item.get("weight"), "evidence weight")
        value = item.get("value")
        if value is not None and not isinstance(value, str):
            raise RuleSchemaError("evidence value must be a string")
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


def _relative_path(value: str) -> str:
    clean = value.replace("\\", "/")
    drive, _ = ntpath.splitdrive(clean)
    if drive or clean.startswith("/") or ".." in clean.split("/"):
        raise RuleSchemaError(f"evidence path must be relative: {value}")
    return clean


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
