"""Defensive parser for the Windows-relevant Ludusavi manifest subset."""

from __future__ import annotations

import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, TextIO

import yaml

from gamesave_scout.saves.ludusavi_models import (
    LudusaviManifest,
    ManifestCondition,
    ManifestGame,
    ManifestLocationRule,
)

MAX_MANIFEST_GAMES = 200_000
MAX_ALIAS_HOPS = 8
_PATH_TOKEN = re.compile(r"^<([A-Za-z][A-Za-z0-9]*)>(?:[\\/]|$)")
_RECOGNIZED_PATH_TOKENS = {
    "base",
    "game",
    "root",
    "home",
    "storeGameId",
    "storeUserId",
    "osUserName",
    "winAppData",
    "winLocalAppData",
    "winLocalAppDataLow",
    "winDocuments",
    "winSavedGames",
    "winPublic",
    "winProgramData",
    "winDir",
    "xdgData",
    "xdgConfig",
}
_LEGACY_NON_WINDOWS_PREFIXES = (
    "$HOME/",
    "$USER/",
    "$XDG_CONFIG_HOME/",
    "$XDG_DATA_HOME/",
    "~/",
)


class InvalidLudusaviManifest(ValueError):
    """The manifest is malformed or outside GameSave Scout's safety limits."""


_SAFE_LOADER: type[yaml.SafeLoader] = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def parse_manifest(
    stream: TextIO,
    *,
    skip_invalid_paths: bool = False,
) -> LudusaviManifest:
    try:
        loaded: Any = yaml.load(stream, Loader=_SAFE_LOADER)
    except yaml.YAMLError as error:
        raise InvalidLudusaviManifest("Ludusavi 清单不是有效的 YAML。") from error
    if not isinstance(loaded, dict):
        raise InvalidLudusaviManifest("Ludusavi 清单顶层必须是游戏映射。")
    if len(loaded) > MAX_MANIFEST_GAMES:
        raise InvalidLudusaviManifest(
            f"Ludusavi 清单游戏条目不能超过 {MAX_MANIFEST_GAMES} 个。"
        )

    games: dict[str, ManifestGame] = {}
    for raw_name, raw_game in loaded.items():
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise InvalidLudusaviManifest("游戏名称必须是非空字符串。")
        name = raw_name.strip()
        if not isinstance(raw_game, dict):
            raise InvalidLudusaviManifest(f"游戏条目必须是映射：{name}")
        game_data = raw_game
        files = _parse_locations(
            game_data.get("files"),
            name,
            registry=False,
            skip_invalid_paths=skip_invalid_paths,
        )
        registry = _parse_locations(
            game_data.get("registry"),
            name,
            registry=True,
            skip_invalid_paths=skip_invalid_paths,
        )
        install_dirs = _parse_install_dirs(game_data.get("installDir"), name)
        alias_value = game_data.get("alias")
        if alias_value is not None and (
            not isinstance(alias_value, str) or not alias_value.strip()
        ):
            raise InvalidLudusaviManifest(f"别名目标必须是非空字符串：{name}")
        games[name] = ManifestGame(
            canonical_name=name,
            files=files,
            registry=registry,
            install_dirs=install_dirs,
            alias=alias_value.strip() if isinstance(alias_value, str) else None,
        )

    _validate_aliases(games)
    return LudusaviManifest(MappingProxyType(games))


def _parse_locations(
    value: Any,
    game_name: str,
    *,
    registry: bool,
    skip_invalid_paths: bool = False,
) -> tuple[ManifestLocationRule, ...]:
    if value is None:
        return ()
    if not isinstance(value, dict):
        section = "registry" if registry else "files"
        raise InvalidLudusaviManifest(f"{game_name} 的 {section} 必须是映射。")

    entries: list[ManifestLocationRule] = []
    for raw_path, raw_metadata in value.items():
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise InvalidLudusaviManifest(f"{game_name} 的路径必须是非空字符串。")
        path = raw_path.strip()
        if not registry:
            if path.startswith(_LEGACY_NON_WINDOWS_PREFIXES):
                continue
            token = _PATH_TOKEN.match(path)
            if token is None or token.group(1) not in _RECOGNIZED_PATH_TOKENS:
                if skip_invalid_paths:
                    continue
                raise InvalidLudusaviManifest(f"文件路径必须以已知占位符开头：{path}")
        elif not _valid_registry_root(path):
            if skip_invalid_paths:
                continue
            raise InvalidLudusaviManifest(f"注册表路径根键不受支持：{path}")

        if raw_metadata is None:
            metadata: Mapping[Any, Any] = {}
        elif isinstance(raw_metadata, dict):
            metadata = raw_metadata
        else:
            raise InvalidLudusaviManifest(f"路径元数据必须是映射：{path}")
        tags = _parse_tags(metadata.get("tags"), path)
        conditions = _parse_conditions(metadata.get("when"), path)
        windows_conditions = tuple(
            condition
            for condition in conditions
            if condition.os is None or condition.os.casefold() == "windows"
        )
        if conditions and not windows_conditions:
            continue
        entries.append(
            ManifestLocationRule(
                path=path,
                tags=tags,
                conditions=windows_conditions,
            )
        )
    return tuple(entries)


def _parse_tags(value: Any, path: str) -> frozenset[str]:
    if value is None:
        return frozenset()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise InvalidLudusaviManifest(f"tags 必须是字符串数组：{path}")
    return frozenset(item.strip().casefold() for item in value if item.strip())


def _parse_conditions(value: Any, path: str) -> tuple[ManifestCondition, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise InvalidLudusaviManifest(f"when 必须是条件数组：{path}")
    conditions: list[ManifestCondition] = []
    for raw_condition in value:
        if not isinstance(raw_condition, dict):
            raise InvalidLudusaviManifest(f"when 条件必须是映射：{path}")
        condition = raw_condition
        os_value = condition.get("os")
        store_value = condition.get("store")
        if os_value is not None and not isinstance(os_value, str):
            raise InvalidLudusaviManifest(f"when.os 必须是字符串：{path}")
        if store_value is not None and not isinstance(store_value, str):
            raise InvalidLudusaviManifest(f"when.store 必须是字符串：{path}")
        conditions.append(
            ManifestCondition(
                os=os_value.strip() if isinstance(os_value, str) else None,
                store=store_value.strip() if isinstance(store_value, str) else None,
            )
        )
    return tuple(conditions)


def _parse_install_dirs(value: Any, game_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, dict):
        raise InvalidLudusaviManifest(f"{game_name} 的 installDir 必须是映射。")
    result: list[str] = []
    for raw_name, metadata in value.items():
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise InvalidLudusaviManifest(f"{game_name} 的安装目录名称无效。")
        if metadata is not None and not isinstance(metadata, dict):
            raise InvalidLudusaviManifest(f"安装目录元数据必须是映射：{raw_name}")
        result.append(raw_name.strip())
    return tuple(result)


def _validate_aliases(games: Mapping[str, ManifestGame]) -> None:
    for start in games:
        current = start
        visited: set[str] = set()
        hops = 0
        while games[current].alias is not None:
            if current in visited:
                raise InvalidLudusaviManifest(f"检测到递归别名：{start}")
            visited.add(current)
            if hops >= MAX_ALIAS_HOPS:
                raise InvalidLudusaviManifest(
                    f"别名链超过 {MAX_ALIAS_HOPS} 跳：{start}"
                )
            target = games[current].alias
            assert target is not None
            if target not in games:
                raise InvalidLudusaviManifest(f"别名目标不存在：{current} -> {target}")
            current = target
            hops += 1


def _valid_registry_root(path: str) -> bool:
    root = path.replace("/", "\\").partition("\\")[0].upper()
    return root in {
        "HKEY_CURRENT_USER",
        "HKEY_LOCAL_MACHINE",
        "HKEY_CLASSES_ROOT",
        "HKEY_USERS",
    }
