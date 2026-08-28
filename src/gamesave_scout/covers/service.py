"""Compensating file/database transactions for one managed cover per game."""

from __future__ import annotations

import logging
import mimetypes
import os
import sqlite3
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import BinaryIO
from uuid import uuid4

from gamesave_scout.bootstrap.paths import AppPaths
from gamesave_scout.covers.image_pipeline import InvalidCoverImage, normalize_cover
from gamesave_scout.covers.models import CoverFiles
from gamesave_scout.db.writer import DbWriter
from gamesave_scout.library.repository import LibraryRepository
from gamesave_scout.library.service import GameNotFoundError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _StoredCover:
    original: str | None
    thumb: str | None
    revision: int


class CoverService:
    def __init__(
        self,
        paths: AppPaths,
        repository: LibraryRepository,
        writer: DbWriter,
        optimize_enabled: Callable[[], bool],
    ) -> None:
        self._paths = paths
        self._repository = repository
        self._writer = writer
        self._optimize_enabled = optimize_enabled

    def import_file(self, game_id: str, source_path: Path) -> CoverFiles:
        content_type = mimetypes.guess_type(source_path.name)[0] or "application/octet-stream"
        try:
            with source_path.open("rb") as source:
                return self._import(game_id, source, content_type)
        except OSError as error:
            raise InvalidCoverImage(f"Cannot read cover source: {source_path}") from error

    def import_clipboard_png(self, game_id: str, png_bytes: bytes) -> CoverFiles:
        if not png_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            raise InvalidCoverImage("Clipboard payload is not a PNG image.")
        return self._import(game_id, BytesIO(png_bytes), "image/png")

    def remove(self, game_id: str) -> None:
        old = self._stored_cover(game_id)

        def operation(connection: sqlite3.Connection) -> None:
            changed = connection.execute(
                """
                UPDATE games
                SET cover_original_relpath = NULL, cover_thumb_relpath = NULL,
                    cover_revision = cover_revision + 1
                WHERE id = ?
                """,
                (game_id,),
            ).rowcount
            if changed == 0:
                raise GameNotFoundError(game_id)

        self._writer.submit(operation).result()
        self._delete_old(old)

    def cleanup_managed_files(self, relative_paths: Sequence[str]) -> int:
        """Delete captured cover files without trusting database paths as filesystem paths."""
        warnings = 0
        seen: set[str] = set()
        allowed_prefixes = {("covers", "original"), ("covers", "thumbs")}
        for relative in relative_paths:
            if relative in seen:
                continue
            seen.add(relative)
            portable = PurePosixPath(relative)
            parts = portable.parts
            if (
                portable.is_absolute()
                or ".." in parts
                or len(parts) != 3
                or tuple(parts[:2]) not in allowed_prefixes
            ):
                warnings += 1
                logger.warning("Skipped unsafe managed cover cleanup path: %s", relative)
                continue
            candidate = self._paths.data_dir.joinpath(*parts)
            try:
                candidate.unlink(missing_ok=True)
            except OSError as error:
                warnings += 1
                logger.warning("Could not clean managed cover file %s: %s", candidate, error)
        return warnings

    def _import(
        self, game_id: str, source: BinaryIO, content_type: str
    ) -> CoverFiles:
        old = self._stored_cover(game_id)
        revision = old.revision + 1
        staging_stem = self._paths.temp_dir / f"cover-{game_id}-{uuid4().hex}"
        normalized = normalize_cover(
            source,
            content_type,
            staging_stem,
            optimize=self._optimize_enabled(),
        )
        staged_original = self._paths.temp_dir / normalized.original_relpath
        staged_thumb = self._paths.temp_dir / normalized.thumb_relpath
        final_original = self._paths.covers_original_dir / (
            f"{game_id}-r{revision}-{uuid4().hex[:8]}{staged_original.suffix}"
        )
        final_thumb = self._paths.covers_thumbs_dir / (
            f"{game_id}-r{revision}-{uuid4().hex[:8]}.webp"
        )
        new_files = (final_original, final_thumb)
        try:
            os.replace(staged_original, final_original)
            os.replace(staged_thumb, final_thumb)
            result = CoverFiles(
                final_original.relative_to(self._paths.data_dir).as_posix(),
                final_thumb.relative_to(self._paths.data_dir).as_posix(),
                revision,
            )

            def operation(connection: sqlite3.Connection) -> None:
                changed = connection.execute(
                    """
                    UPDATE games
                    SET cover_original_relpath = ?, cover_thumb_relpath = ?,
                        cover_revision = ?
                    WHERE id = ?
                    """,
                    (
                        result.original_relpath,
                        result.thumb_relpath,
                        result.revision,
                        game_id,
                    ),
                ).rowcount
                if changed == 0:
                    raise GameNotFoundError(game_id)

            self._writer.submit(operation).result()
        except Exception:
            for path in (*new_files, staged_original, staged_thumb):
                with suppress(OSError):
                    path.unlink(missing_ok=True)
            raise
        self._delete_old(old)
        return result

    def _stored_cover(self, game_id: str) -> _StoredCover:
        if self._repository.get_game(game_id) is None:
            raise GameNotFoundError(game_id)
        with self._repository.factory.connect(readonly=True) as connection:
            row = connection.execute(
                """
                SELECT cover_original_relpath, cover_thumb_relpath, cover_revision
                FROM games WHERE id = ?
                """,
                (game_id,),
            ).fetchone()
        assert row is not None
        return _StoredCover(row[0], row[1], int(row[2]))

    def _delete_old(self, old: _StoredCover) -> None:
        self.cleanup_managed_files(
            tuple(relative for relative in (old.original, old.thumb) if relative is not None)
        )
