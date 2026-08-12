"""Transactional commands for scan roots and game-library records."""

from __future__ import annotations

import ntpath
import posixpath
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

from gameshelf.db.writer import DbWriter
from gameshelf.library.models import Game, ScanMode, ScanRoot
from gameshelf.library.repository import (
    LibraryRepository,
    game_from_row,
    scan_root_from_row,
)
from gameshelf.scanning.path_keys import windows_path_key


class InvalidRootConfiguration(ValueError):
    """Raised when a root mode, depth, or exclusion is unsafe."""


class RootNotFoundError(LookupError):
    """Raised when a scan-root command names an unknown record."""


class LibraryService:
    def __init__(self, repository: LibraryRepository, writer: DbWriter) -> None:
        self._repository = repository
        self._writer = writer

    def add_root(
        self,
        display_path: str,
        scan_mode: ScanMode,
        max_depth: int,
        exclusions: Sequence[str],
    ) -> ScanRoot:
        clean_path = _validate_display_path(display_path)
        mode, depth = _validate_mode_depth(scan_mode, max_depth)
        clean_exclusions = _normalize_exclusions(exclusions)
        path_key = windows_path_key(clean_path)

        def operation(connection: sqlite3.Connection) -> ScanRoot:
            existing = connection.execute(
                "SELECT * FROM scan_roots WHERE path_key = ?", (path_key,)
            ).fetchone()
            if existing is not None:
                return scan_root_from_row(existing)
            root_id = str(uuid4())
            created_at = _utc_now()
            connection.execute(
                """
                INSERT INTO scan_roots(
                    id, display_path, path_key, enabled, scan_mode, max_depth,
                    exclusions_json, created_at
                ) VALUES (?, ?, ?, 1, ?, ?, json(?), ?)
                """,
                (
                    root_id,
                    clean_path,
                    path_key,
                    mode,
                    depth,
                    _json_array(clean_exclusions),
                    created_at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM scan_roots WHERE id = ?", (root_id,)
            ).fetchone()
            assert row is not None
            return scan_root_from_row(row)

        return self._writer.submit(operation).result()

    def update_root(
        self,
        root_id: str,
        *,
        enabled: bool,
        scan_mode: ScanMode,
        max_depth: int,
        exclusions: Sequence[str],
    ) -> ScanRoot:
        mode, depth = _validate_mode_depth(scan_mode, max_depth)
        clean_exclusions = _normalize_exclusions(exclusions)

        def operation(connection: sqlite3.Connection) -> ScanRoot:
            changed = connection.execute(
                """
                UPDATE scan_roots
                SET enabled = ?, scan_mode = ?, max_depth = ?, exclusions_json = json(?)
                WHERE id = ?
                """,
                (bool(enabled), mode, depth, _json_array(clean_exclusions), root_id),
            ).rowcount
            if changed == 0:
                raise RootNotFoundError(root_id)
            row = connection.execute(
                "SELECT * FROM scan_roots WHERE id = ?", (root_id,)
            ).fetchone()
            assert row is not None
            return scan_root_from_row(row)

        return self._writer.submit(operation).result()

    def remove_root(self, root_id: str) -> None:
        def operation(connection: sqlite3.Connection) -> None:
            exists = connection.execute(
                "SELECT 1 FROM scan_roots WHERE id = ?", (root_id,)
            ).fetchone()
            if exists is None:
                raise RootNotFoundError(root_id)
            now = _utc_now()
            connection.execute(
                """
                UPDATE games
                SET scan_root_id = NULL, status = 'missing', missing_since = ?, updated_at = ?
                WHERE scan_root_id = ?
                """,
                (now, now, root_id),
            )
            connection.execute("DELETE FROM scan_roots WHERE id = ?", (root_id,))

        self._writer.submit(operation).result()

    def remap_root(self, root_id: str, display_path: str) -> ScanRoot:
        clean_path = _validate_display_path(display_path)
        path_key = windows_path_key(clean_path)

        def operation(connection: sqlite3.Connection) -> ScanRoot:
            try:
                changed = connection.execute(
                    "UPDATE scan_roots SET display_path = ?, path_key = ? WHERE id = ?",
                    (clean_path, path_key, root_id),
                ).rowcount
            except sqlite3.IntegrityError as error:
                raise InvalidRootConfiguration(
                    "The remapped root is already configured."
                ) from error
            if changed == 0:
                raise RootNotFoundError(root_id)
            games = connection.execute(
                "SELECT id, relative_dir FROM games WHERE scan_root_id = ?", (root_id,)
            ).fetchall()
            for game in games:
                relative_dir = game["relative_dir"]
                install_key = (
                    windows_path_key(ntpath.join(clean_path, relative_dir))
                    if relative_dir is not None
                    else None
                )
                connection.execute(
                    "UPDATE games SET install_path_key = ?, updated_at = ? WHERE id = ?",
                    (install_key, _utc_now(), game["id"]),
                )
            row = connection.execute(
                "SELECT * FROM scan_roots WHERE id = ?", (root_id,)
            ).fetchone()
            assert row is not None
            return scan_root_from_row(row)

        return self._writer.submit(operation).result()

    def list_roots(self) -> tuple[ScanRoot, ...]:
        return self._repository.list_roots()

    def list_games(self) -> tuple[Game, ...]:
        return self._repository.list_games()

    def get_game(self, game_id: str) -> Game | None:
        return self._repository.get_game(game_id)

    def create_game_for_test(
        self, root_id: str, relative_dir: str, title: str
    ) -> Game:
        """Seed a minimal discovered record until the scan reconciler owns creation."""
        relative = _normalize_relative_directory(relative_dir)

        def operation(connection: sqlite3.Connection) -> Game:
            root = connection.execute(
                "SELECT * FROM scan_roots WHERE id = ?", (root_id,)
            ).fetchone()
            if root is None:
                raise RootNotFoundError(root_id)
            game_id = str(uuid4())
            now = _utc_now()
            install_key = windows_path_key(ntpath.join(root["display_path"], relative))
            connection.execute(
                """
                INSERT INTO games(
                    id, scan_root_id, relative_dir, install_path_key, title, status,
                    added_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'installed', ?, ?)
                """,
                (game_id, root_id, relative, install_key, title, now, now),
            )
            row = connection.execute(
                "SELECT * FROM games WHERE id = ?", (game_id,)
            ).fetchone()
            assert row is not None
            return game_from_row(row)

        return self._writer.submit(operation).result()


def _validate_display_path(display_path: str) -> str:
    clean = display_path.strip()
    drive, _ = ntpath.splitdrive(clean)
    if not clean or (not drive and not ntpath.isabs(clean)):
        raise InvalidRootConfiguration("A scan root must be an absolute Windows path.")
    return clean


def _validate_mode_depth(mode: str, max_depth: int) -> tuple[ScanMode, int]:
    if mode not in {"children", "recursive"}:
        raise InvalidRootConfiguration(f"Unknown scan mode: {mode}")
    if mode == "children":
        return "children", 1
    if not 1 <= max_depth <= 8:
        raise InvalidRootConfiguration("Recursive scan depth must be between 1 and 8.")
    return "recursive", max_depth


def _normalize_exclusions(exclusions: Sequence[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for exclusion in exclusions:
        value = exclusion.strip().replace("\\", "/")
        drive, _ = ntpath.splitdrive(value)
        parts = value.split("/")
        if not value or drive or value.startswith("/") or ".." in parts:
            raise InvalidRootConfiguration(f"Unsafe root exclusion: {exclusion}")
        value = posixpath.normpath(value)
        if value == ".":
            raise InvalidRootConfiguration(f"Unsafe root exclusion: {exclusion}")
        key = value.casefold()
        if key not in seen:
            normalized.append(value)
            seen.add(key)
    return tuple(normalized)


def _normalize_relative_directory(relative_dir: str) -> str:
    value = relative_dir.strip().replace("\\", "/")
    drive, _ = ntpath.splitdrive(value)
    parts = value.split("/")
    if not value or drive or value.startswith("/") or ".." in parts:
        raise InvalidRootConfiguration(f"Unsafe relative game directory: {relative_dir}")
    return posixpath.normpath(value)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _json_array(values: Sequence[str]) -> str:
    import json

    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))
