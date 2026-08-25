"""Strict, non-executable schema for bundled save-location rules."""

from __future__ import annotations

import ntpath
import re
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, Literal, cast

import yaml

from gamesave_scout.rules.models import RuleMetadata, RuleSource
from gamesave_scout.rules.validation import RuleMetadataError, build_rule_metadata
from gamesave_scout.saves.models import SaveLocationKind, SuggestionCategory

type SaveRuleType = Literal["save_game", "save_engine"]

MAX_RULES = 256
MAX_SELECTOR_VALUES = 64
MAX_LOCATIONS_PER_RULE = 32
MAX_PATH_LENGTH = 1024

_TOP_KEYS = {"version", "rules"}
_COMMON_RULE_KEYS = {
    "id",
    "label",
    "type",
    "status",
    "priority",
    "enabled",
    "notes",
    "references",
    "locations",
}
_GAME_RULE_KEYS = _COMMON_RULE_KEYS | {"titles", "product_ids"}
_ENGINE_RULE_KEYS = _COMMON_RULE_KEYS | {"engine_ids"}
_LOCATION_KEYS = {"kind", "path", "category", "confidence", "require_existing"}
_LOCATION_KINDS = {"directory", "file", "glob", "registry"}
_CATEGORIES = {"save", "config", "other"}
_FILESYSTEM_TOKENS = {
    "<game>",
    "<home>",
    "<winAppData>",
    "<winLocalAppData>",
    "<winLocalAppDataLow>",
    "<winDocuments>",
    "<winSavedGames>",
    "<winProgramData>",
    "<winPublic>",
    "<winDir>",
}
_METADATA_FIELDS = {
    "company_name",
    "product_name",
    "project_name",
    "renpy_save_directory",
}
_REGISTRY_ROOTS = {"HKEY_CURRENT_USER", "HKEY_LOCAL_MACHINE"}
_SOURCES = {"builtin", "user"}
_PRODUCT_ID = re.compile(
    r"(?:steam|gog|epic|itch|vndb|dlsite):[A-Za-z0-9._-]{1,96}\Z"
)
_ENGINE_ID = re.compile(r"[a-z0-9_]{1,80}\Z")
_ROOT_TEMPLATE = re.compile(r"(<[^<>\\/]+>)(?:[\\/](.*))?\Z")
_PLACEHOLDER_SEGMENT = re.compile(
    r"\{(company_name|product_name|project_name|renpy_save_directory)\}\Z"
)


class SaveRuleSchemaError(ValueError):
    """Raised when a save rule could escape the declarative safety boundary."""


@dataclass(frozen=True, slots=True)
class SaveRuleLocation:
    kind: SaveLocationKind
    path_template: str
    category: SuggestionCategory
    confidence: float
    metadata_fields: tuple[str, ...]
    require_existing: bool = False


@dataclass(frozen=True, slots=True)
class SaveRule:
    metadata: RuleMetadata
    label: str
    notes: str | None
    titles: tuple[str, ...]
    product_ids: tuple[str, ...]
    engine_ids: tuple[str, ...]
    locations: tuple[SaveRuleLocation, ...]


def load_save_rules(path: Path) -> tuple[SaveRule, ...]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise SaveRuleSchemaError(f"Cannot read save rules: {error}") from error

    return parse_save_rule_document(raw, source="builtin", require_single=False)


def parse_save_rule_document(
    raw: object,
    *,
    source: RuleSource,
    require_single: bool,
) -> tuple[SaveRule, ...]:
    if source not in _SOURCES:
        raise SaveRuleSchemaError(f"unsupported rule source: {source}")
    document = _mapping(raw, "document")
    _reject_unknown(document, _TOP_KEYS, "document")
    version = _text(document.get("version"), "version")
    entries = document.get("rules")
    if not isinstance(entries, list):
        raise SaveRuleSchemaError("rules must be a list")
    if require_single and len(entries) != 1:
        raise SaveRuleSchemaError("用户规则文件必须恰好包含一条规则。")
    if len(entries) > MAX_RULES:
        raise SaveRuleSchemaError(f"规则文件最多 {MAX_RULES} 条规则。")

    rules = tuple(
        _parse_rule(_mapping(entry, f"rule {index}"), version, source)
        for index, entry in enumerate(entries, start=1)
    )
    seen: set[str] = set()
    for rule in rules:
        qualified_id = rule.metadata.qualified_id
        if qualified_id in seen:
            raise SaveRuleSchemaError(f"duplicate save rule id: {qualified_id}")
        seen.add(qualified_id)
    return rules


def _parse_rule(
    raw: dict[str, Any],
    version: str,
    source: RuleSource,
) -> SaveRule:
    rule_type = _text(raw.get("type"), "rule type")
    if rule_type == "save_game":
        allowed = _GAME_RULE_KEYS
    elif rule_type == "save_engine":
        allowed = _ENGINE_RULE_KEYS
    else:
        raise SaveRuleSchemaError(f"unsupported save rule type: {rule_type}")
    _reject_unknown(raw, allowed, f"rule {raw.get('id', '?')}")

    rule_id = _text(raw.get("id"), "rule id")
    label = _text(raw.get("label"), "rule label")
    notes = _optional_notes(raw.get("notes"))
    try:
        metadata = build_rule_metadata(
            rule_id=rule_id,
            rule_type=rule_type,
            source=source,
            status=raw.get(
                "status", "formal" if source == "builtin" else "experimental"
            ),
            version=version,
            references=raw.get("references", []),
            priority=raw.get("priority", 0),
            enabled=raw.get("enabled", True),
        )
    except RuleMetadataError as error:
        raise SaveRuleSchemaError(
            f"invalid metadata for save rule {rule_id}: {error}"
        ) from error
    if (
        source == "builtin"
        and metadata.status == "formal"
        and not metadata.references
    ):
        raise SaveRuleSchemaError(f"正式规则 {metadata.qualified_id} 必须提供公开依据。")

    if rule_type == "save_game":
        titles = _selector_values(raw.get("titles"), "titles")
        product_ids = _selector_values(
            raw.get("product_ids", []), "product_ids", allow_empty=True
        )
        for product_id in product_ids:
            if _PRODUCT_ID.fullmatch(product_id) is None:
                raise SaveRuleSchemaError(f"不受支持的产品编号：{product_id}")
        engine_ids: tuple[str, ...] = ()
    else:
        titles = ()
        product_ids = ()
        engine_ids = _selector_values(raw.get("engine_ids"), "engine_ids")
        for engine_id in engine_ids:
            if _ENGINE_ID.fullmatch(engine_id) is None:
                raise SaveRuleSchemaError(f"无效的 engine_ids 值：{engine_id}")

    locations_raw = raw.get("locations")
    if not isinstance(locations_raw, list) or not locations_raw:
        raise SaveRuleSchemaError("locations must be a non-empty list")
    if len(locations_raw) > MAX_LOCATIONS_PER_RULE:
        raise SaveRuleSchemaError(
            f"每条规则最多 {MAX_LOCATIONS_PER_RULE} 个存档位置。"
        )
    locations = tuple(
        _parse_location(_mapping(entry, "save location"), source)
        for entry in locations_raw
    )
    return SaveRule(
        metadata,
        label,
        notes,
        titles,
        product_ids,
        engine_ids,
        locations,
    )


def _parse_location(
    raw: dict[str, Any],
    source: RuleSource,
) -> SaveRuleLocation:
    _reject_unknown(raw, _LOCATION_KEYS, "save location")
    kind = _text(raw.get("kind"), "location kind")
    if kind not in _LOCATION_KINDS:
        raise SaveRuleSchemaError(f"unsupported save location kind: {kind}")
    category = _text(raw.get("category"), "location category")
    if category not in _CATEGORIES:
        raise SaveRuleSchemaError(f"unsupported save location category: {category}")
    confidence_raw = raw.get("confidence")
    if (
        not isinstance(confidence_raw, (int, float))
        or isinstance(confidence_raw, bool)
        or not 0 <= float(confidence_raw) <= 1
    ):
        raise SaveRuleSchemaError("location confidence must be between 0 and 1")
    path_template = _text(raw.get("path"), "location path")
    if len(path_template) > MAX_PATH_LENGTH or "\x00" in path_template:
        raise SaveRuleSchemaError("存档路径模板过长或包含空字符。")
    metadata_fields = _validate_path_template(
        path_template,
        cast(SaveLocationKind, kind),
        source,
    )
    require_existing = raw.get("require_existing", False)
    if not isinstance(require_existing, bool):
        raise SaveRuleSchemaError("location require_existing must be a boolean")
    return SaveRuleLocation(
        kind=cast(SaveLocationKind, kind),
        path_template=path_template,
        category=cast(SuggestionCategory, category),
        confidence=float(confidence_raw),
        metadata_fields=metadata_fields,
        require_existing=require_existing,
    )


def _validate_path_template(
    path_template: str,
    kind: SaveLocationKind,
    source: RuleSource,
) -> tuple[str, ...]:
    if kind == "registry":
        normalized = path_template.replace("/", "\\")
        parts = tuple(part for part in normalized.split("\\") if part)
        if len(parts) < 2 or parts[0] not in _REGISTRY_ROOTS:
            raise SaveRuleSchemaError("注册表根只允许 HKEY_CURRENT_USER 或 HKEY_LOCAL_MACHINE。")
        if path_template.startswith(("\\", "/")) or "<" in path_template:
            raise SaveRuleSchemaError("注册表模板不能使用文件系统令牌。")
        if any(part == ".." for part in parts):
            raise SaveRuleSchemaError("注册表模板不能离开声明的注册表根。")
        if any("*" in part or "?" in part for part in parts):
            raise SaveRuleSchemaError("注册表模板不能包含通配符。")
        return _metadata_fields(parts[1:])

    match = _ROOT_TEMPLATE.fullmatch(path_template)
    if match is None:
        raise SaveRuleSchemaError("文件系统模板必须从白名单路径令牌开始。")
    token, suffix = match.groups()
    if token not in _FILESYSTEM_TOKENS:
        raise SaveRuleSchemaError(f"未知的路径令牌：{token}")
    if suffix is None or suffix == "":
        return ()
    drive, _ = ntpath.splitdrive(suffix)
    if drive or ntpath.isabs(suffix):
        raise SaveRuleSchemaError("路径令牌后的内容必须是相对路径。")
    parts = PureWindowsPath(suffix).parts
    if any(part == ".." for part in parts):
        raise SaveRuleSchemaError("路径模板不能离开令牌根目录。")
    if any("<" in part or ">" in part for part in parts):
        raise SaveRuleSchemaError("路径后缀不能包含其他令牌。")
    if kind != "glob" and any("*" in part or "?" in part for part in parts):
        raise SaveRuleSchemaError("只有 glob 位置允许通配符。")
    if source == "user" and parts and parts[0] == "**":
        raise SaveRuleSchemaError("用户规则不允许从令牌根开始无界 ** glob。")
    return _metadata_fields(parts)


def _optional_notes(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 4096 or "\x00" in value:
        raise SaveRuleSchemaError("notes must be a bounded string or null")
    return value


def _metadata_fields(parts: tuple[str, ...]) -> tuple[str, ...]:
    result: list[str] = []
    for part in parts:
        if "{" not in part and "}" not in part:
            continue
        match = _PLACEHOLDER_SEGMENT.fullmatch(part)
        if match is None:
            known = next(
                (field for field in _METADATA_FIELDS if f"{{{field}}}" in part),
                None,
            )
            if known is not None:
                raise SaveRuleSchemaError("元数据占位符必须占满一个完整路径段。")
            raise SaveRuleSchemaError(f"未知的元数据占位符：{part}")
        field = match.group(1)
        if field not in result:
            result.append(field)
    return tuple(result)


def _selector_values(
    raw: object,
    label: str,
    *,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if not isinstance(raw, list) or (not raw and not allow_empty):
        raise SaveRuleSchemaError(f"{label} must be a non-empty list")
    if len(raw) > MAX_SELECTOR_VALUES:
        raise SaveRuleSchemaError(f"{label} 最多 {MAX_SELECTOR_VALUES} 项。")
    result: list[str] = []
    for value in raw:
        if (
            not isinstance(value, str)
            or not value
            or value != value.strip()
            or len(value) > 256
            or any(ord(character) < 32 for character in value)
        ):
            raise SaveRuleSchemaError(f"{label} 必须包含非空的受限字符串。")
        if value not in result:
            result.append(value)
    return tuple(result)


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise SaveRuleSchemaError(f"{label} must be a mapping")
    return cast(dict[str, Any], value)


def _reject_unknown(raw: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise SaveRuleSchemaError(f"unknown key in {label}: {', '.join(unknown)}")


def _text(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(ord(character) < 32 for character in value)
    ):
        raise SaveRuleSchemaError(f"{label} must be a non-empty string")
    return value
