"""Transactional commands for scan roots and game-library records."""

from __future__ import annotations

import ntpath
import posixpath
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from gameshelf.db.writer import DbWriter
from gameshelf.library.models import (
    BatchGameRemovalResult,
    Game,
    GameRemovalRequest,
    RemovableGameStatus,
    ScanMode,
    ScanRoot,
)
from gameshelf.library.repository import (
    LibraryRepository,
    game_from_row_with_groups,
    scan_root_from_row,
)
from gameshelf.scanning.path_keys import (
    PathTraversalError,
    expand_relative,
    is_same_or_child,
    windows_path_key,
)
from gameshelf.scanning.pe_metadata import read_pe_metadata


class InvalidRootConfiguration(ValueError):
    """Raised when a root mode, depth, or exclusion is unsafe."""


class RootNotFoundError(LookupError):
    """Raised when a scan-root command names an unknown record."""


class GameNotFoundError(LookupError):
    """Raised when a game-library command names an unknown record."""


class InvalidExecutableError(ValueError):
    """Raised when a manually selected executable is unsafe or unavailable."""


class InvalidGameConfiguration(ValueError):
    """Raised when editable game metadata is malformed."""


class InvalidEngineConfiguration(ValueError):
    """Raised when a manual engine value is malformed."""


class InvalidGameRemoval(ValueError):
    """Raised when a game record cannot use the requested removal flow."""


class LibraryService:
    MAX_BATCH_REMOVALS = 500

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
            connection.execute(
                """
                DELETE FROM game_analysis_cache
                WHERE game_id IN (SELECT id FROM games WHERE scan_root_id = ?)
                """,
                (root_id,),
            )
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

    def remove_games(
        self, requests: Sequence[GameRemovalRequest]
    ) -> BatchGameRemovalResult:
        if not requests:
            raise InvalidGameRemoval("At least one game must be selected for removal.")
        if len(requests) > self.MAX_BATCH_REMOVALS:
            raise InvalidGameRemoval(
                f"A batch removal cannot contain more than {self.MAX_BATCH_REMOVALS} items."
            )

        unique_requests: dict[str, RemovableGameStatus] = {}
        for request in requests:
            game_id = request.game_id.strip()
            expected_status = request.expected_status
            if not game_id or expected_status not in ("installed", "missing"):
                raise InvalidGameRemoval("Each removal item must name a removable game status.")
            previous = unique_requests.get(game_id)
            if previous is not None and previous != expected_status:
                raise InvalidGameRemoval(
                    "A duplicate game cannot declare conflicting expected statuses."
                )
            unique_requests[game_id] = expected_status

        def operation(connection: sqlite3.Connection) -> BatchGameRemovalResult:
            installed_count = 0
            missing_count = 0
            root_additions: dict[str, list[str]] = {}
            root_rows: dict[str, sqlite3.Row] = {}
            cover_paths: list[str] = []
            seen_cover_paths: set[str] = set()

            for game_id, expected_status in unique_requests.items():
                game = connection.execute(
                    """
                    SELECT status, scan_root_id, relative_dir,
                           cover_original_relpath, cover_thumb_relpath
                    FROM games WHERE id = ?
                    """,
                    (game_id,),
                ).fetchone()
                if game is None:
                    raise GameNotFoundError(game_id)
                if game["status"] != expected_status:
                    raise InvalidGameRemoval(
                        "A selected game's status changed before the batch was applied; "
                        f"expected {expected_status}."
                    )

                if expected_status == "installed":
                    root_id = game["scan_root_id"]
                    relative_value = game["relative_dir"]
                    if root_id is None or relative_value is None:
                        raise InvalidGameRemoval(
                            "An installed game must belong to a scan root and relative directory."
                        )
                    try:
                        relative = _normalize_relative_directory(str(relative_value))
                    except InvalidRootConfiguration as error:
                        raise InvalidGameRemoval(
                            "An installed game has an unsafe relative directory."
                        ) from error
                    root_id = str(root_id)
                    if root_id not in root_rows:
                        root = connection.execute(
                            "SELECT * FROM scan_roots WHERE id = ?", (root_id,)
                        ).fetchone()
                        if root is None:
                            raise RootNotFoundError(root_id)
                        root_rows[root_id] = root
                        root_additions[root_id] = []
                    root_additions[root_id].append(relative)
                    installed_count += 1
                else:
                    missing_count += 1

                for relative_cover in (
                    game["cover_original_relpath"],
                    game["cover_thumb_relpath"],
                ):
                    if relative_cover is None:
                        continue
                    relative_cover = str(relative_cover)
                    if relative_cover not in seen_cover_paths:
                        cover_paths.append(relative_cover)
                        seen_cover_paths.add(relative_cover)

            for root_id, additions in root_additions.items():
                root = root_rows[root_id]
                exclusions = _normalize_exclusions(
                    (*_json_string_tuple(root["exclusions_json"]), *additions)
                )
                connection.execute(
                    "UPDATE scan_roots SET exclusions_json = json(?) WHERE id = ?",
                    (_json_array(exclusions), root_id),
                )

            updated_roots = tuple(
                scan_root_from_row(row)
                for root_id in root_additions
                if (
                    row := connection.execute(
                        "SELECT * FROM scan_roots WHERE id = ?", (root_id,)
                    ).fetchone()
                )
                is not None
            )
            assert len(updated_roots) == len(root_additions)

            connection.executemany(
                "DELETE FROM games WHERE id = ?",
                ((game_id,) for game_id in unique_requests),
            )
            return BatchGameRemovalResult(
                installed_count=installed_count,
                missing_count=missing_count,
                updated_roots=updated_roots,
                managed_cover_relpaths=tuple(cover_paths),
            )

        return self._writer.submit(operation).result()

    def remove_game_and_exclude(self, game_id: str) -> ScanRoot:
        result = self.remove_games((GameRemovalRequest(game_id, "installed"),))
        assert len(result.updated_roots) == 1
        return result.updated_roots[0]

    def delete_missing_game(self, game_id: str) -> None:
        self.remove_games((GameRemovalRequest(game_id, "missing"),))

    def set_game_metadata(
        self,
        game_id: str,
        title: str,
        version: str | None,
    ) -> Game:
        clean_title = title.strip()
        clean_version = version.strip() if version is not None else ""
        if not clean_title:
            raise InvalidGameConfiguration("游戏标题不能为空。")
        return self._update_game(
            game_id,
            "title = ?, title_is_manual = 1, "
            "version = ?, version_is_manual = 1, updated_at = ?",
            (clean_title, clean_version or None, _utc_now()),
        )

    def set_game_executable(self, game_id: str, selected_path: str) -> Game:
        game = self._require_game(game_id)
        install_dir = self.install_directory(game_id)
        selected = Path(selected_path)
        selected_key = windows_path_key(selected)
        if (
            not is_same_or_child(selected_key, windows_path_key(install_dir))
            or selected.suffix.casefold() != ".exe"
            or not selected.is_file()
        ):
            raise InvalidExecutableError(
                "The executable must be an existing .exe inside the game directory."
            )
        relative = ntpath.relpath(str(selected), str(install_dir)).replace("\\", "/")
        try:
            expand_relative(install_dir, relative)
        except PathTraversalError as error:
            raise InvalidExecutableError("The executable leaves the game directory.") from error
        architecture = read_pe_metadata(selected).architecture
        return self._update_game(
            game.id,
            """
            main_exe_relpath = ?, main_exe_is_manual = 1, exe_arch = ?,
            updated_at = ?
            """,
            (relative, architecture, _utc_now()),
            invalidate_analysis_cache=True,
        )

    def set_game_engine(
        self,
        game_id: str,
        engine_id: str | None,
        variant: str | None = None,
    ) -> Game:
        clean_engine_id = None
        if engine_id is not None:
            clean_engine_id = engine_id.strip()
            if not clean_engine_id or "\x00" in clean_engine_id:
                raise InvalidEngineConfiguration("引擎名称无效。")
        clean_variant = variant.strip() if variant is not None else None
        if clean_variant == "":
            clean_variant = None
        if clean_variant is not None and "\x00" in clean_variant:
            raise InvalidEngineConfiguration("引擎变体无效。")
        return self._update_game(
            game_id,
            """
            engine_id = ?, engine_variant = ?, engine_is_manual = 1,
            updated_at = ?
            """,
            (clean_engine_id, clean_variant, _utc_now()),
        )

    def clear_manual_engine(self, game_id: str) -> Game:
        return self._update_game(
            game_id,
            """
            engine_id = detected_engine_id,
            engine_variant = detected_engine_variant,
            engine_is_manual = 0, updated_at = ?
            """,
            (_utc_now(),),
        )

    def update_launch_configuration(
        self,
        game_id: str,
        *,
        working_dir_relpath: str | None,
        launch_args: Sequence[str],
        environment: Mapping[str, str],
    ) -> Game:
        install_dir = self.install_directory(game_id)
        clean_working_dir: str | None = None
        if working_dir_relpath is not None and working_dir_relpath.strip():
            clean_working_dir = _normalize_relative_directory(working_dir_relpath)
            try:
                expand_relative(install_dir, clean_working_dir)
            except PathTraversalError as error:
                raise InvalidGameConfiguration(
                    "Working directory must remain inside the game directory."
                ) from error
        clean_args = tuple(_validate_text(value, "launch argument") for value in launch_args)
        clean_environment: dict[str, str] = {}
        for key, value in environment.items():
            clean_key = _validate_text(key, "environment key")
            clean_value = _validate_text(value, "environment value")
            if not clean_key or "=" in clean_key:
                raise InvalidGameConfiguration("Invalid environment variable name.")
            clean_environment[clean_key] = clean_value
        return self._update_game(
            game_id,
            """
            working_dir_relpath = ?, launch_args_json = ?, environment_json = ?,
            updated_at = ?
            """,
            (
                clean_working_dir,
                _json_array(clean_args),
                _json_object(clean_environment),
                _utc_now(),
            ),
        )

    def install_directory(self, game_id: str) -> Path:
        game = self._require_game(game_id)
        if game.scan_root_id is not None and game.relative_dir is not None:
            root = self._repository.get_root(game.scan_root_id)
            if root is not None:
                try:
                    return expand_relative(Path(root.display_path), game.relative_dir)
                except PathTraversalError as error:
                    raise InvalidGameConfiguration(
                        "Stored game directory is unsafe."
                    ) from error
        if game.install_path_key is not None:
            return Path(game.install_path_key)
        raise InvalidGameConfiguration("Game has no installation directory.")

    def _require_game(self, game_id: str) -> Game:
        game = self._repository.get_game(game_id)
        if game is None:
            raise GameNotFoundError(game_id)
        return game

    def _update_game(
        self,
        game_id: str,
        assignments: str,
        parameters: tuple[object, ...],
        *,
        invalidate_analysis_cache: bool = False,
    ) -> Game:
        def operation(connection: sqlite3.Connection) -> Game:
            cursor = connection.execute(
                f"UPDATE games SET {assignments} WHERE id = ?",  # noqa: S608
                (*parameters, game_id),
            )
            if cursor.rowcount == 0:
                raise GameNotFoundError(game_id)
            if invalidate_analysis_cache:
                connection.execute(
                    "DELETE FROM game_analysis_cache WHERE game_id = ?",
                    (game_id,),
                )
            row = connection.execute(
                "SELECT * FROM games WHERE id = ?", (game_id,)
            ).fetchone()
            assert row is not None
            return game_from_row_with_groups(connection, row)

        return self._writer.submit(operation).result()

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
            return game_from_row_with_groups(connection, row)

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


def _json_object(values: Mapping[str, str]) -> str:
    import json

    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


def _json_string_tuple(value: str) -> tuple[str, ...]:
    import json

    decoded = json.loads(value)
    return tuple(str(item) for item in decoded) if isinstance(decoded, list) else ()


def _validate_text(value: str, label: str) -> str:
    if "\x00" in value:
        raise InvalidGameConfiguration(f"Invalid NUL character in {label}.")
    return value
