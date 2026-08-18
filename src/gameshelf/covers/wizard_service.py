"""Single-session coordinator for the batch cover review workspace."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, replace
from pathlib import Path
from threading import RLock
from typing import Literal, Protocol
from uuid import uuid4

from gameshelf.bootstrap.paths import AppPaths
from gameshelf.covers.candidate_images import stage_candidate_bytes
from gameshelf.covers.candidates import (
    CoverCandidate,
    CoverProgress,
    CoverProgressDetail,
    CoverWizardQueueItem,
    CoverWizardQueueStatus,
    CoverWizardSnapshot,
    merge_and_sort_candidates,
)
from gameshelf.covers.local_discovery import LocalDiscoverySummary
from gameshelf.covers.vndb import VndbError
from gameshelf.library.models import Game

_REPARSE_POINT = 0x400


class ActiveCoverWizardError(RuntimeError):
    """Raised when a second wizard is started while one is active."""


class CoverWizardNotFoundError(LookupError):
    """Raised when a wizard session ID is no longer active."""


class CoverCandidateNotFoundError(LookupError):
    """Raised when a candidate does not belong to the active session."""


class CoverWizardBusyError(RuntimeError):
    """Raised when two source operations or close overlap."""


class CandidateSourceChangedError(RuntimeError):
    """Raised when an adopted source disappeared or changed after preview."""


class _Library(Protocol):
    def list_games(self) -> tuple[Game, ...]: ...

    def get_game(self, game_id: str) -> Game | None: ...

    def install_directory(self, game_id: str) -> Path: ...


class _Covers(Protocol):
    def import_file(self, game_id: str, source_path: Path) -> object: ...


class _LocalDiscovery(Protocol):
    def scan_game_directory(
        self,
        game: Game,
        install_directory: Path,
        session_root: Path,
        limit: int,
        context: CoverProgress,
    ) -> LocalDiscoverySummary: ...

    def match_cover_directory(
        self,
        games: Sequence[Game],
        directory: Path,
        session_root: Path,
        context: CoverProgress,
    ) -> Mapping[str, LocalDiscoverySummary]: ...


class _Vndb(Protocol):
    def search(
        self,
        title: str,
        limit: int,
        session_root: Path,
        game_id: str,
        context: CoverProgress,
    ) -> tuple[CoverCandidate, ...]: ...


@dataclass(frozen=True)
class _VndbBatchProgress:
    parent: CoverProgress
    completed_games: int
    total_games: int
    current_index: int
    game_id: str
    game_title: str

    def report(
        self,
        completed: int,
        total: int | None,
        message: str,
        *,
        details: Mapping[str, CoverProgressDetail] | None = None,
    ) -> None:
        del completed, total
        merged: dict[str, CoverProgressDetail] = dict(details or {})
        merged["gameId"] = self.game_id
        merged["currentIndex"] = self.current_index
        self.parent.report(
            self.completed_games,
            self.total_games,
            (
                f"正在搜索 {self.current_index}/{self.total_games}："
                f"{self.game_title} · {message}"
            ),
            details=merged,
        )

    def raise_if_cancelled(self) -> None:
        self.parent.raise_if_cancelled()


@dataclass
class _Session:
    id: str
    root: Path
    items: list[CoverWizardQueueItem]
    candidates: dict[str, tuple[CoverCandidate, ...]]
    include_existing: bool
    current_game_id: str | None
    source_operation_active: bool = False


class CoverWizardService:
    def __init__(
        self,
        paths: AppPaths,
        library: _Library,
        covers: _Covers,
        local_discovery: _LocalDiscovery,
        vndb: _Vndb,
    ) -> None:
        self._paths = paths
        self._library = library
        self._covers = covers
        self._local = local_discovery
        self._vndb = vndb
        self._lock = RLock()
        self._session: _Session | None = None
        self._wizard_root = paths.temp_dir / "cover-wizard"
        self._wizard_root.mkdir(parents=True, exist_ok=True)
        self._cleanup_stale_sessions()

    def start(self, include_existing: bool = False) -> CoverWizardSnapshot:
        if not isinstance(include_existing, bool):
            raise ValueError("包含已有封面必须是布尔值。")
        with self._lock:
            if self._session is not None:
                raise ActiveCoverWizardError("已有批量封面向导正在运行。")
            session_id = str(uuid4())
            root = self._wizard_root / session_id
            root.mkdir(parents=True)
            items = [
                CoverWizardQueueItem(
                    game_id=game.id,
                    title=game.title,
                    initial_has_cover=game.cover_thumb_relpath is not None,
                    version=game.version,
                )
                for game in self._library.list_games()
            ]
            visible = [
                item for item in items if include_existing or not item.initial_has_cover
            ]
            self._session = _Session(
                id=session_id,
                root=root,
                items=items,
                candidates={item.game_id: () for item in items},
                include_existing=include_existing,
                current_game_id=visible[0].game_id if visible else None,
            )
            return self._snapshot(self._session)

    def snapshot(self, session_id: str) -> CoverWizardSnapshot:
        with self._lock:
            return self._snapshot(self._require_session(session_id))

    def set_include_existing(
        self, session_id: str, include_existing: bool
    ) -> CoverWizardSnapshot:
        if not isinstance(include_existing, bool):
            raise ValueError("包含已有封面必须是布尔值。")
        with self._lock:
            session = self._require_session(session_id)
            session.include_existing = include_existing
            visible = self._visible_items(session)
            visible_ids = {item.game_id for item in visible}
            if session.current_game_id not in visible_ids:
                session.current_game_id = visible[0].game_id if visible else None
            return self._snapshot(session)

    def list_candidates(
        self, session_id: str, game_id: str
    ) -> tuple[CoverCandidate, ...]:
        with self._lock:
            session = self._require_session(session_id)
            self._require_item(session, game_id)
            return session.candidates[game_id]

    def add_candidate_bytes(
        self,
        session_id: str,
        game_id: str,
        *,
        file_name: str,
        payload: bytes,
        source: Literal["clipboard", "drop"],
    ) -> CoverCandidate:
        if source not in {"clipboard", "drop"}:
            raise ValueError("手动封面候选来源必须是剪贴板或拖放。")
        with self._lock:
            session = self._require_session(session_id)
            self._require_item(session, game_id)
            if session.source_operation_active:
                raise CoverWizardBusyError("正在收集其他封面来源。")
            candidate_id = uuid4().hex
            source_path = session.root / "sources" / game_id / f"{candidate_id}.image"
            preview_path = session.root / "previews" / game_id / f"{candidate_id}.webp"
            staged = stage_candidate_bytes(payload, source_path, preview_path)
            source_label = "剪贴板" if source == "clipboard" else "拖放"
            candidate = CoverCandidate(
                id=candidate_id,
                game_id=game_id,
                source=source,
                source_label=source_label,
                display_name=file_name,
                width=staged.width,
                height=staged.height,
                sha256=staged.sha256,
                match_kind="manual",
                score=100.0,
                evidence=(source_label,),
                file_ref=staged.file_ref,
                preview_path=staged.preview_path,
            )
            self._merge(session, game_id, (candidate,))
            return next(
                item
                for item in session.candidates[game_id]
                if item.sha256 == candidate.sha256
            )

    def collect_shallow(
        self,
        session_id: str,
        game_id: str,
        limit: int,
        context: CoverProgress,
    ) -> LocalDiscoverySummary:
        session = self._begin_source(session_id)
        try:
            game = self._require_game(game_id)
            with self._lock:
                self._require_item(session, game_id)
            result = self._local.scan_game_directory(
                game,
                self._library.install_directory(game_id),
                session.root,
                limit,
                context,
            )
            with self._lock:
                self._merge(self._require_session(session_id), game_id, result.candidates)
            return result
        except Exception as error:
            with self._lock:
                self._mark_failed_if_active(session_id, game_id, str(error))
            raise
        finally:
            self._end_source(session_id)

    def collect_directory(
        self,
        session_id: str,
        directory: Path,
        context: CoverProgress,
    ) -> Mapping[str, LocalDiscoverySummary]:
        session = self._begin_source(session_id)
        try:
            with self._lock:
                games = tuple(
                    game
                    for item in self._visible_items(session)
                    if (game := self._library.get_game(item.game_id)) is not None
                )
            results = self._local.match_cover_directory(
                games, directory, session.root, context
            )
            with self._lock:
                current = self._require_session(session_id)
                for game_id, summary in results.items():
                    self._merge(current, game_id, summary.candidates)
            return results
        finally:
            self._end_source(session_id)

    def collect_vndb(
        self,
        session_id: str,
        game_ids: Sequence[str],
        limit: int,
        context: CoverProgress,
    ) -> CoverWizardSnapshot:
        session = self._begin_source(session_id)
        try:
            total_games = len(game_ids)
            for index, game_id in enumerate(game_ids, start=1):
                context.raise_if_cancelled()
                game = self._require_game(game_id)
                with self._lock:
                    self._require_item(session, game_id)
                batch_progress = _VndbBatchProgress(
                    context,
                    index - 1,
                    total_games,
                    index,
                    game.id,
                    _game_display_name(game),
                )
                batch_progress.report(0, None, "正在查询 VNDB")
                try:
                    candidates = self._vndb.search(
                        game.title, limit, session.root, game_id, batch_progress
                    )
                except VndbError as error:
                    with self._lock:
                        self._mark_failed_if_active(session_id, game_id, str(error))
                    context.report(
                        index,
                        total_games,
                        f"{_game_display_name(game)} 的 VNDB 搜索失败，继续下一个",
                        details={"gameId": game_id},
                    )
                    continue
                with self._lock:
                    self._merge(
                        self._require_session(session_id), game_id, candidates
                    )
                context.report(
                    index,
                    total_games,
                    f"已完成 {_game_display_name(game)} 的 VNDB 搜索",
                    details={"gameId": game_id},
                )
            with self._lock:
                return self._snapshot(self._require_session(session_id))
        finally:
            self._end_source(session_id)

    def adopt(self, session_id: str, candidate_id: str) -> Game:
        with self._lock:
            session = self._require_session(session_id)
            candidate = self._find_candidate(session, candidate_id)
            _verify_candidate_source(candidate)
            self._covers.import_file(candidate.game_id, candidate.file_ref.path)
            game = self._require_game(candidate.game_id)
            discarded = session.candidates[candidate.game_id]
            session.candidates[candidate.game_id] = ()
            self._update_item(
                session,
                candidate.game_id,
                status="adopted",
                candidate_count=0,
                error=None,
            )
            session.current_game_id = self._next_game_id(
                session, candidate.game_id
            )
            _cleanup_candidates(discarded)
            return game

    def skip(self, session_id: str, game_id: str) -> CoverWizardSnapshot:
        with self._lock:
            session = self._require_session(session_id)
            self._require_item(session, game_id)
            self._update_item(session, game_id, status="skipped", error=None)
            session.current_game_id = self._next_game_id(session, game_id)
            return self._snapshot(session)

    def preview_path(self, session_id: str, candidate_id: str) -> Path | None:
        with self._lock:
            try:
                session = self._require_session(session_id)
                return self._find_candidate(session, candidate_id).preview_path
            except (CoverWizardNotFoundError, CoverCandidateNotFoundError):
                return None

    def close(self, session_id: str) -> None:
        with self._lock:
            session = self._require_session(session_id)
            if session.source_operation_active:
                raise CoverWizardBusyError("封面来源仍在收集中，暂时不能关闭向导。")
            self._session = None
            shutil.rmtree(session.root, ignore_errors=True)

    def close_all(self) -> None:
        with self._lock:
            if self._session is None:
                return
            self.close(self._session.id)

    def _snapshot(self, session: _Session) -> CoverWizardSnapshot:
        return CoverWizardSnapshot(
            id=session.id,
            queue=tuple(self._visible_items(session)),
            current_game_id=session.current_game_id,
            include_existing=session.include_existing,
            source_operation_active=session.source_operation_active,
        )

    def _visible_items(self, session: _Session) -> list[CoverWizardQueueItem]:
        return [
            item
            for item in session.items
            if session.include_existing or not item.initial_has_cover
        ]

    def _require_session(self, session_id: str) -> _Session:
        if self._session is None or self._session.id != session_id:
            raise CoverWizardNotFoundError(session_id)
        return self._session

    @staticmethod
    def _require_item(session: _Session, game_id: str) -> CoverWizardQueueItem:
        item = next((item for item in session.items if item.game_id == game_id), None)
        if item is None:
            raise CoverCandidateNotFoundError(game_id)
        return item

    def _require_game(self, game_id: str) -> Game:
        game = self._library.get_game(game_id)
        if game is None:
            raise CoverCandidateNotFoundError(game_id)
        return game

    def _begin_source(self, session_id: str) -> _Session:
        with self._lock:
            session = self._require_session(session_id)
            if session.source_operation_active:
                raise CoverWizardBusyError("已有封面来源正在收集中。")
            session.source_operation_active = True
            return session

    def _end_source(self, session_id: str) -> None:
        with self._lock:
            if self._session is not None and self._session.id == session_id:
                self._session.source_operation_active = False

    def _merge(
        self,
        session: _Session,
        game_id: str,
        additions: Sequence[CoverCandidate],
    ) -> None:
        self._require_item(session, game_id)
        if any(candidate.game_id != game_id for candidate in additions):
            raise ValueError("封面候选不能跨游戏汇入。")
        combined = (*session.candidates[game_id], *additions)
        merged = merge_and_sort_candidates(combined)
        retained = {candidate.id for candidate in merged}
        _cleanup_candidates(
            tuple(candidate for candidate in combined if candidate.id not in retained)
        )
        session.candidates[game_id] = merged
        item = self._require_item(session, game_id)
        if item.status not in {"adopted", "skipped"}:
            self._update_item(
                session,
                game_id,
                status="ready" if merged else "pending",
                candidate_count=len(merged),
                error=None,
            )

    def _update_item(
        self,
        session: _Session,
        game_id: str,
        *,
        status: CoverWizardQueueStatus,
        candidate_count: int | None = None,
        error: str | None = None,
    ) -> None:
        for index, item in enumerate(session.items):
            if item.game_id == game_id:
                session.items[index] = replace(
                    item,
                    status=status,
                    candidate_count=(
                        item.candidate_count
                        if candidate_count is None
                        else candidate_count
                    ),
                    error=error,
                )
                return
        raise CoverCandidateNotFoundError(game_id)

    def _mark_failed_if_active(
        self, session_id: str, game_id: str, message: str
    ) -> None:
        if self._session is None or self._session.id != session_id:
            return
        item = self._require_item(self._session, game_id)
        if item.status not in {"adopted", "skipped"}:
            self._update_item(
                self._session, game_id, status="failed", error=message
            )

    @staticmethod
    def _find_candidate(session: _Session, candidate_id: str) -> CoverCandidate:
        for candidates in session.candidates.values():
            for candidate in candidates:
                if candidate.id == candidate_id:
                    return candidate
        raise CoverCandidateNotFoundError(candidate_id)

    def _next_game_id(self, session: _Session, current_game_id: str) -> str | None:
        visible = self._visible_items(session)
        current_index = next(
            (index for index, item in enumerate(visible) if item.game_id == current_game_id),
            -1,
        )
        for item in visible[current_index + 1 :]:
            if item.status in {"pending", "ready", "failed"}:
                return item.game_id
        return None

    def _cleanup_stale_sessions(self) -> None:
        try:
            entries = tuple(os.scandir(self._wizard_root))
        except OSError:
            return
        for entry in entries:
            path = Path(entry.path)
            try:
                if entry.is_dir(follow_symlinks=False) and not _is_reparse_path(path):
                    shutil.rmtree(path)
            except OSError:
                continue


def _game_display_name(game: Game) -> str:
    if game.version:
        return f"{game.title} {game.version}"
    return game.title


def _verify_candidate_source(candidate: CoverCandidate) -> None:
    path = candidate.file_ref.path
    try:
        metadata = path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or _is_reparse_metadata(metadata)
            or path.is_symlink()
        ):
            raise CandidateSourceChangedError("封面候选源文件已变化。")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(64 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise CandidateSourceChangedError("封面候选源文件已不可用。") from error
    if digest.hexdigest() != candidate.file_ref.expected_sha256:
        raise CandidateSourceChangedError("封面候选源文件已变化。")


def _cleanup_candidates(candidates: Sequence[CoverCandidate]) -> None:
    for candidate in candidates:
        with suppress(OSError):
            candidate.preview_path.unlink(missing_ok=True)
        if candidate.file_ref.temporary:
            with suppress(OSError):
                candidate.file_ref.path.unlink(missing_ok=True)


def _is_reparse_metadata(metadata: os.stat_result) -> bool:
    return bool(getattr(metadata, "st_file_attributes", 0) & _REPARSE_POINT)


def _is_reparse_path(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return True
    return path.is_symlink() or _is_reparse_metadata(metadata)
