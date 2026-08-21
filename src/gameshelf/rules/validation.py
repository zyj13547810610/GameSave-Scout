"""Validate metadata shared by engine and save rules."""

from __future__ import annotations

import re
from typing import cast
from urllib.parse import urlsplit

from gameshelf.rules.models import (
    RuleMetadata,
    RuleSource,
    RuleStatus,
    RuleType,
)

_RULE_ID = re.compile(r"[a-z0-9_]{1,80}\Z")
_RULE_TYPES = {"engine", "save_game", "save_engine"}
_RULE_SOURCES = {"builtin", "user"}
_RULE_STATUSES = {"formal", "experimental"}


class RuleMetadataError(ValueError):
    """Raised when shared rule metadata is invalid."""


def validate_rule_id(value: object) -> str:
    if not isinstance(value, str) or _RULE_ID.fullmatch(value) is None:
        raise RuleMetadataError(
            "规则 ID 必须由 1～80 个小写 ASCII 字母、数字或下划线组成。"
        )
    return value


def parse_rule_references(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise RuleMetadataError("公开依据必须是 URL 列表。")
    result: list[str] = []
    for entry in value:
        if not isinstance(entry, str) or not entry or entry != entry.strip():
            raise RuleMetadataError("公开依据必须是非空 HTTPS URL。")
        parsed = urlsplit(entry)
        if parsed.scheme != "https" or not parsed.netloc:
            raise RuleMetadataError("公开依据必须是非空 HTTPS URL。")
        if entry not in result:
            result.append(entry)
    return tuple(result)


def build_rule_metadata(
    *,
    rule_id: object,
    rule_type: object,
    source: object,
    status: object,
    version: object,
    references: object,
    priority: object,
    enabled: object,
) -> RuleMetadata:
    normalized_id = validate_rule_id(rule_id)
    normalized_type = _choice(rule_type, _RULE_TYPES, "规则类型")
    normalized_source = _choice(source, _RULE_SOURCES, "规则来源")
    normalized_status = _choice(status, _RULE_STATUSES, "规则状态")
    if (
        not isinstance(version, str)
        or not version
        or version != version.strip()
        or any(ord(character) < 32 for character in version)
    ):
        raise RuleMetadataError("规则版本必须是非空且不含控制字符的字符串。")
    if (
        not isinstance(priority, int)
        or isinstance(priority, bool)
        or not -1000 <= priority <= 1000
    ):
        raise RuleMetadataError("规则优先级必须是 -1000～1000 的整数。")
    if not isinstance(enabled, bool):
        raise RuleMetadataError("规则启用状态必须是布尔值。")
    return RuleMetadata(
        rule_id=normalized_id,
        rule_type=cast(RuleType, normalized_type),
        source=cast(RuleSource, normalized_source),
        status=cast(RuleStatus, normalized_status),
        version=version,
        references=parse_rule_references(references),
        priority=priority,
        enabled=enabled,
    )


def _choice(value: object, allowed: set[str], label: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise RuleMetadataError(f"{label}不受支持。")
    return value
