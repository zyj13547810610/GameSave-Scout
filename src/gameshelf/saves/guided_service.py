"""Thread-safe orchestration for one active guided save detection session."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock, Timer
from time import time_ns
from typing import Literal, Protocol
from uuid import uuid4

from gameshelf.library.launcher import LaunchReceipt
from gameshelf.saves.guided_events import GuidedChangeAggregator, RawFileChange
from gameshelf.saves.guided_models import (
    GuidedSavePreview,
    GuidedSaveSession,
    GuidedScopeOption,
)
from gameshelf.saves.guided_registry import (
    RegistryMetadataReader,
    RegistrySnapshot,
    diff_registry_snapshots,
)
from gameshelf.saves.guided_repository import GuidedSaveRepository
from gameshelf.saves.guided_scanner import BoundedMetadataScanner, MetadataScanResult
from gameshelf.saves.guided_scoring import (
    GuidedScoringContext,
    score_guided_changes_with_summary,
)
from gameshelf.scanning.path_keys import windows_path_key


class GuidedSaveError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class CancelHandle(Protocol):
    def cancel(self) -> None: ...


class StopHandle(Protocol):
    def stop(self) -> None: ...


class Scheduler(Protocol):
    def call_later(self, delay: float, callback: Callable[[], None]) -> CancelHandle: ...


class ScopeBuilder(Protocol):
    def preview(self, game_id: str) -> GuidedSavePreview: ...

    def resolve_selected(
        self,
        game_id: str,
        selected_scope_ids: Sequence[str],
        additional_directories: Sequence[str],
    ) -> tuple[GuidedScopeOption, ...]: ...


class DirectoryWatcher(Protocol):
    def start(self, root: Path, sink: object) -> StopHandle: ...


class GameLauncher(Protocol):
    def launch(self, game_id: str) -> LaunchReceipt: ...


class ProcessTracker(Protocol):
    def start(self, root_pid: int, sink: object) -> StopHandle: ...


type ScoringContextFactory = Callable[
    [str, tuple[GuidedScopeOption, ...], tuple[str, ...], tuple[str, ...]],
    GuidedScoringContext,
]
type AnalysisSubmitter = Callable[[Callable[[], None]], object]
type CloseResolution = Literal["return", "cancel_and_exit", "analyze_and_exit"]


@dataclass(slots=True)
class _ActiveRuntime:
    session_id: str
    game_id: str
    started_monotonic_ns: int
    started_wall_time_ns: int
    approved_scopes: tuple[GuidedScopeOption, ...]
    registry_keys: tuple[str, ...]
    registry_before: RegistrySnapshot
    aggregator: GuidedChangeAggregator
    watch_handles: list[StopHandle]
    process_handle: StopHandle | None = None
    duration_timer: CancelHandle | None = None
    settle_timer: CancelHandle | None = None
    save_mark_monotonic_ns: int | None = None
    analysis_started: bool = False


class _ThreadingScheduler:
    def call_later(self, delay: float, callback: Callable[[], None]) -> Timer:
        timer = Timer(delay, callback)
        timer.daemon = True
        timer.start()
        return timer


class _DirectorySink:
    def __init__(self, aggregator: GuidedChangeAggregator) -> None:
        self._aggregator = aggregator

    def on_change(self, change: RawFileChange) -> None:
        self._aggregator.record(change)

    def on_overflow(self, root: Path) -> None:
        self._aggregator.mark_overflow(root)

    def on_failure(self, root: Path, _code: str) -> None:
        self._aggregator.mark_failure(root)


class _ProcessSink:
    def __init__(self, service: GuidedSaveSessionService, session_id: str) -> None:
        self._service = service
        self._session_id = session_id

    def on_tree_exit(self) -> None:
        self._service._process_tree_exited(self._session_id)

    def on_tracking_degraded(self, _reason: str) -> None:
        self._service._process_tracking_degraded(self._session_id)


class GuidedSaveSessionService:
    def __init__(
        self,
        *,
        repository: GuidedSaveRepository,
        scope_builder: ScopeBuilder,
        registry_reader: RegistryMetadataReader,
        watcher: DirectoryWatcher,
        launcher: GameLauncher,
        process_tracker: ProcessTracker,
        scanner: BoundedMetadataScanner,
        scoring_context_factory: ScoringContextFactory,
        scheduler: Scheduler | None = None,
        utc_now: Callable[[], str] | None = None,
        monotonic_ns: Callable[[], int],
        wall_time_ns: Callable[[], int] = time_ns,
        submit_analysis: AnalysisSubmitter | None = None,
        exit_callback: Callable[[], None] | None = None,
    ) -> None:
        self._repository = repository
        self._scope_builder = scope_builder
        self._registry_reader = registry_reader
        self._watcher = watcher
        self._launcher = launcher
        self._process_tracker = process_tracker
        self._scanner = scanner
        self._scoring_context_factory = scoring_context_factory
        self._scheduler = scheduler or _ThreadingScheduler()
        self._utc_now = utc_now or _utc_now
        self._monotonic_ns = monotonic_ns
        self._wall_time_ns = wall_time_ns
        self._executor = (
            None
            if submit_analysis is not None
            else ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="gameshelf-guided-save"
            )
        )
        self._submit_analysis = submit_analysis or self._submit_to_executor
        self._exit_callback = exit_callback or (lambda: None)
        self._lock = RLock()
        self._active: _ActiveRuntime | None = None
        self._close_requested = False
        self._exit_after_analysis = False
        self._closed = False

    @property
    def close_requested(self) -> bool:
        with self._lock:
            return self._close_requested

    def preview(self, game_id: str) -> GuidedSavePreview:
        return self._scope_builder.preview(game_id)

    def set_exit_callback(self, callback: Callable[[], None]) -> None:
        with self._lock:
            self._exit_callback = callback

    def start(
        self,
        game_id: str,
        selected_scope_ids: Sequence[str],
        additional_directories: Sequence[str],
    ) -> GuidedSaveSession:
        with self._lock:
            if self._closed:
                raise GuidedSaveError("guided_service_closed", "引导式寻找服务已经关闭。")
            if self._active is not None:
                raise GuidedSaveError("guided_session_active", "已有游戏正在引导式寻找存档。")
            preview = self._scope_builder.preview(game_id)
            scopes = self._scope_builder.resolve_selected(
                game_id, selected_scope_ids, additional_directories
            )
            if not scopes:
                raise GuidedSaveError("guided_scope_empty", "至少选择一个监控范围。")
            session_id = str(uuid4())
            unavailable = tuple(
                scope.label for scope in preview.scopes if not scope.available
            )
            self._repository.create_session(
                session_id, game_id, self._utc_now(), scopes, unavailable
            )
            runtime: _ActiveRuntime | None = None
            try:
                registry_keys = tuple(target.key for target in preview.registry_targets)
                runtime = _ActiveRuntime(
                    session_id=session_id,
                    game_id=game_id,
                    started_monotonic_ns=self._monotonic_ns(),
                    started_wall_time_ns=self._wall_time_ns(),
                    approved_scopes=scopes,
                    registry_keys=registry_keys,
                    registry_before=self._registry_reader.snapshot(registry_keys),
                    aggregator=GuidedChangeAggregator(),
                    watch_handles=[],
                )
                self._active = runtime
                sink = _DirectorySink(runtime.aggregator)
                for scope in scopes:
                    runtime.watch_handles.append(
                        self._watcher.start(Path(scope.display_path), sink)
                    )
                receipt = self._launcher.launch(game_id)
                monitoring = self._repository.set_monitoring(
                    session_id,
                    self._utc_now(),
                    root_pid=receipt.pid,
                )
                runtime.process_handle = self._process_tracker.start(
                    receipt.pid, _ProcessSink(self, session_id)
                )
                runtime.duration_timer = self._scheduler.call_later(
                    1800.0, lambda: self._duration_expired(session_id)
                )
                return monitoring
            except Exception as error:
                if runtime is not None:
                    self._cleanup_runtime(runtime)
                self._repository.fail(
                    session_id,
                    self._utc_now(),
                    "guided_start_failed",
                    "引导式寻找启动失败。",
                )
                self._active = None
                raise GuidedSaveError(
                    "guided_start_failed", "引导式寻找启动失败。"
                ) from error

    def current(self) -> GuidedSaveSession | None:
        with self._lock:
            active = self._active
        if active is not None:
            return self._repository.get_session(active.session_id)
        return self._repository.latest_reviewable()

    def status(self, session_id: str) -> GuidedSaveSession:
        session = self._repository.get_session(session_id)
        if session is None:
            raise GuidedSaveError("guided_session_not_found", "找不到引导式寻找会话。")
        return session

    def latest_for_game(self, game_id: str) -> GuidedSaveSession | None:
        return self._repository.latest_reviewable(game_id)

    def mark_saved(self, session_id: str) -> GuidedSaveSession:
        with self._lock:
            runtime = self._require_active(session_id)
            if runtime.save_mark_monotonic_ns is not None:
                return self.status(session_id)
            runtime.save_mark_monotonic_ns = self._monotonic_ns()
            settling = self._repository.mark_settling(session_id, self._utc_now())
            runtime.settle_timer = self._scheduler.call_later(
                3.0, lambda: self._begin_analysis(session_id)
            )
            return settling

    def stop_and_analyze(self, session_id: str) -> GuidedSaveSession:
        self._begin_analysis(session_id)
        return self.status(session_id)

    def cancel(self, session_id: str) -> GuidedSaveSession:
        with self._lock:
            runtime = self._require_active(session_id)
            self._cleanup_runtime(runtime)
            cancelled = self._repository.cancel(session_id, self._utc_now())
            self._active = None
            self._close_requested = False
            return cancelled

    def request_close(self) -> bool:
        with self._lock:
            if self._active is None:
                return True
            self._close_requested = True
            return False

    def resolve_close(self, resolution: CloseResolution) -> None:
        with self._lock:
            runtime = self._active
            if resolution == "return":
                self._close_requested = False
                return
            if runtime is None:
                self._close_requested = False
                self._exit_callback()
                return
            if resolution == "cancel_and_exit":
                self.cancel(runtime.session_id)
                self._exit_callback()
                return
            if resolution == "analyze_and_exit":
                self._exit_after_analysis = True
                self._begin_analysis(runtime.session_id)
                return
            raise GuidedSaveError("invalid_close_resolution", "未知的关闭处理方式。")

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            runtime = self._active
            if runtime is not None:
                self._cleanup_runtime(runtime)
                self._repository.recover_interrupted(self._utc_now())
                self._active = None
        if self._executor is not None:
            self._executor.shutdown(wait=True, cancel_futures=True)

    def recover_interrupted(self) -> int:
        return self._repository.recover_interrupted(self._utc_now())

    def _duration_expired(self, session_id: str) -> None:
        try:
            self._begin_analysis(session_id)
        except GuidedSaveError:
            return

    def _process_tree_exited(self, session_id: str) -> None:
        try:
            self._begin_analysis(session_id)
        except GuidedSaveError:
            return

    def _process_tracking_degraded(self, session_id: str) -> None:
        with self._lock:
            if self._active is None or self._active.session_id != session_id:
                return
            self._repository.set_process_tracking_degraded(session_id)

    def _begin_analysis(self, session_id: str) -> None:
        with self._lock:
            runtime = self._require_active(session_id)
            if runtime.analysis_started:
                return
            if runtime.save_mark_monotonic_ns is None:
                self._repository.begin_settling(session_id)
            runtime.analysis_started = True
            if runtime.duration_timer is not None:
                runtime.duration_timer.cancel()
            if runtime.settle_timer is not None:
                runtime.settle_timer.cancel()
            self._submit_analysis(lambda: self._analyze(runtime))

    def _analyze(self, runtime: _ActiveRuntime) -> None:
        try:
            self._stop_handles(runtime)
            after = self._registry_reader.snapshot(runtime.registry_keys)
            registry_drafts = diff_registry_snapshots(runtime.registry_before, after)
            snapshot = runtime.aggregator.snapshot()
            scanned: list[MetadataScanResult] = []
            incomplete_roots = dict.fromkeys(snapshot.failed_roots)
            for root_text in (*snapshot.overflowed_roots, *snapshot.failed_roots):
                try:
                    result = self._scanner.scan(
                        Path(root_text),
                        started_ns=runtime.started_wall_time_ns,
                        finished_ns=self._wall_time_ns(),
                    )
                except (OSError, ValueError):
                    continue
                scanned.append(result)
                if result.truncated_by is not None:
                    incomplete_roots.setdefault(root_text, None)
            truncated_roots = tuple(incomplete_roots)
            overflow_keys = tuple(
                windows_path_key(root) for root in snapshot.overflowed_roots
            )
            truncated_keys = tuple(windows_path_key(root) for root in truncated_roots)
            context = self._scoring_context_factory(
                runtime.game_id,
                runtime.approved_scopes,
                overflow_keys,
                truncated_keys,
            ).with_evidence(
                wall_time_offset_ns=(
                    runtime.started_wall_time_ns - runtime.started_monotonic_ns
                )
            )
            scoring = score_guided_changes_with_summary(
                changes=snapshot.changes,
                scanned_files=tuple(file for result in scanned for file in result.files),
                save_mark_ns=runtime.save_mark_monotonic_ns,
                context=context,
            )
            discoveries = tuple(
                sorted(
                    (*scoring.discoveries, *registry_drafts),
                    key=lambda item: (-item.confidence, item.path_key),
                )[:200]
            )
            summary = {
                "candidateCount": len(discoveries),
                "eventCount": snapshot.event_count,
                "droppedEventCount": snapshot.dropped_event_count,
                **scoring.filtered_counts,
            }
            self._repository.complete(
                runtime.session_id,
                self._utc_now(),
                discoveries,
                overflowed_scopes=snapshot.overflowed_roots,
                truncated_scopes=truncated_roots,
                result_summary=summary,
            )
        except Exception:
            self._repository.fail(
                runtime.session_id,
                self._utc_now(),
                "guided_analysis_failed",
                "引导式寻找分析失败。",
            )
        finally:
            with self._lock:
                if self._active is runtime:
                    self._active = None
                should_exit = self._exit_after_analysis
                self._exit_after_analysis = False
                self._close_requested = False
            if should_exit:
                self._exit_callback()

    def _require_active(self, session_id: str) -> _ActiveRuntime:
        runtime = self._active
        if runtime is None or runtime.session_id != session_id:
            raise GuidedSaveError("guided_session_not_active", "引导式寻找会话不再活动。")
        return runtime

    def _cleanup_runtime(self, runtime: _ActiveRuntime) -> None:
        if runtime.duration_timer is not None:
            runtime.duration_timer.cancel()
        if runtime.settle_timer is not None:
            runtime.settle_timer.cancel()
        self._stop_handles(runtime)

    @staticmethod
    def _stop_handles(runtime: _ActiveRuntime) -> None:
        if runtime.process_handle is not None:
            runtime.process_handle.stop()
            runtime.process_handle = None
        for handle in reversed(runtime.watch_handles):
            handle.stop()
        runtime.watch_handles.clear()

    def _submit_to_executor(self, operation: Callable[[], None]) -> object:
        assert self._executor is not None
        return self._executor.submit(operation)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
