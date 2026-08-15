"""Lifecycle, verification, and opening rules for save locations."""

from __future__ import annotations

import glob
import os
import sqlite3
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from itertools import islice
from pathlib import Path
from typing import Protocol, cast

from gameshelf.db.writer import DbWriter
from gameshelf.library.service import (
    GameNotFoundError,
    InvalidGameConfiguration,
    LibraryService,
)
from gameshelf.saves.location_persistence import (
    PreparedSaveLocation,
    upsert_confirmed_location,
)
from gameshelf.saves.models import (
    SaveLocation,
    SaveLocationKind,
    SaveLocationSource,
    SaveLocationSuggestion,
)
from gameshelf.saves.repository import SaveLocationRepository, save_location_from_row
from gameshelf.saves.templates import InvalidPathTemplate, PathTemplateResolver
from gameshelf.scanning.path_keys import windows_path_key


class SaveLocationShell(Protocol):
    def open_directory(self, path: Path) -> None: ...

    def reveal_file(self, path: Path) -> None: ...


class RegistryAccess(Protocol):
    def key_exists(self, key: str) -> bool: ...

    def open_key(self, key: str) -> None: ...


class InvalidSaveLocation(ValueError):
    """A save location is malformed, unsafe, unavailable, or the wrong kind."""


class SaveLocationNotFoundError(LookupError):
    """A command referenced a save location that is not present."""


class SaveLocationOpenError(OSError):
    """A save location cannot currently be opened."""


_KINDS = {"directory", "file", "glob", "registry"}
_SOURCES = {"manual", "dynamic", "ludusavi", "engine", "legacy_scan"}
_GLOB_MAGIC = "*?["
_REGISTRY_ROOTS = {
    "HKCU": "HKEY_CURRENT_USER",
    "HKEY_CURRENT_USER": "HKEY_CURRENT_USER",
    "HKLM": "HKEY_LOCAL_MACHINE",
    "HKEY_LOCAL_MACHINE": "HKEY_LOCAL_MACHINE",
}


class SaveLocationService:
    def __init__(
        self,
        repository: SaveLocationRepository,
        writer: DbWriter,
        resolver: PathTemplateResolver,
        library: LibraryService,
        shell: SaveLocationShell,
        registry: RegistryAccess,
    ) -> None:
        self._repository = repository
        self._writer = writer
        self._resolver = resolver
        self._library = library
        self._shell = shell
        self._registry = registry

    def add_manual(
        self,
        game_id: str,
        kind: SaveLocationKind | str,
        selected_path: str | Path,
    ) -> SaveLocation:
        clean_kind = _validate_kind(kind)
        game_dir = self._game_directory(game_id)
        raw_path = os.fspath(selected_path).strip()
        if not raw_path:
            raise InvalidSaveLocation("存档位置不能为空。")

        if clean_kind == "registry":
            display_path = _normalize_registry_key(raw_path)
            if not self._registry.key_exists(display_path):
                raise InvalidSaveLocation("手动添加的注册表位置必须存在。")
            path_template = display_path
            path_key = _registry_path_key(display_path)
        else:
            path = Path(raw_path)
            self._validate_manual_filesystem_path(clean_kind, path)
            try:
                path_template = self._resolver.collapse(path, game_dir)
                display_path = str(self._resolver.expand(path_template, game_dir))
            except InvalidPathTemplate as error:
                raise InvalidSaveLocation(str(error)) from error
            path_key = windows_path_key(display_path)

        return self._persist_confirmed(
            game_id=game_id,
            kind=clean_kind,
            path_template=path_template,
            display_path=display_path,
            path_key=path_key,
            source="manual",
            confidence=1.0,
            evidence=("用户手动添加",),
        )

    def accept_suggestion(
        self,
        game_id: str,
        suggestion: SaveLocationSuggestion,
    ) -> SaveLocation:
        return self._persist_prepared(self.prepare_suggestion(game_id, suggestion))

    def prepare_suggestion(
        self,
        game_id: str,
        suggestion: SaveLocationSuggestion,
    ) -> PreparedSaveLocation:
        kind = _validate_kind(suggestion.kind)
        source = _validate_source(suggestion.source)
        confidence = _validate_confidence(suggestion.confidence)
        game_dir = self._game_directory(game_id)
        if kind == "registry":
            path_template = _normalize_registry_key(suggestion.path_template)
            display_path = path_template
            path_key = _registry_path_key(path_template)
        else:
            try:
                expanded = self._resolver.expand(suggestion.path_template, game_dir)
            except InvalidPathTemplate as error:
                raise InvalidSaveLocation(str(error)) from error
            path_template = suggestion.path_template
            display_path = str(expanded)
            path_key = windows_path_key(expanded)

        return PreparedSaveLocation(
            game_id=game_id,
            kind=kind,
            path_template=path_template,
            display_path=display_path,
            path_key=path_key,
            source=source,
            confidence=confidence,
            evidence=_validate_evidence(
                (
                    *suggestion.evidence,
                    *(
                    f"[{item.source}] {item.detail}"
                    for item in suggestion.source_evidence
                    ),
                )
            ),
        )

    def list_for_game(self, game_id: str) -> tuple[SaveLocation, ...]:
        self._require_game(game_id)
        game_dir = self._game_directory(game_id)
        return tuple(
            self._with_existence(location, game_dir)
            for location in self._repository.list_for_game(game_id)
        )

    def verify_game(self, game_id: str) -> tuple[SaveLocation, ...]:
        self._require_game(game_id)
        verified_at = _utc_now()

        def operation(connection: sqlite3.Connection) -> None:
            connection.execute(
                "UPDATE save_locations SET last_verified_at = ? WHERE game_id = ?",
                (verified_at, game_id),
            )

        self._writer.submit(operation).result()
        return self.list_for_game(game_id)

    def disable(self, location_id: str) -> SaveLocation:
        def operation(connection: sqlite3.Connection) -> SaveLocation:
            changed = connection.execute(
                "UPDATE save_locations SET enabled = 0 WHERE id = ?", (location_id,)
            ).rowcount
            if changed == 0:
                raise SaveLocationNotFoundError(location_id)
            row = connection.execute(
                "SELECT * FROM save_locations WHERE id = ?", (location_id,)
            ).fetchone()
            assert row is not None
            return save_location_from_row(row)

        location = self._writer.submit(operation).result()
        return self._with_existence(location, self._game_directory(location.game_id))

    def remove(self, location_id: str) -> None:
        def operation(connection: sqlite3.Connection) -> None:
            changed = connection.execute(
                "DELETE FROM save_locations WHERE id = ?", (location_id,)
            ).rowcount
            if changed == 0:
                raise SaveLocationNotFoundError(location_id)

        self._writer.submit(operation).result()

    def open_location(self, location_id: str) -> None:
        location = self._repository.get(location_id)
        if location is None:
            raise SaveLocationNotFoundError(location_id)
        if location.kind == "registry":
            if not location.confirmed:
                raise SaveLocationOpenError("未确认的注册表位置不能打开。")
            self._registry.open_key(location.path_template)
            return

        path = self._expanded_path(location)
        if location.kind == "directory":
            if not path.is_dir():
                raise SaveLocationOpenError(f"存档目录不存在：{path}")
            self._shell.open_directory(path)
        elif location.kind == "file":
            if not path.is_file():
                raise SaveLocationOpenError(f"存档文件不存在：{path}")
            self._shell.reveal_file(path)
        else:
            parent = _nearest_existing_glob_parent(path)
            if parent is None:
                raise SaveLocationOpenError(f"找不到通配符路径的现有父目录：{path}")
            self._shell.open_directory(parent)

    def _persist_confirmed(
        self,
        *,
        game_id: str,
        kind: SaveLocationKind,
        path_template: str,
        display_path: str,
        path_key: str,
        source: SaveLocationSource,
        confidence: float,
        evidence: Sequence[str],
    ) -> SaveLocation:
        self._require_game(game_id)
        return self._persist_prepared(
            PreparedSaveLocation(
                game_id=game_id,
                kind=kind,
                path_template=path_template,
                display_path=display_path,
                path_key=path_key,
                source=source,
                confidence=confidence,
                evidence=_validate_evidence(evidence),
            )
        )

    def _persist_prepared(self, prepared: PreparedSaveLocation) -> SaveLocation:
        self._require_game(prepared.game_id)
        location = self._writer.submit(
            lambda connection: upsert_confirmed_location(connection, prepared)
        ).result()
        return self._with_existence(
            location, self._game_directory(prepared.game_id)
        )

    def _with_existence(
        self,
        location: SaveLocation,
        game_dir: Path | None,
    ) -> SaveLocation:
        if location.kind == "registry":
            return replace(
                location,
                exists=self._registry.key_exists(location.path_template),
            )

        path = self._expanded_path(location, game_dir)
        if location.kind == "glob":
            matches = sum(1 for _ in islice(glob.iglob(os.fspath(path)), 1001))
            return replace(
                location,
                exists=matches > 0,
                match_count=min(matches, 1000),
                matches_truncated=matches > 1000,
            )
        exists = path.is_dir() if location.kind == "directory" else path.is_file()
        return replace(location, exists=exists)

    def _expanded_path(
        self,
        location: SaveLocation,
        game_dir: Path | None = None,
    ) -> Path:
        if game_dir is None:
            game_dir = self._game_directory(location.game_id)
        try:
            return self._resolver.expand(location.path_template, game_dir)
        except InvalidPathTemplate as error:
            raise InvalidSaveLocation(str(error)) from error

    def _validate_manual_filesystem_path(
        self,
        kind: SaveLocationKind,
        path: Path,
    ) -> None:
        if kind == "directory" and not path.is_dir():
            raise InvalidSaveLocation("手动添加的存档目录必须存在。")
        if kind == "file" and not path.is_file():
            raise InvalidSaveLocation("手动添加的存档文件必须存在。")
        if kind == "glob":
            if not any(character in os.fspath(path) for character in _GLOB_MAGIC):
                raise InvalidSaveLocation("通配符位置必须包含 *, ? 或 [。")
            if _nearest_existing_glob_parent(path) is None:
                raise InvalidSaveLocation("通配符位置必须有一个现有父目录。")

    def _game_directory(self, game_id: str) -> Path | None:
        self._require_game(game_id)
        try:
            return self._library.install_directory(game_id)
        except InvalidGameConfiguration:
            return None

    def _require_game(self, game_id: str) -> None:
        if self._library.get_game(game_id) is None:
            raise GameNotFoundError(game_id)


def _validate_kind(value: str) -> SaveLocationKind:
    if value not in _KINDS:
        raise InvalidSaveLocation(f"未知的存档位置类型：{value}")
    return cast(SaveLocationKind, value)


def _validate_source(value: str) -> SaveLocationSource:
    if value not in _SOURCES:
        raise InvalidSaveLocation(f"未知的存档位置来源：{value}")
    return cast(SaveLocationSource, value)


def _validate_confidence(value: float) -> float:
    if not 0 <= value <= 1:
        raise InvalidSaveLocation("存档位置置信度必须在 0 到 1 之间。")
    return value


def _validate_evidence(values: Sequence[str]) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        clean = value.strip()
        if not clean or "\x00" in clean:
            raise InvalidSaveLocation("存档位置证据不能为空或包含 NUL。")
        result.append(clean)
    return tuple(result)


def _normalize_registry_key(value: str) -> str:
    clean = value.strip().replace("/", "\\").rstrip("\\")
    if not clean or "\x00" in clean or ".." in clean.split("\\"):
        raise InvalidSaveLocation("注册表路径无效。")
    root, separator, suffix = clean.partition("\\")
    canonical_root = _REGISTRY_ROOTS.get(root.upper())
    if canonical_root is None or not separator or not suffix:
        raise InvalidSaveLocation("注册表路径必须包含受支持的根键和子键。")
    return f"{canonical_root}\\{suffix}"


def _registry_path_key(value: str) -> str:
    return value.casefold()


def _nearest_existing_glob_parent(path: Path) -> Path | None:
    parts = path.parts
    if not parts:
        return None
    parent = Path(parts[0])
    for part in parts[1:]:
        if any(character in part for character in _GLOB_MAGIC):
            break
        parent /= part
    while parent != parent.parent and not parent.is_dir():
        parent = parent.parent
    return parent if parent.is_dir() else None


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
