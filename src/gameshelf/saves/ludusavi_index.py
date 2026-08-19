"""Validated, read-only access to a derived Ludusavi SQLite index."""

from __future__ import annotations

import fnmatch
import json
import re
import sqlite3
from collections.abc import Collection, Mapping
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, cast

from gameshelf.saves.ludusavi_models import (
    ManifestCondition,
    ManifestGame,
    ManifestLocationRule,
)
from gameshelf.scanning.path_keys import windows_path_key

INDEX_SCHEMA_VERSION = 2
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_EXPECTED_COLUMNS = {
    "index_metadata": ("key", "value"),
    "games": ("id", "canonical_name"),
    "names": (
        "game_id",
        "candidate_order",
        "source",
        "display_name",
        "normalized_name",
    ),
    "locations": (
        "game_id",
        "location_order",
        "kind",
        "path",
        "tags_json",
        "conditions_json",
    ),
    "path_rules": (
        "game_id",
        "location_order",
        "kind",
        "root_token",
        "relative_pattern",
        "first_segment_key",
        "specificity",
        "tags_json",
        "conditions_json",
    ),
}

type IndexedNameSource = Literal["canonical", "install_dir", "alias"]
type IndexedPathRuleKind = Literal["file", "registry"]


class InvalidLudusaviIndex(ValueError):
    """The index is corrupt, stale, or outside the supported schema."""


@dataclass(frozen=True, slots=True)
class LudusaviIndexMetadata:
    schema_version: int
    manifest_sha256: str
    game_count: int
    name_count: int
    path_rule_count: int


@dataclass(frozen=True, slots=True)
class IndexedName:
    game_id: int
    display_name: str
    normalized_name: str
    source: IndexedNameSource
    candidate_order: int


@dataclass(frozen=True, slots=True)
class IndexedPathRule:
    game_id: int
    canonical_name: str
    kind: IndexedPathRuleKind
    root_token: str
    relative_pattern: str
    first_segment_key: str
    specificity: int
    tags: frozenset[str]
    conditions: tuple[ManifestCondition, ...]


class LudusaviIndex:
    """A validated index handle that opens a short read-only connection per read."""

    def __init__(self, path: Path, metadata: LudusaviIndexMetadata) -> None:
        self._path = path
        self.metadata = metadata

    @classmethod
    def open(cls, path: Path, *, manifest_sha256: str) -> LudusaviIndex:
        if not _SHA256_PATTERN.fullmatch(manifest_sha256):
            raise InvalidLudusaviIndex("Ludusavi 源清单摘要格式无效。")
        if not path.is_file():
            raise InvalidLudusaviIndex(f"Ludusavi SQLite 索引不存在：{path}")
        try:
            with closing(_connect_read_only(path)) as connection:
                _validate_schema(connection)
                metadata = _read_index_metadata(connection)
                if metadata.manifest_sha256 != manifest_sha256:
                    raise InvalidLudusaviIndex("Ludusavi 索引与源清单摘要不一致。")
                actual_game_count = cast(
                    int,
                    connection.execute("SELECT COUNT(*) FROM games").fetchone()[0],
                )
                actual_name_count = cast(
                    int,
                    connection.execute("SELECT COUNT(*) FROM names").fetchone()[0],
                )
                actual_path_rule_count = cast(
                    int,
                    connection.execute("SELECT COUNT(*) FROM path_rules").fetchone()[
                        0
                    ],
                )
                if (
                    metadata.game_count != actual_game_count
                    or metadata.name_count != actual_name_count
                    or metadata.path_rule_count != actual_path_rule_count
                ):
                    raise InvalidLudusaviIndex("Ludusavi 索引条目计数不一致。")
        except InvalidLudusaviIndex:
            raise
        except (OSError, sqlite3.Error, UnicodeError, ValueError) as error:
            raise InvalidLudusaviIndex(f"无法读取 Ludusavi SQLite 索引：{path}") from error
        return cls(path, metadata)

    def load_names(self) -> tuple[IndexedName, ...]:
        try:
            with closing(_connect_read_only(self._path)) as connection:
                rows = connection.execute(
                    """
                    SELECT game_id, display_name, normalized_name, source, candidate_order
                    FROM names
                    ORDER BY game_id, candidate_order
                    """
                ).fetchall()
            result: list[IndexedName] = []
            for row in rows:
                source = _indexed_name_source(row[3])
                game_id = _positive_int(row[0], "名称游戏 ID")
                candidate_order = _non_negative_int(row[4], "名称顺序")
                display_name = _non_empty_string(row[1], "显示名称")
                normalized_name = _non_empty_string(row[2], "规范化名称")
                result.append(
                    IndexedName(
                        game_id=game_id,
                        display_name=display_name,
                        normalized_name=normalized_name,
                        source=source,
                        candidate_order=candidate_order,
                    )
                )
            return tuple(result)
        except InvalidLudusaviIndex:
            raise
        except (OSError, sqlite3.Error, UnicodeError, ValueError) as error:
            raise InvalidLudusaviIndex("无法读取 Ludusavi 索引名称目录。") from error

    def load_games(self, game_ids: Collection[int]) -> Mapping[int, ManifestGame]:
        requested = tuple(sorted(set(game_ids)))
        if not requested:
            return MappingProxyType({})
        if any(
            not isinstance(game_id, int)
            or isinstance(game_id, bool)
            or game_id <= 0
            for game_id in requested
        ):
            raise InvalidLudusaviIndex("Ludusavi 索引游戏 ID 无效。")
        placeholders = ", ".join("?" for _ in requested)
        try:
            with closing(_connect_read_only(self._path)) as connection:
                game_rows = connection.execute(
                    f"SELECT id, canonical_name FROM games WHERE id IN ({placeholders}) ",
                    requested,
                ).fetchall()
                name_rows = connection.execute(
                    "SELECT game_id, display_name FROM names "
                    f"WHERE game_id IN ({placeholders}) AND source = 'install_dir' "
                    "ORDER BY game_id, candidate_order",
                    requested,
                ).fetchall()
                location_rows = connection.execute(
                    "SELECT game_id, kind, path, tags_json, conditions_json "
                    f"FROM locations WHERE game_id IN ({placeholders}) "
                    "ORDER BY game_id, location_order",
                    requested,
                ).fetchall()
        except (OSError, sqlite3.Error) as error:
            raise InvalidLudusaviIndex("无法读取 Ludusavi 索引游戏规则。") from error

        canonical_names = {
            _positive_int(row[0], "游戏 ID"): _non_empty_string(row[1], "规范游戏名")
            for row in game_rows
        }
        if set(canonical_names) != set(requested):
            raise InvalidLudusaviIndex("Ludusavi 索引缺少请求的游戏条目。")
        install_dirs: dict[int, list[str]] = {game_id: [] for game_id in requested}
        for row in name_rows:
            game_id = _positive_int(row[0], "安装目录游戏 ID")
            install_dirs[game_id].append(_non_empty_string(row[1], "安装目录名"))

        files: dict[int, list[ManifestLocationRule]] = {
            game_id: [] for game_id in requested
        }
        registry: dict[int, list[ManifestLocationRule]] = {
            game_id: [] for game_id in requested
        }
        for row in location_rows:
            game_id = _positive_int(row[0], "位置游戏 ID")
            kind = _non_empty_string(row[1], "位置类型")
            rule = ManifestLocationRule(
                path=_non_empty_string(row[2], "位置路径"),
                tags=_decode_tags(row[3]),
                conditions=_decode_conditions(row[4]),
            )
            if kind == "file":
                files[game_id].append(rule)
            elif kind == "registry":
                registry[game_id].append(rule)
            else:
                raise InvalidLudusaviIndex(f"Ludusavi 索引位置类型无效：{kind}")

        games = {
            game_id: ManifestGame(
                canonical_name=canonical_names[game_id],
                files=tuple(files[game_id]),
                registry=tuple(registry[game_id]),
                install_dirs=tuple(install_dirs[game_id]),
                alias=None,
            )
            for game_id in requested
        }
        return MappingProxyType(games)

    def load_literal_path_rules(
        self,
        root_tokens: Collection[str],
    ) -> tuple[IndexedPathRule, ...]:
        requested = tuple(sorted({_normalize_root_token(value) for value in root_tokens}))
        if not requested:
            return ()
        placeholders = ", ".join("?" for _ in requested)
        try:
            with closing(_connect_read_only(self._path)) as connection:
                rows = connection.execute(
                    "SELECT p.game_id, g.canonical_name, p.kind, p.root_token, "
                    "p.relative_pattern, p.first_segment_key, p.specificity, "
                    "p.tags_json, p.conditions_json "
                    "FROM path_rules AS p JOIN games AS g ON g.id = p.game_id "
                    f"WHERE p.root_token IN ({placeholders}) "
                    "ORDER BY p.game_id, p.location_order",
                    requested,
                ).fetchall()
        except (OSError, sqlite3.Error) as error:
            raise InvalidLudusaviIndex("无法读取 Ludusavi 字面路径规则。") from error
        return tuple(
            rule
            for row in rows
            if _is_literal_pattern(str(row[4]))
            for rule in (_indexed_path_rule(row),)
        )

    def find_path_rules(
        self,
        root_token: str,
        relative_path: str,
        kind: IndexedPathRuleKind,
    ) -> tuple[IndexedPathRule, ...]:
        canonical_root = _normalize_root_token(root_token)
        if kind not in {"file", "registry"}:
            raise InvalidLudusaviIndex("Ludusavi 反向查询位置类型无效。")
        clean_relative = _normalize_relative_path(relative_path)
        first_segment = clean_relative.partition("\\")[0]
        first_segment_key = _segment_key(first_segment)
        try:
            with closing(_connect_read_only(self._path)) as connection:
                rows = connection.execute(
                    "SELECT p.game_id, g.canonical_name, p.kind, p.root_token, "
                    "p.relative_pattern, p.first_segment_key, p.specificity, "
                    "p.tags_json, p.conditions_json "
                    "FROM path_rules AS p JOIN games AS g ON g.id = p.game_id "
                    "WHERE p.root_token = ? AND p.kind = ? "
                    "AND (p.first_segment_key = ? OR p.first_segment_key = '') "
                    "ORDER BY p.specificity DESC, g.canonical_name COLLATE NOCASE, "
                    "p.game_id, p.location_order",
                    (canonical_root, kind, first_segment_key),
                ).fetchall()
        except (OSError, sqlite3.Error) as error:
            raise InvalidLudusaviIndex("无法查询 Ludusavi 反向路径规则。") from error
        return tuple(
            rule
            for row in rows
            if _windows_glob_match(str(row[4]), clean_relative)
            for rule in (_indexed_path_rule(row),)
        )


def _connect_read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA trusted_schema = OFF")
    return connection


def _validate_schema(connection: sqlite3.Connection) -> None:
    quick_check = connection.execute("PRAGMA quick_check").fetchall()
    if quick_check != [("ok",)]:
        raise InvalidLudusaviIndex("Ludusavi SQLite 索引完整性检查失败。")
    user_version = cast(int, connection.execute("PRAGMA user_version").fetchone()[0])
    if user_version != INDEX_SCHEMA_VERSION:
        raise InvalidLudusaviIndex("Ludusavi 索引格式版本不受支持。")
    for table, expected in _EXPECTED_COLUMNS.items():
        columns = tuple(row[1] for row in connection.execute(f"PRAGMA table_info({table})"))
        if columns != expected:
            raise InvalidLudusaviIndex(f"Ludusavi 索引表结构无效：{table}")


def _read_index_metadata(connection: sqlite3.Connection) -> LudusaviIndexMetadata:
    rows = connection.execute("SELECT key, value FROM index_metadata").fetchall()
    data = {row[0]: row[1] for row in rows}
    if set(data) != {
        "schema_version",
        "manifest_sha256",
        "game_count",
        "name_count",
        "path_rule_count",
    }:
        raise InvalidLudusaviIndex("Ludusavi 索引元数据字段无效。")
    try:
        schema_version = int(data["schema_version"])
        game_count = int(data["game_count"])
        name_count = int(data["name_count"])
        path_rule_count = int(data["path_rule_count"])
    except (TypeError, ValueError) as error:
        raise InvalidLudusaviIndex("Ludusavi 索引元数据数值无效。") from error
    manifest_sha256 = data["manifest_sha256"]
    if schema_version != INDEX_SCHEMA_VERSION:
        raise InvalidLudusaviIndex("Ludusavi 索引格式版本不受支持。")
    if not isinstance(manifest_sha256, str) or not _SHA256_PATTERN.fullmatch(
        manifest_sha256
    ):
        raise InvalidLudusaviIndex("Ludusavi 索引源摘要格式无效。")
    if game_count < 0 or name_count < 0 or path_rule_count < 0:
        raise InvalidLudusaviIndex("Ludusavi 索引条目计数无效。")
    return LudusaviIndexMetadata(
        schema_version=schema_version,
        manifest_sha256=manifest_sha256,
        game_count=game_count,
        name_count=name_count,
        path_rule_count=path_rule_count,
    )


_ROOT_TOKENS = {
    "<home>",
    "<winAppData>",
    "<winLocalAppData>",
    "<winLocalAppDataLow>",
    "<winDocuments>",
    "<winSavedGames>",
    "<winProgramData>",
    "<winPublic>",
    "<winDir>",
    "HKEY_CURRENT_USER",
    "HKEY_LOCAL_MACHINE",
}
_ROOT_TOKENS_BY_KEY = {value.casefold(): value for value in _ROOT_TOKENS}
_ROOT_TOKENS_BY_KEY.update(
    {
        "hkcu": "HKEY_CURRENT_USER",
        "hklm": "HKEY_LOCAL_MACHINE",
    }
)
_EMBEDDED_TOKEN = re.compile(r"<[^<>\\/]+>")


def _normalize_root_token(value: object) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise InvalidLudusaviIndex("Ludusavi 反向查询根令牌无效。")
    try:
        return _ROOT_TOKENS_BY_KEY[value.casefold()]
    except KeyError as error:
        raise InvalidLudusaviIndex("Ludusavi 反向查询根令牌不受支持。") from error


def _normalize_relative_path(value: object) -> str:
    if not isinstance(value, str) or "\x00" in value:
        raise InvalidLudusaviIndex("Ludusavi 反向查询相对路径无效。")
    clean = value.replace("/", "\\").strip("\\")
    if not clean or any(part in {"", ".", ".."} for part in clean.split("\\")):
        raise InvalidLudusaviIndex("Ludusavi 反向查询相对路径无效。")
    if re.match(r"^[A-Za-z]:", clean):
        raise InvalidLudusaviIndex("Ludusavi 反向查询只接受相对路径。")
    return clean


def _segment_key(value: str) -> str:
    return windows_path_key(value)


def _is_literal_pattern(value: str) -> bool:
    return not any(character in value for character in "*?[") and not _EMBEDDED_TOKEN.search(
        value
    )


def _windows_glob_match(pattern: str, relative_path: str) -> bool:
    pattern_parts = pattern.replace("/", "\\").strip("\\").split("\\")
    path_parts = relative_path.replace("/", "\\").strip("\\").split("\\")
    memo: dict[tuple[int, int], bool] = {}

    def matches(pattern_index: int, path_index: int) -> bool:
        key = (pattern_index, path_index)
        if key in memo:
            return memo[key]
        if pattern_index == len(pattern_parts):
            result = path_index == len(path_parts)
        elif pattern_parts[pattern_index] == "**":
            result = matches(pattern_index + 1, path_index) or (
                path_index < len(path_parts) and matches(pattern_index, path_index + 1)
            )
        elif path_index == len(path_parts):
            result = False
        else:
            segment_pattern = _EMBEDDED_TOKEN.sub("?*", pattern_parts[pattern_index])
            result = fnmatch.fnmatchcase(
                path_parts[path_index].casefold(),
                segment_pattern.casefold(),
            ) and matches(pattern_index + 1, path_index + 1)
        memo[key] = result
        return result

    return matches(0, 0)


def _indexed_path_rule(row: tuple[object, ...]) -> IndexedPathRule:
    kind_value = _non_empty_string(row[2], "反向规则位置类型")
    if kind_value not in {"file", "registry"}:
        raise InvalidLudusaviIndex("Ludusavi 反向规则位置类型无效。")
    return IndexedPathRule(
        game_id=_positive_int(row[0], "反向规则游戏 ID"),
        canonical_name=_non_empty_string(row[1], "反向规则游戏名"),
        kind=cast(IndexedPathRuleKind, kind_value),
        root_token=_normalize_root_token(row[3]),
        relative_pattern=_string(row[4], "反向规则相对路径"),
        first_segment_key=_string(row[5], "反向规则首段"),
        specificity=_non_negative_int(row[6], "反向规则特异度"),
        tags=_decode_tags(row[7]),
        conditions=_decode_conditions(row[8]),
    )


def _decode_tags(value: object) -> frozenset[str]:
    loaded = _decode_json(value, "标签")
    if not isinstance(loaded, list) or not all(isinstance(item, str) for item in loaded):
        raise InvalidLudusaviIndex("Ludusavi 索引标签必须是字符串数组。")
    return frozenset(loaded)


def _decode_conditions(value: object) -> tuple[ManifestCondition, ...]:
    loaded = _decode_json(value, "条件")
    if not isinstance(loaded, list):
        raise InvalidLudusaviIndex("Ludusavi 索引条件必须是数组。")
    conditions: list[ManifestCondition] = []
    for item in loaded:
        if not isinstance(item, dict) or set(item) != {"os", "store"}:
            raise InvalidLudusaviIndex("Ludusavi 索引条件字段无效。")
        data = cast(dict[str, Any], item)
        os_value = data["os"]
        store_value = data["store"]
        if os_value is not None and not isinstance(os_value, str):
            raise InvalidLudusaviIndex("Ludusavi 索引条件系统字段无效。")
        if store_value is not None and not isinstance(store_value, str):
            raise InvalidLudusaviIndex("Ludusavi 索引条件平台字段无效。")
        conditions.append(ManifestCondition(os=os_value, store=store_value))
    return tuple(conditions)


def _decode_json(value: object, label: str) -> Any:
    if not isinstance(value, str):
        raise InvalidLudusaviIndex(f"Ludusavi 索引{label}不是 JSON 文本。")
    try:
        return json.loads(value)
    except json.JSONDecodeError as error:
        raise InvalidLudusaviIndex(f"Ludusavi 索引{label}不是有效 JSON。") from error


def _indexed_name_source(value: object) -> IndexedNameSource:
    if value not in {"canonical", "install_dir", "alias"}:
        raise InvalidLudusaviIndex("Ludusavi 索引名称来源无效。")
    return cast(IndexedNameSource, value)


def _positive_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise InvalidLudusaviIndex(f"Ludusavi 索引{label}无效。")
    return value


def _non_negative_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise InvalidLudusaviIndex(f"Ludusavi 索引{label}无效。")
    return value


def _non_empty_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise InvalidLudusaviIndex(f"Ludusavi 索引{label}无效。")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or "\x00" in value:
        raise InvalidLudusaviIndex(f"Ludusavi 索引{label}无效。")
    return value
