from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType

import pytest

from gamesave_scout.bridge.tasks import TaskCancelled
from gamesave_scout.saves.batch_models import RawBatchCandidate
from gamesave_scout.saves.batch_rules import BatchRuleCatalog
from gamesave_scout.saves.batch_scanner import (
    BatchScanCancelled,
    BatchScanOutput,
    BatchScopeResult,
)
from gamesave_scout.saves.batch_service import (
    BatchSaveDiscoveryService,
    BatchScanRequest,
)


@dataclass
class _Context:
    reports: list[tuple[int, int | None, str, dict[str, object]]] = field(default_factory=list)

    def raise_if_cancelled(self) -> None:
        return None

    def report(
        self,
        completed: int,
        total: int | None,
        message: str,
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        self.reports.append((completed, total, message, details or {}))


@dataclass
class _Rules:
    catalog: BatchRuleCatalog

    def collect(self, _context: object) -> BatchRuleCatalog:
        return self.catalog


@dataclass
class _Scopes:
    scopes: tuple[object, ...] = ()

    def build(self, _standard: object, _custom: object) -> tuple[object, ...]:
        return self.scopes


@dataclass
class _Scanner:
    output: BatchScanOutput | None = None
    cancellation: BatchScanCancelled | None = None
    error: Exception | None = None

    def scan(self, _scopes: object, _catalog: object, _context: object) -> BatchScanOutput:
        if self.error is not None:
            raise self.error
        if self.cancellation is not None:
            raise self.cancellation
        assert self.output is not None
        return self.output


@dataclass
class _Library:
    def list_games(self) -> tuple[object, ...]:
        return ()


@dataclass
class _Locations:
    def list_all(self) -> tuple[object, ...]:
        return ()


@dataclass
class _Repository:
    finishes: list[tuple[str, str]] = field(default_factory=list)
    recorded: list[tuple[object, ...]] = field(default_factory=list)
    rules_version: str | None = None

    def start_session(self, _request: object, _rules_version: str) -> str:
        return "session-1"

    def update_rules_version(self, _session_id: str, rules_version: str) -> None:
        self.rules_version = rules_version

    def record_candidates(
        self,
        _session_id: str,
        _scope_results: object,
        candidates: tuple[object, ...],
    ) -> tuple[str, ...]:
        self.recorded.append(candidates)
        return tuple(f"candidate-{index}" for index, _ in enumerate(candidates))

    def finish_session(self, session_id: str, *, status: str, **_kwargs: object) -> int:
        self.finishes.append((session_id, status))
        return 0

    def session_counts(self, _session_id: str) -> dict[str, int]:
        count = len(self.recorded[-1]) if self.recorded else 0
        return {
            "new": count,
            "pending": count,
            "recorded": 0,
            "ignored": 0,
            "unavailable": 0,
        }


def test_batch_service_completes_empty_scan_with_explicit_progress() -> None:
    repository = _Repository()
    context = _Context()
    service = _service(
        repository,
        _Scanner(output=_output("completed")),
    )

    summary = service.run(BatchScanRequest(("documents",), ()), context)

    assert summary.status == "completed"
    assert summary.new_count == 0
    assert repository.rules_version == "rules-v1"
    assert repository.finishes == [("session-1", "completed")]
    assert context.reports[-1][:3] == (1, 1, "未发现存档候选")


def test_batch_service_persists_partial_output_before_user_cancellation() -> None:
    repository = _Repository()
    output = _output("cancelled", candidates=(_raw_candidate(),))
    service = _service(
        repository,
        _Scanner(cancellation=BatchScanCancelled(output, "user")),
    )

    with pytest.raises(TaskCancelled) as captured:
        service.run(BatchScanRequest(("documents",), ()), _Context())

    assert captured.value.reason == "user"
    assert len(repository.recorded[0]) == 1
    assert repository.finishes == [("session-1", "cancelled")]


def test_batch_service_marks_all_unavailable_empty_scan_as_unavailable() -> None:
    repository = _Repository()
    service = _service(repository, _Scanner(output=_output("unavailable")))

    summary = service.run(BatchScanRequest(("documents",), ()), _Context())

    assert summary.status == "unavailable"
    assert summary.inaccessible_scope_count == 1
    assert repository.finishes == [("session-1", "unavailable")]


def test_batch_service_marks_failure_without_hiding_original_error() -> None:
    repository = _Repository()
    service = _service(repository, _Scanner(error=RuntimeError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        service.run(BatchScanRequest(("documents",), ()), _Context())

    assert repository.finishes == [("session-1", "failed")]


def _service(
    repository: _Repository,
    scanner: _Scanner,
) -> BatchSaveDiscoveryService:
    return BatchSaveDiscoveryService(
        repository=repository,  # type: ignore[arg-type]
        rule_provider=_Rules(_catalog()),  # type: ignore[arg-type]
        scope_builder=_Scopes(),  # type: ignore[arg-type]
        scanner=scanner,  # type: ignore[arg-type]
        library=_Library(),  # type: ignore[arg-type]
        save_repository=_Locations(),  # type: ignore[arg-type]
    )


def _catalog() -> BatchRuleCatalog:
    return BatchRuleCatalog(
        candidates=(),
        identities_by_path=MappingProxyType({}),
        reverse_path_rules=(),
        warnings=(),
        rules_version="rules-v1",
    )


def _output(
    status: str,
    *,
    candidates: tuple[RawBatchCandidate, ...] = (),
) -> BatchScanOutput:
    return BatchScanOutput(
        scope_results=(
            BatchScopeResult(
                scope_key="documents",
                status=status,  # type: ignore[arg-type]
                entries=10,
                candidate_count=len(candidates),
                truncated=False,
                error=None,
            ),
        ),
        candidates=candidates,
        total_entries=10,
        elapsed_seconds=0.25,
    )


def _raw_candidate() -> RawBatchCandidate:
    return RawBatchCandidate(
        scope_key="documents",
        kind="directory",
        path_template=r"<winDocuments>\Alice\SaveData",
        display_path=r"D:\Documents\Alice\SaveData",
        path_key=r"d:\documents\alice\savedata",
        sources=("bounded_scan",),
        evidence=("测试",),
        representative_files=(),
        matched_file_count=0,
        representatives_truncated=False,
    )
