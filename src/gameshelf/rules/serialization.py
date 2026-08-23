"""Stable, non-executable serialization for declarative GameShelf rules."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import yaml

from gameshelf.engines.rule_schema import EngineRule, EvidenceRule
from gameshelf.saves.rule_schema import SaveRule, SaveRuleLocation

type RuleDefinition = EngineRule | SaveRule


def serialize_rule_document(rule: RuleDefinition) -> bytes:
    """Serialize exactly one rule as deterministic UTF-8 YAML with LF endings."""

    document = {
        "version": rule.metadata.version,
        "rules": [_rule_mapping(rule)],
    }
    rendered = yaml.safe_dump(
        document,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=120,
    )
    return rendered.replace("\r\n", "\n").encode("utf-8")


def verification_fingerprint(rule: RuleDefinition) -> str:
    """Hash only identity, matching evidence/selectors and produced locations."""

    if isinstance(rule, EngineRule):
        match: dict[str, Any] = {
            "variant": rule.variant,
            "threshold": rule.threshold,
            "all": [_evidence_mapping(item) for item in rule.required],
            "any": [_evidence_mapping(item) for item in rule.optional],
            "negative": [_evidence_mapping(item) for item in rule.negative],
        }
        payload: dict[str, Any] = {
            "id": rule.metadata.rule_id,
            "type": rule.metadata.rule_type,
            "match": match,
            "locations": [],
        }
    else:
        selectors = (
            {
                "titles": list(rule.titles),
                "product_ids": list(rule.product_ids),
            }
            if rule.metadata.rule_type == "save_game"
            else {"engine_ids": list(rule.engine_ids)}
        )
        payload = {
            "id": rule.metadata.rule_id,
            "type": rule.metadata.rule_type,
            "match": selectors,
            "locations": [_location_mapping(item) for item in rule.locations],
        }
    normalized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


def _rule_mapping(rule: RuleDefinition) -> dict[str, Any]:
    common: dict[str, Any] = {
        "id": rule.metadata.rule_id,
        "label": rule.label,
        "type": rule.metadata.rule_type,
        "status": rule.metadata.status,
        "priority": rule.metadata.priority,
        "enabled": rule.metadata.enabled,
    }
    if rule.notes is not None:
        common["notes"] = rule.notes
    common["references"] = list(rule.metadata.references)

    if isinstance(rule, EngineRule):
        if rule.variant is not None:
            common["variant"] = rule.variant
        common["threshold"] = rule.threshold
        common["all"] = [_evidence_mapping(item) for item in rule.required]
        common["any"] = [_evidence_mapping(item) for item in rule.optional]
        common["negative"] = [_evidence_mapping(item) for item in rule.negative]
        return common

    if rule.metadata.rule_type == "save_game":
        common["titles"] = list(rule.titles)
        if rule.product_ids:
            common["product_ids"] = list(rule.product_ids)
    else:
        common["engine_ids"] = list(rule.engine_ids)
    common["locations"] = [_location_mapping(item) for item in rule.locations]
    return common


def _evidence_mapping(evidence: EvidenceRule) -> dict[str, Any]:
    result: dict[str, Any] = {
        "op": evidence.op,
        "path": evidence.path,
    }
    if evidence.value is not None:
        result["value"] = evidence.value
    if evidence.offset:
        result["offset"] = evidence.offset
    result["weight"] = evidence.weight
    if evidence.field is not None:
        result["field"] = evidence.field
    return result


def _location_mapping(location: SaveRuleLocation) -> dict[str, Any]:
    return {
        "kind": location.kind,
        "path": location.path_template,
        "category": location.category,
        "confidence": location.confidence,
    }
