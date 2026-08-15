"""Validated, read-only access to a derived Ludusavi SQLite index."""

from __future__ import annotations

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

INDEX_SCHEMA_VERSION = 1
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
}

type IndexedNameSource = Literal["canonical", "install_dir", "alias"]


class InvalidLudusaviIndex(ValueError):
    """The index is corrupt, stale, or outside the supported schema."""


@dataclass(frozen=True, slots=True)
class LudusaviIndexMetadata:
    schema_version: int
    manifest_sha256: str
    game_count: int
    name_count: int


@dataclass(frozen=True, slots=True)
class IndexedName:
    game_id: int
    display_name: str
    normalized_name: str
    source: IndexedNameSource
    candidate_order: int


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
                if (
                    metadata.game_count != actual_game_count
                    or metadata.name_count != actual_name_count
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
    if set(data) != {"schema_version", "manifest_sha256", "game_count", "name_count"}:
        raise InvalidLudusaviIndex("Ludusavi 索引元数据字段无效。")
    try:
        schema_version = int(data["schema_version"])
        game_count = int(data["game_count"])
        name_count = int(data["name_count"])
    except (TypeError, ValueError) as error:
        raise InvalidLudusaviIndex("Ludusavi 索引元数据数值无效。") from error
    manifest_sha256 = data["manifest_sha256"]
    if schema_version != INDEX_SCHEMA_VERSION:
        raise InvalidLudusaviIndex("Ludusavi 索引格式版本不受支持。")
    if not isinstance(manifest_sha256, str) or not _SHA256_PATTERN.fullmatch(
        manifest_sha256
    ):
        raise InvalidLudusaviIndex("Ludusavi 索引源摘要格式无效。")
    if game_count < 0 or name_count < 0:
        raise InvalidLudusaviIndex("Ludusavi 索引条目计数无效。")
    return LudusaviIndexMetadata(
        schema_version=schema_version,
        manifest_sha256=manifest_sha256,
        game_count=game_count,
        name_count=name_count,
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
