"""Build the derived Ludusavi SQLite index from a validated manifest."""

from __future__ import annotations

import json
import ntpath
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from gameshelf.saves.ludusavi_index import (
    INDEX_SCHEMA_VERSION,
    LudusaviIndex,
    LudusaviIndexMetadata,
)
from gameshelf.saves.ludusavi_matcher import normalize_ludusavi_name
from gameshelf.saves.ludusavi_models import LudusaviManifest, ManifestLocationRule
from gameshelf.scanning.path_keys import windows_path_key

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SCHEMA = """
CREATE TABLE index_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE games (
    id INTEGER PRIMARY KEY,
    canonical_name TEXT NOT NULL UNIQUE
);
CREATE TABLE names (
    game_id INTEGER NOT NULL REFERENCES games(id),
    candidate_order INTEGER NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('canonical', 'install_dir', 'alias')),
    display_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    PRIMARY KEY (game_id, candidate_order)
);
CREATE INDEX names_normalized_name_idx ON names(normalized_name);
CREATE TABLE locations (
    game_id INTEGER NOT NULL REFERENCES games(id),
    location_order INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('file', 'registry')),
    path TEXT NOT NULL,
    tags_json TEXT NOT NULL,
    conditions_json TEXT NOT NULL,
    PRIMARY KEY (game_id, location_order)
);
CREATE INDEX locations_game_id_idx ON locations(game_id);
CREATE TABLE path_rules (
    game_id INTEGER NOT NULL REFERENCES games(id),
    location_order INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('file', 'registry')),
    root_token TEXT NOT NULL,
    relative_pattern TEXT NOT NULL,
    first_segment_key TEXT NOT NULL,
    specificity INTEGER NOT NULL CHECK (specificity >= 0),
    tags_json TEXT NOT NULL,
    conditions_json TEXT NOT NULL,
    PRIMARY KEY (game_id, location_order)
);
CREATE INDEX path_rules_lookup_idx
ON path_rules(root_token, first_segment_key, kind);
"""

_FILE_RULE_PATTERN = re.compile(r"^(<[^<>\\/]+>)(?:[\\/](.*))?$")
_EMBEDDED_TOKEN = re.compile(r"<[^<>\\/]+>")
_SUPPORTED_FILE_ROOTS = {
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
_REGISTRY_ROOTS = {
    "HKCU": "HKEY_CURRENT_USER",
    "HKEY_CURRENT_USER": "HKEY_CURRENT_USER",
    "HKLM": "HKEY_LOCAL_MACHINE",
    "HKEY_LOCAL_MACHINE": "HKEY_LOCAL_MACHINE",
}


def build_ludusavi_index(
    path: Path,
    manifest: LudusaviManifest,
    *,
    manifest_sha256: str,
) -> LudusaviIndexMetadata:
    if not _SHA256_PATTERN.fullmatch(manifest_sha256):
        raise ValueError("Ludusavi 源清单摘要格式无效。")
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    canonical_ids = {
        name: game_id
        for game_id, (name, game) in enumerate(
            (
                (name, game)
                for name, game in manifest.games.items()
                if game.alias is None
            ),
            start=1,
        )
    }
    aliases = _aliases_by_canonical(manifest)
    name_count = 0
    path_rule_count = 0
    try:
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = DELETE")
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute(f"PRAGMA user_version = {INDEX_SCHEMA_VERSION}")
            connection.executescript(_SCHEMA)
            for canonical_name, game_id in canonical_ids.items():
                game = manifest.games[canonical_name]
                connection.execute(
                    "INSERT INTO games (id, canonical_name) VALUES (?, ?)",
                    (game_id, canonical_name),
                )
                candidates = (
                    ("canonical", canonical_name),
                    *(("install_dir", value) for value in game.install_dirs),
                    *(("alias", value) for value in aliases.get(canonical_name, ())),
                )
                candidate_order = 0
                for source, display_name in candidates:
                    normalized_name = normalize_ludusavi_name(display_name)
                    if not normalized_name:
                        continue
                    connection.execute(
                        """
                        INSERT INTO names (
                            game_id,
                            candidate_order,
                            source,
                            display_name,
                            normalized_name
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            game_id,
                            candidate_order,
                            source,
                            display_name,
                            normalized_name,
                        ),
                    )
                    candidate_order += 1
                    name_count += 1

                location_order = 0
                for kind, rules in (("file", game.files), ("registry", game.registry)):
                    for rule in rules:
                        _insert_location(
                            connection,
                            game_id=game_id,
                            location_order=location_order,
                            kind=kind,
                            rule=rule,
                        )
                        if _insert_path_rule(
                            connection,
                            game_id=game_id,
                            location_order=location_order,
                            kind=kind,
                            rule=rule,
                        ):
                            path_rule_count += 1
                        location_order += 1

            metadata = LudusaviIndexMetadata(
                schema_version=INDEX_SCHEMA_VERSION,
                manifest_sha256=manifest_sha256,
                game_count=len(canonical_ids),
                name_count=name_count,
                path_rule_count=path_rule_count,
            )
            connection.executemany(
                "INSERT INTO index_metadata (key, value) VALUES (?, ?)",
                (
                    ("schema_version", str(metadata.schema_version)),
                    ("manifest_sha256", metadata.manifest_sha256),
                    ("game_count", str(metadata.game_count)),
                    ("name_count", str(metadata.name_count)),
                    ("path_rule_count", str(metadata.path_rule_count)),
                ),
            )
            connection.commit()
        LudusaviIndex.open(path, manifest_sha256=manifest_sha256)
        return metadata
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _aliases_by_canonical(manifest: LudusaviManifest) -> dict[str, tuple[str, ...]]:
    aliases: dict[str, list[str]] = {}
    for alias_name, game in manifest.games.items():
        if game.alias is None:
            continue
        current = alias_name
        for _ in range(8):
            target = manifest.games[current].alias
            if target is None:
                aliases.setdefault(current, []).append(alias_name)
                break
            current = target
    return {key: tuple(values) for key, values in aliases.items()}


def _insert_location(
    connection: sqlite3.Connection,
    *,
    game_id: int,
    location_order: int,
    kind: str,
    rule: ManifestLocationRule,
) -> None:
    tags_json = json.dumps(
        sorted(rule.tags),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    conditions_json = json.dumps(
        [
            {"os": condition.os, "store": condition.store}
            for condition in rule.conditions
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    connection.execute(
        """
        INSERT INTO locations (
            game_id,
            location_order,
            kind,
            path,
            tags_json,
            conditions_json
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            game_id,
            location_order,
            kind,
            rule.path,
            tags_json,
            conditions_json,
        ),
    )


def _insert_path_rule(
    connection: sqlite3.Connection,
    *,
    game_id: int,
    location_order: int,
    kind: str,
    rule: ManifestLocationRule,
) -> bool:
    parts = _path_rule_parts(kind, rule.path)
    if parts is None:
        return False
    root_token, relative_pattern = parts
    normalized_pattern = relative_pattern.replace("/", "\\").strip("\\")
    first_segment = normalized_pattern.partition("\\")[0]
    first_segment_key = (
        ""
        if _segment_has_glob(first_segment)
        else windows_path_key(first_segment)
    )
    specificity = len(
        re.sub(r"<[^<>]+>|[*?\[\]]", "", normalized_pattern)
    )
    tags_json = json.dumps(
        sorted(rule.tags),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    conditions_json = json.dumps(
        [
            {"os": condition.os, "store": condition.store}
            for condition in rule.conditions
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    connection.execute(
        """
        INSERT INTO path_rules (
            game_id,
            location_order,
            kind,
            root_token,
            relative_pattern,
            first_segment_key,
            specificity,
            tags_json,
            conditions_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            game_id,
            location_order,
            kind,
            root_token,
            normalized_pattern,
            first_segment_key,
            specificity,
            tags_json,
            conditions_json,
        ),
    )
    return True


def _path_rule_parts(kind: str, path: str) -> tuple[str, str] | None:
    if kind == "file":
        match = _FILE_RULE_PATTERN.fullmatch(path)
        if match is None:
            return None
        root_token, relative_pattern = match.groups()
        if root_token not in _SUPPORTED_FILE_ROOTS:
            return None
        return root_token, relative_pattern or ""
    if kind != "registry":
        return None
    clean = path.replace("/", "\\").strip("\\")
    root, separator, relative_pattern = clean.partition("\\")
    canonical_root = _REGISTRY_ROOTS.get(root.upper())
    if canonical_root is None or not separator or not relative_pattern:
        return None
    return canonical_root, ntpath.normpath(relative_pattern)


def _segment_has_glob(value: str) -> bool:
    return any(character in value for character in "*?[") or bool(
        _EMBEDDED_TOKEN.search(value)
    )
