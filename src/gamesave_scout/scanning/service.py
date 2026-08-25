"""Cancellable two-phase game-library scans."""

from __future__ import annotations

import json
import logging
import sqlite3
import stat
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Literal
from uuid import uuid4

from gamesave_scout.bridge.tasks import TaskCancelled, TaskContext
from gamesave_scout.db.writer import DbWriter
from gamesave_scout.engines.service import EngineDetectionService
from gamesave_scout.library.models import Game, ScanRoot
from gamesave_scout.library.repository import LibraryRepository, game_from_row_with_groups
from gamesave_scout.library.service import RootNotFoundError
from gamesave_scout.library.title_parser import split_title_and_version
from gamesave_scout.scanning.analysis import AnalyzedCandidate, GameAnalyzer
from gamesave_scout.scanning.analysis_cache import (
    AnalysisCacheEntry,
    AnalysisCacheRepository,
    PendingAnalysisCache,
    delete_analysis_cache,
    upsert_analysis_cache,
)
from gamesave_scout.scanning.analysis_pool import ScanAnalysisPool
from gamesave_scout.scanning.discovery import RootUnavailableError, enumerate_candidates
from gamesave_scout.scanning.models import DirectoryCandidate
from gamesave_scout.scanning.path_keys import (
    PathTraversalError,
    expand_relative,
    is_same_or_child,
    windows_path_key,
)
from gamesave_scout.scanning.reconcile import MoveSuggestion, reconcile_session

type ScanKind = Literal["quick", "full"]
type ScanStatus = Literal["completed", "cancelled", "failed", "unavailable"]
type PathProbeStatus = Literal["present", "missing", "unknown"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScanSummary:
    session_id: str
    status: ScanStatus
    discovered: int
    added: int
    updated: int
    missing: int
    warnings: int
    move_suggestions: tuple[MoveSuggestion, ...]
    games: tuple[Game, ...] = ()
    checked: int = 0
    cache_hits: int = 0
    reanalyzed: int = 0
    full_analyses: int = 0


@dataclass(frozen=True)
class PathProbe:
    status: PathProbeStatus
    warning: str | None = None


@dataclass(frozen=True)
class _QuickWork:
    candidate: DirectoryCandidate
    existing: Game
    cache: AnalysisCacheEntry | None


@dataclass(frozen=True)
class _AnalysisWork:
    candidate: DirectoryCandidate
    existing: Game | None
    cache: AnalysisCacheEntry | None


class RootDisabledError(ValueError):
    """Raised before a disabled root can create a scan session."""


class ScanService:
    def __init__(
        self,
        repository: LibraryRepository,
        writer: DbWriter,
        engine_detection: EngineDetectionService | None = None,
        *,
        engine_detection_provider: (
            Callable[[], EngineDetectionService | None] | None
        ) = None,
        analysis_pool: ScanAnalysisPool | None = None,
        analyzer: GameAnalyzer | None = None,
        analysis_cache: AnalysisCacheRepository | None = None,
    ) -> None:
        self._repository = repository
        self._writer = writer
        if engine_detection is not None and engine_detection_provider is not None:
            raise ValueError("不能同时提供固定引擎服务和动态引擎服务提供者。")
        self._engine_detection_provider = engine_detection_provider or (
            lambda: engine_detection
        )
        self._analysis_pool = analysis_pool
        self._analyzer_override = analyzer
        self._analysis_cache = analysis_cache or AnalysisCacheRepository(
            repository.factory
        )

    def scan_root(
        self, root_id: str, scan_kind: ScanKind, context: TaskContext
    ) -> ScanSummary:
        if scan_kind not in {"quick", "full"}:
            raise ValueError(f"Unknown scan kind: {scan_kind}")
        root = self._repository.get_root(root_id)
        if root is None:
            raise RootNotFoundError(root_id)
        if not root.enabled:
            raise RootDisabledError("该游戏目录未参与扫描。")
        analyzer = self._analyzer_for_task()
        if scan_kind == "quick":
            return self._scan_quick(root, context, analyzer)
        session_id = self._create_session(root_id, scan_kind)
        started_at = time.monotonic()
        discovered = 0
        warnings = 0
        directories_scanned = 0
        inaccessible_directories = 0
        current_path = "."
        checked = 0
        cache_hits = 0
        reanalyzed = 0
        full_analyses = 0
        progress_lock = Lock()
        candidates: list[DirectoryCandidate] = []

        def report(
            stage: str,
            message: str,
            *,
            completed: int | None = None,
            total: int | None = None,
            **summary: int,
        ) -> None:
            context.report(
                discovered if completed is None else completed,
                total,
                message,
                details={
                    "stage": stage,
                    "currentPath": current_path,
                    "directoriesScanned": directories_scanned,
                    "discovered": discovered,
                    "inaccessibleDirectories": inaccessible_directories,
                    "warnings": warnings,
                    "checked": checked,
                    "cacheHits": cache_hits,
                    "reanalyzed": reanalyzed,
                    "fullAnalyses": full_analyses,
                    "elapsedSeconds": round(time.monotonic() - started_at, 2),
                    **summary,
                },
            )

        def observe_directory(path: Path, accessible: bool) -> None:
            nonlocal current_path, directories_scanned, inaccessible_directories, warnings
            directories_scanned += 1
            try:
                relative = path.relative_to(Path(root.display_path)).as_posix()
            except ValueError:
                relative = path.name
            current_path = relative or "."
            if not accessible:
                inaccessible_directories += 1
                warnings += 1
            report("discovering", f"正在检查：{current_path}")

        report("preparing", "正在准备扫描…")
        try:
            context.raise_if_cancelled()
            for candidate in self._candidates(
                root, scan_kind, context, observe_directory
            ):
                context.raise_if_cancelled()
                install_key = windows_path_key(candidate.path)
                if self._owning_root_id(install_key) != root.id:
                    continue
                candidates.append(candidate)
                discovered += 1
                current_path = candidate.relative_dir
                report("discovering", f"已发现：{candidate.relative_dir}")
            context.raise_if_cancelled()

            work: list[_AnalysisWork] = []
            for candidate in candidates:
                install_key = windows_path_key(candidate.path)
                existing = self._repository.get_game_by_install_path_key(install_key)
                work.append(
                    _AnalysisWork(
                        candidate,
                        existing,
                        self._analysis_cache.get(existing.id)
                        if existing is not None
                        else None,
                    )
                )

            def analyze(item: _AnalysisWork) -> tuple[_AnalysisWork, AnalyzedCandidate]:
                nonlocal checked, warnings, cache_hits, reanalyzed, full_analyses
                nonlocal current_path
                result = analyzer.analyze(
                    item.candidate,
                    item.existing,
                    item.cache,
                    context,
                )
                with progress_lock:
                    checked += 1
                    warnings += result.warning_count
                    current_path = item.candidate.relative_dir
                    if result.analysis_kind == "reuse":
                        cache_hits += 1
                    elif result.analysis_kind == "full":
                        full_analyses += 1
                    else:
                        reanalyzed += 1
                    report(
                        "analyzing",
                        f"正在分析：{current_path}",
                        completed=checked,
                        total=len(work),
                    )
                return item, result

            analyzed = (
                self._analysis_pool.map_ordered(tuple(work), analyze, context)
                if self._analysis_pool is not None
                else tuple(analyze(item) for item in work)
            )
            batch: list[tuple[str, str]] = []
            for item, analysis_result in analyzed:
                detected_title, detected_version = split_title_and_version(
                    item.candidate.path.name
                )
                payload = {
                    "relativeDir": item.candidate.relative_dir,
                    "title": detected_title,
                    "version": detected_version,
                    **analysis_result.payload,
                    "analysisCache": _pending_cache_payload(analysis_result),
                }
                batch.append(
                    (
                        windows_path_key(item.candidate.path),
                        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    )
                )
                if len(batch) == 200:
                    self._stage_batch(session_id, batch)
                    batch.clear()
            if batch:
                self._stage_batch(session_id, batch)
            context.raise_if_cancelled()
        except RootUnavailableError as error:
            self._finish_without_reconcile(session_id, root.id, "unavailable", str(error))
            report("unavailable", "根目录暂时无法访问。")
            return _empty_summary(session_id, "unavailable", discovered)
        except TaskCancelled:
            self._finish_without_reconcile(session_id, root.id, "cancelled", "Scan cancelled.")
            report("cancelled", "扫描已取消。")
            raise
        except Exception as error:
            self._finish_without_reconcile(session_id, root.id, "failed", str(error))
            report("failed", "扫描失败。")
            raise

        report("reconciling", "正在更新游戏库…")
        result = self._writer.submit(
            lambda connection: reconcile_session(connection, session_id, root, scan_kind)
        ).result()
        summary = ScanSummary(
            session_id=session_id,
            status="completed",
            discovered=discovered,
            added=result.added,
            updated=result.updated,
            missing=result.missing,
            warnings=warnings,
            move_suggestions=result.move_suggestions,
            games=result.games,
            checked=checked,
            cache_hits=cache_hits,
            reanalyzed=reanalyzed,
            full_analyses=full_analyses,
        )
        report(
            "completed",
            "扫描完成。",
            added=result.added,
            updated=result.updated,
            missing=result.missing,
            completed=checked,
            total=len(candidates),
        )
        return summary

    def _scan_quick(
        self,
        root: ScanRoot,
        context: TaskContext,
        analyzer: GameAnalyzer,
    ) -> ScanSummary:
        session_id = self._create_session(root.id, "quick")
        started_at = time.monotonic()
        known_games = self._repository.list_games_for_root(root.id)
        total = len(known_games)
        checked = 0
        discovered = 0
        warnings = 0
        inaccessible_directories = 0
        current_path = "."
        cache_hits = 0
        reanalyzed = 0
        full_analyses = 0
        progress_lock = Lock()

        def report(stage: str, message: str, **summary: int) -> None:
            context.report(
                checked,
                total,
                message,
                details={
                    "stage": stage,
                    "currentPath": current_path,
                    "directoriesScanned": checked,
                    "discovered": discovered,
                    "inaccessibleDirectories": inaccessible_directories,
                    "warnings": warnings,
                    "checked": checked,
                    "cacheHits": cache_hits,
                    "reanalyzed": reanalyzed,
                    "fullAnalyses": full_analyses,
                    "elapsedSeconds": round(time.monotonic() - started_at, 2),
                    **summary,
                },
            )

        report("preparing", "正在准备快速核验…")
        root_path = Path(root.display_path)
        root_probe = _probe_directory(root_path)
        if root_probe.status != "present":
            message = root_probe.warning or "根目录不存在或不再是目录。"
            warnings = int(root_probe.status == "unknown")
            self._finish_without_reconcile(
                session_id,
                root.id,
                "unavailable",
                message,
            )
            report("unavailable", "根目录暂时无法访问。")
            return ScanSummary(
                session_id,
                "unavailable",
                0,
                0,
                0,
                0,
                warnings,
                (),
                checked=0,
            )

        work: list[_QuickWork] = []
        missing_game_ids: list[str] = []
        try:
            for game in known_games:
                context.raise_if_cancelled()
                relative = game.relative_dir
                current_path = relative or game.title
                if relative is None:
                    probe = PathProbe("unknown", "游戏记录缺少相对目录。")
                else:
                    try:
                        game_path = expand_relative(root_path, relative)
                    except PathTraversalError:
                        probe = PathProbe("unknown", "游戏目录越过了根目录边界。")
                    else:
                        probe = _probe_directory(game_path)
                if probe.status == "present":
                    assert relative is not None
                    candidate = DirectoryCandidate(
                        path=game_path,
                        relative_dir=relative,
                        depth=len(relative.split("/")),
                        reason="direct_child",
                    )
                    work.append(
                        _QuickWork(
                            candidate,
                            game,
                            self._analysis_cache.get(game.id),
                        )
                    )
                    continue
                checked += 1
                if probe.status == "missing":
                    missing_game_ids.append(game.id)
                    report("checking", f"目录已不存在：{current_path}")
                else:
                    warnings += 1
                    inaccessible_directories += 1
                    logger.warning(
                        "Cannot determine game directory state for %s: %s",
                        current_path,
                        probe.warning,
                    )
                    report("checking", f"无法核验：{current_path}")

            def analyze(item: _QuickWork) -> tuple[_QuickWork, AnalyzedCandidate]:
                nonlocal checked, discovered, warnings
                nonlocal cache_hits, reanalyzed, full_analyses, current_path
                result = analyzer.analyze(
                    item.candidate,
                    item.existing,
                    item.cache,
                    context,
                )
                with progress_lock:
                    checked += 1
                    discovered += 1
                    warnings += result.warning_count
                    current_path = item.candidate.relative_dir
                    if result.analysis_kind == "reuse":
                        cache_hits += 1
                    elif result.analysis_kind == "full":
                        full_analyses += 1
                    else:
                        reanalyzed += 1
                    report("checking", f"已核验：{current_path}")
                return item, result

            analyzed = (
                self._analysis_pool.map_ordered(tuple(work), analyze, context)
                if self._analysis_pool is not None
                else tuple(analyze(item) for item in work)
            )
            batch: list[tuple[str, str]] = []
            for item, analysis_result in analyzed:
                detected_title, detected_version = split_title_and_version(
                    item.candidate.path.name
                )
                payload = {
                    "relativeDir": item.candidate.relative_dir,
                    "title": detected_title,
                    "version": detected_version,
                    **analysis_result.payload,
                    "analysisCache": _pending_cache_payload(analysis_result),
                }
                install_key = item.existing.install_path_key or windows_path_key(
                    item.candidate.path
                )
                batch.append(
                    (
                        install_key,
                        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    )
                )
                if len(batch) == 200:
                    self._stage_batch(session_id, batch)
                    batch.clear()
            if batch:
                self._stage_batch(session_id, batch)
            context.raise_if_cancelled()
        except TaskCancelled:
            self._finish_without_reconcile(
                session_id,
                root.id,
                "cancelled",
                "Scan cancelled.",
            )
            report("cancelled", "扫描已取消。")
            raise
        except Exception as error:
            self._finish_without_reconcile(session_id, root.id, "failed", str(error))
            report("failed", "扫描失败。")
            raise

        report("reconciling", "正在更新游戏库…")
        reconcile_result = self._writer.submit(
            lambda connection: reconcile_session(
                connection,
                session_id,
                root,
                "quick",
                quick_missing_game_ids=tuple(missing_game_ids),
            )
        ).result()
        summary = ScanSummary(
            session_id=session_id,
            status="completed",
            discovered=discovered,
            added=reconcile_result.added,
            updated=reconcile_result.updated,
            missing=reconcile_result.missing,
            warnings=warnings,
            move_suggestions=reconcile_result.move_suggestions,
            games=reconcile_result.games,
            checked=checked,
            cache_hits=cache_hits,
            reanalyzed=reanalyzed,
            full_analyses=full_analyses,
        )
        report(
            "completed",
            "快速核验完成。",
            added=reconcile_result.added,
            updated=reconcile_result.updated,
            missing=reconcile_result.missing,
        )
        return summary

    def confirm_move(
        self,
        session_id: str,
        existing_game_id: str,
        candidate_relative_dir: str,
    ) -> Game:
        def operation(connection: sqlite3.Connection) -> Game:
            session = connection.execute(
                "SELECT root_id, status, scope_json FROM scan_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if session is None or session["status"] != "completed":
                raise ConfirmMoveError("The referenced scan session is not complete.")
            scope = json.loads(session["scope_json"])
            expected = {
                "existingGameId": existing_game_id,
                "candidateRelativeDir": candidate_relative_dir,
            }
            if expected not in scope.get("moveCandidates", []):
                raise ConfirmMoveError("The move was not suggested by this scan session.")
            existing = connection.execute(
                "SELECT * FROM games WHERE id = ? AND status = 'missing'",
                (existing_game_id,),
            ).fetchone()
            if existing is None:
                raise ConfirmMoveError("The original game is no longer missing.")
            candidate = connection.execute(
                """
                SELECT * FROM games
                WHERE scan_root_id = ? AND relative_dir = ? AND status = 'installed'
                """,
                (session["root_id"], candidate_relative_dir),
            ).fetchone()
            if candidate is None or candidate["id"] == existing_game_id:
                raise ConfirmMoveError("The suggested target is no longer available.")

            candidate_evidence = json.loads(candidate["engine_evidence_json"])
            evidence_codes = {
                str(item.get("code"))
                for item in candidate_evidence
                if isinstance(item, dict)
            }
            detection_failed = (
                candidate["detected_engine_id"] is None
                and "detector_error" in evidence_codes
                and not any(code.startswith("candidate:") for code in evidence_codes)
            )
            connection.execute("DELETE FROM games WHERE id = ?", (candidate["id"],))
            delete_analysis_cache(connection, existing_game_id)
            now = _utc_now()
            connection.execute(
                """
                UPDATE games
                SET scan_root_id = ?, relative_dir = ?, install_path_key = ?,
                    status = 'installed', missing_since = NULL,
                    detected_title = ?, detected_version = ?,
                    detected_main_exe_relpath = ?,
                    main_exe_relpath = CASE WHEN main_exe_is_manual = 1
                        THEN main_exe_relpath ELSE ? END,
                    detected_engine_id = CASE
                        WHEN ? THEN detected_engine_id ELSE ? END,
                    detected_engine_variant = CASE
                        WHEN ? THEN detected_engine_variant ELSE ? END,
                    engine_id = CASE
                        WHEN engine_is_manual = 1 OR ? THEN engine_id ELSE ? END,
                    engine_variant = CASE
                        WHEN engine_is_manual = 1 OR ? THEN engine_variant ELSE ? END,
                    engine_confidence = CASE
                        WHEN ? THEN engine_confidence ELSE ? END,
                    engine_evidence_json = CASE
                        WHEN ? THEN engine_evidence_json ELSE ? END,
                    engine_rules_version = CASE
                        WHEN ? THEN engine_rules_version ELSE ? END,
                    exe_arch = CASE WHEN main_exe_is_manual = 1
                        THEN exe_arch ELSE ? END,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    candidate["scan_root_id"],
                    candidate["relative_dir"],
                    candidate["install_path_key"],
                    candidate["detected_title"],
                    candidate["detected_version"],
                    candidate["detected_main_exe_relpath"],
                    candidate["main_exe_relpath"],
                    detection_failed,
                    candidate["detected_engine_id"],
                    detection_failed,
                    candidate["detected_engine_variant"],
                    detection_failed,
                    candidate["detected_engine_id"],
                    detection_failed,
                    candidate["detected_engine_variant"],
                    detection_failed,
                    candidate["engine_confidence"],
                    detection_failed,
                    candidate["engine_evidence_json"],
                    detection_failed,
                    candidate["engine_rules_version"],
                    candidate["exe_arch"],
                    now,
                    existing_game_id,
                ),
            )
            row = connection.execute(
                "SELECT * FROM games WHERE id = ?", (existing_game_id,)
            ).fetchone()
            assert row is not None
            return game_from_row_with_groups(connection, row)

        return self._writer.submit(operation).result()

    def reanalyze_game(self, game_id: str, context: TaskContext) -> Game:
        game = self._repository.get_game(game_id)
        if game is None:
            raise GameReanalysisError("没有找到对应的游戏。")
        if game.status != "installed":
            raise GameReanalysisError("只有已安装游戏可以重新检测。")
        if game.scan_root_id is None or game.relative_dir is None:
            raise GameReanalysisError("游戏没有可用的安装目录。")
        root = self._repository.get_root(game.scan_root_id)
        if root is None:
            raise GameReanalysisError("游戏所属根目录已不存在。")
        try:
            game_path = expand_relative(Path(root.display_path), game.relative_dir)
        except PathTraversalError as error:
            raise GameReanalysisError("游戏安装目录不安全。") from error
        probe = _probe_directory(game_path)
        if probe.status != "present":
            raise GameReanalysisError("游戏安装目录当前不可访问。")

        candidate = DirectoryCandidate(
            path=game_path,
            relative_dir=game.relative_dir,
            depth=len(game.relative_dir.split("/")),
            reason="direct_child",
        )
        context.report(0, 1, "正在重新检测主程序和引擎…")
        analyzer_for_task = self._analyzer_for_task()

        def analyze(item: DirectoryCandidate) -> AnalyzedCandidate:
            return analyzer_for_task.analyze(item, game, None, context)

        analyzed = (
            self._analysis_pool.map_ordered((candidate,), analyze, context)[0]
            if self._analysis_pool is not None
            else analyze(candidate)
        )
        context.raise_if_cancelled()
        if analyzed.payload.get("engineDetectionFailed") is True:
            raise GameReanalysisError("引擎检测失败，已保留原有结果。")

        def operation(connection: sqlite3.Connection) -> Game:
            context.raise_if_cancelled()
            current = connection.execute(
                "SELECT * FROM games WHERE id = ? AND status = 'installed'",
                (game_id,),
            ).fetchone()
            if current is None:
                raise GameReanalysisError("游戏状态已改变，请刷新后重试。")
            if (
                current["scan_root_id"] != game.scan_root_id
                or current["relative_dir"] != game.relative_dir
                or current["install_path_key"] != game.install_path_key
            ):
                raise GameReanalysisError("游戏安装位置已改变，请重新执行检测。")
            payload = analyzed.payload
            now = _utc_now()
            connection.execute(
                """
                UPDATE games
                SET detected_main_exe_relpath = ?,
                    main_exe_relpath = CASE
                        WHEN main_exe_is_manual = 1 THEN main_exe_relpath ELSE ? END,
                    exe_arch = CASE
                        WHEN main_exe_is_manual = 1 THEN exe_arch ELSE ? END,
                    detected_engine_id = ?, detected_engine_variant = ?,
                    engine_id = CASE
                        WHEN engine_is_manual = 1 THEN engine_id ELSE ? END,
                    engine_variant = CASE
                        WHEN engine_is_manual = 1 THEN engine_variant ELSE ? END,
                    engine_confidence = ?, engine_evidence_json = json(?),
                    engine_rules_version = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    payload["mainExeRelpath"],
                    payload["mainExeRelpath"],
                    payload["exeArch"],
                    payload["detectedEngineId"],
                    payload["detectedEngineVariant"],
                    payload["detectedEngineId"],
                    payload["detectedEngineVariant"],
                    payload["engineConfidence"],
                    json.dumps(payload["engineEvidence"], ensure_ascii=False),
                    payload["engineRulesVersion"],
                    now,
                    game_id,
                ),
            )
            _replace_analysis_cache(connection, game_id, analyzed.pending_cache, now)
            row = connection.execute(
                "SELECT * FROM games WHERE id = ?", (game_id,)
            ).fetchone()
            assert row is not None
            return game_from_row_with_groups(connection, row)

        result = self._writer.submit(operation).result()
        context.report(1, 1, "重新检测完成。")
        return result

    def _analyzer_for_task(self) -> GameAnalyzer:
        if self._analyzer_override is not None:
            return self._analyzer_override
        return GameAnalyzer(self._engine_detection_provider())

    def _candidates(
        self,
        root: ScanRoot,
        scan_kind: ScanKind,
        context: TaskContext,
        on_directory: Callable[[Path, bool], None],
    ) -> Iterator[DirectoryCandidate]:
        if scan_kind == "quick" and root.scan_mode == "recursive":
            for game in self._repository.list_games():
                if game.scan_root_id != root.id or game.relative_dir is None:
                    continue
                context.raise_if_cancelled()
                path = Path(root.display_path).joinpath(*game.relative_dir.split("/"))
                accessible = path.is_dir()
                on_directory(path, accessible)
                if not accessible:
                    continue
                yield DirectoryCandidate(
                    path=path,
                    relative_dir=game.relative_dir,
                    depth=len(game.relative_dir.split("/")),
                    reason="direct_child",
                )
            return
        yield from enumerate_candidates(root, context, on_directory)

    def _owning_root_id(self, install_key: str) -> str | None:
        eligible = [
            root
            for root in self._repository.list_roots()
            if root.enabled and is_same_or_child(install_key, root.path_key)
        ]
        if not eligible:
            return None
        return max(eligible, key=lambda root: len(root.path_key)).id

    def _create_session(self, root_id: str, scan_kind: ScanKind) -> str:
        session_id = str(uuid4())
        started_at = _utc_now()
        scope = json.dumps({"scanKind": scan_kind}, separators=(",", ":"))
        self._writer.submit(
            lambda connection: connection.execute(
                """
                INSERT INTO scan_sessions(id, root_id, kind, status, started_at, scope_json)
                VALUES (?, ?, 'library', 'running', ?, ?)
                """,
                (session_id, root_id, started_at, scope),
            ).rowcount
        ).result()
        return session_id

    def _stage_batch(self, session_id: str, batch: list[tuple[str, str]]) -> None:
        staged = tuple(batch)

        def operation(connection: sqlite3.Connection) -> None:
            connection.executemany(
                """
                INSERT INTO scan_observations(session_id, install_path_key, payload_json)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id, install_path_key)
                DO UPDATE SET payload_json = excluded.payload_json
                """,
                ((session_id, path_key, payload) for path_key, payload in staged),
            )

        self._writer.submit(operation).result()

    def _finish_without_reconcile(
        self,
        session_id: str,
        root_id: str,
        status: ScanStatus,
        error_summary: str,
    ) -> None:
        finished_at = _utc_now()

        def operation(connection: sqlite3.Connection) -> None:
            connection.execute(
                "DELETE FROM scan_observations WHERE session_id = ?", (session_id,)
            )
            connection.execute(
                """
                UPDATE scan_sessions
                SET status = ?, finished_at = ?, error_summary = ?
                WHERE id = ?
                """,
                (status, finished_at, error_summary, session_id),
            )
            connection.execute(
                """
                UPDATE scan_roots
                SET last_scan_status = ?, last_error = ?
                WHERE id = ?
                """,
                (status, error_summary, root_id),
            )

        self._writer.submit(operation).result()


def _empty_summary(
    session_id: str, status: ScanStatus, discovered: int
) -> ScanSummary:
    return ScanSummary(session_id, status, discovered, 0, 0, 0, 0, ())


def _probe_directory(path: Path) -> PathProbe:
    try:
        info = path.stat(follow_symlinks=False)
    except (FileNotFoundError, NotADirectoryError):
        return PathProbe("missing")
    except OSError as error:
        return PathProbe("unknown", f"{type(error).__name__}: {error}")
    if not stat.S_ISDIR(info.st_mode):
        return PathProbe("missing")
    return PathProbe("present")


def _pending_cache_payload(result: AnalyzedCandidate) -> dict[str, object] | None:
    pending = result.pending_cache
    if pending is None:
        return None
    return {
        "executableRelpath": pending.executable_relpath,
        "fileSize": pending.file_size,
        "modifiedTimeNs": pending.modified_time_ns,
        "rankerRulesVersion": pending.ranker_rules_version,
        "engineRulesVersion": pending.engine_rules_version,
    }


def _replace_analysis_cache(
    connection: sqlite3.Connection,
    game_id: str,
    pending: PendingAnalysisCache | None,
    analyzed_at: str,
) -> None:
    if pending is None:
        delete_analysis_cache(connection, game_id)
    else:
        upsert_analysis_cache(connection, game_id, pending, analyzed_at)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class ConfirmMoveError(ValueError):
    """Raised when a move suggestion is stale or cannot be verified."""


class GameReanalysisError(ValueError):
    """Raised when a game cannot be safely reanalyzed."""
