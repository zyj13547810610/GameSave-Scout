"""Coordinate one explicit two-phase batch save discovery run."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from gamesave_scout.bridge.tasks import TaskCancelled, TaskContext
from gamesave_scout.library.models import Game
from gamesave_scout.saves.batch_matching import (
    BatchCandidateMatcher,
    group_matched_candidates,
)
from gamesave_scout.saves.batch_models import (
    BatchScanScope,
    BatchScanSessionStatus,
    BatchScanSummary,
    MatchedBatchCandidate,
)
from gamesave_scout.saves.batch_rules import (
    BatchRuleCatalog,
    BatchRuleContext,
)
from gamesave_scout.saves.batch_scanner import (
    BatchFilesystemScanner,
    BatchScanCancelled,
    BatchScanOutput,
    BatchScopeResult,
)
from gamesave_scout.saves.models import SaveLocation

_ROOT_TOKEN_BY_SCOPE = {
    "documents": "<winDocuments>",
    "saved_games": "<winSavedGames>",
    "app_data": "<winAppData>",
    "local_app_data": "<winLocalAppData>",
    "local_app_data_low": "<winLocalAppDataLow>",
}


@dataclass(frozen=True, slots=True)
class BatchScanRequest:
    standard_scope_ids: tuple[str, ...]
    custom_root_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if any(scope_id not in _ROOT_TOKEN_BY_SCOPE for scope_id in self.standard_scope_ids):
            raise ValueError("批量存档扫描包含未知的标准范围。")
        if any(
            not isinstance(root_id, str) or not root_id or "\x00" in root_id
            for root_id in self.custom_root_ids
        ):
            raise ValueError("批量存档扫描包含无效的自定义目录 ID。")
        if len(set(self.standard_scope_ids)) != len(self.standard_scope_ids) or len(
            set(self.custom_root_ids)
        ) != len(self.custom_root_ids):
            raise ValueError("批量存档扫描范围不能重复。")


class BatchRuleCollector(Protocol):
    def collect(self, context: BatchRuleContext) -> BatchRuleCatalog: ...


class BatchScopeResolver(Protocol):
    def build(
        self,
        standard_scope_ids: Sequence[str],
        custom_root_ids: Sequence[str],
    ) -> tuple[BatchScanScope, ...]: ...


class BatchLibraryReader(Protocol):
    def list_games(self) -> tuple[Game, ...]: ...


class BatchLocationReader(Protocol):
    def list_all(self) -> tuple[SaveLocation, ...]: ...


class BatchPersistence(Protocol):
    def start_session(self, request: BatchScanRequest, rules_version: str) -> str: ...

    def update_rules_version(self, session_id: str, rules_version: str) -> None: ...

    def record_candidates(
        self,
        session_id: str,
        scope_results: Sequence[BatchScopeResult],
        candidates: Sequence[MatchedBatchCandidate],
    ) -> tuple[str, ...]: ...

    def finish_session(
        self,
        session_id: str,
        *,
        status: BatchScanSessionStatus,
        scope_results: Sequence[BatchScopeResult] = (),
        counts: Mapping[str, int] | None = None,
        error_summary: str | None = None,
    ) -> int: ...

    def session_counts(self, session_id: str) -> dict[str, int]: ...


class BatchSaveDiscoveryService:
    def __init__(
        self,
        *,
        repository: BatchPersistence,
        rule_provider: BatchRuleCollector,
        scope_builder: BatchScopeResolver,
        scanner: BatchFilesystemScanner,
        library: BatchLibraryReader,
        save_repository: BatchLocationReader,
    ) -> None:
        self._repository = repository
        self._rule_provider = rule_provider
        self._scope_builder = scope_builder
        self._scanner = scanner
        self._library = library
        self._save_repository = save_repository

    def run(
        self,
        request: BatchScanRequest,
        context: TaskContext,
    ) -> BatchScanSummary:
        session_id = self._repository.start_session(request, "pending")
        try:
            context.raise_if_cancelled()
            context.report(
                0,
                3,
                "正在加载存档规则",
                details={"phase": "rules"},
            )
            catalog = self._rule_provider.collect(
                BatchRuleContext(
                    root_tokens=tuple(
                        _ROOT_TOKEN_BY_SCOPE[scope_id] for scope_id in request.standard_scope_ids
                    )
                )
            )
            self._repository.update_rules_version(session_id, catalog.rules_version)
            context.raise_if_cancelled()
            context.report(
                1,
                3,
                "存档规则加载完成，正在扫描所选范围",
                details={
                    "phase": "filesystem",
                    "warningCount": len(catalog.warnings),
                },
            )
            scopes = self._scope_builder.build(
                request.standard_scope_ids,
                request.custom_root_ids,
            )
            output = self._scanner.scan(scopes, catalog, context)
            return self._complete(session_id, catalog, output, context)
        except BatchScanCancelled as cancellation:
            self._persist_output(session_id, catalog, cancellation.output)
            counts = self._repository.session_counts(session_id)
            status: BatchScanSessionStatus = (
                "cancelled" if cancellation.reason == "user" else "interrupted"
            )
            self._repository.finish_session(
                session_id,
                status=status,
                counts=counts,
            )
            raise TaskCancelled(cancellation.reason) from cancellation
        except TaskCancelled as cancellation:
            status = "cancelled" if cancellation.reason == "user" else "interrupted"
            self._repository.finish_session(session_id, status=status)
            raise
        except Exception as error:
            self._repository.finish_session(
                session_id,
                status="failed",
                error_summary=str(error)[:500],
            )
            raise

    def _complete(
        self,
        session_id: str,
        catalog: BatchRuleCatalog,
        output: BatchScanOutput,
        context: TaskContext,
    ) -> BatchScanSummary:
        matched = self._persist_output(session_id, catalog, output)
        all_selected_unavailable = bool(output.scope_results) and all(
            result.status == "unavailable" for result in output.scope_results
        )
        status: BatchScanSessionStatus = (
            "unavailable" if all_selected_unavailable and not matched else "completed"
        )
        counts = self._repository.session_counts(session_id)
        unavailable_marked = self._repository.finish_session(
            session_id,
            status=status,
            counts=counts,
        )
        if matched:
            context.report(
                1,
                1,
                f"发现 {len(matched)} 个存档候选",
                details={"phase": "completed", "candidateCount": len(matched)},
            )
        else:
            context.report(
                1,
                1,
                "未发现存档候选",
                details={"phase": "completed", "candidateCount": 0},
            )
        return BatchScanSummary(
            session_id=session_id,
            status=status,
            new_count=counts.get("new", 0),
            pending_count=counts.get("pending", 0),
            recorded_count=counts.get("recorded", 0),
            ignored_count=counts.get("ignored", 0),
            unavailable_count=counts.get("unavailable", 0) + unavailable_marked,
            group_count=len(group_matched_candidates(matched)),
            inaccessible_scope_count=sum(
                result.status == "unavailable" for result in output.scope_results
            ),
            truncated_scope_count=sum(result.truncated for result in output.scope_results),
            total_entries=output.total_entries,
            elapsed_seconds=output.elapsed_seconds,
        )

    def _persist_output(
        self,
        session_id: str,
        catalog: BatchRuleCatalog,
        output: BatchScanOutput,
    ) -> tuple[MatchedBatchCandidate, ...]:
        matcher = BatchCandidateMatcher(
            games=self._library.list_games(),
            save_locations=self._save_repository.list_all(),
            catalog=catalog,
        )
        matched = matcher.match_all(output.candidates)
        self._repository.record_candidates(
            session_id,
            output.scope_results,
            matched,
        )
        return matched
