from dataclasses import replace
from pathlib import Path
from threading import Event

from gamesave_scout.bootstrap.config import ConfigService, JsonConfigStore
from gamesave_scout.bootstrap.paths import AppPaths
from gamesave_scout.bridge.api import BridgeApi
from gamesave_scout.bridge.tasks import TaskRegistry
from gamesave_scout.saves.batch_external import BatchExternalLookupError
from gamesave_scout.saves.batch_models import (
    BatchScanSummary,
    CandidateAlternative,
    RepresentativeFile,
)
from gamesave_scout.saves.batch_repository import (
    BatchCandidatePage,
    BatchCandidateQuery,
    PersistedBatchCandidate,
)
from gamesave_scout.saves.batch_review import BatchAcceptResult
from gamesave_scout.saves.batch_service import BatchScanRequest


class FakeBatchRepository:
    def __init__(self) -> None:
        self.candidate = _candidate()
        self.queries: list[BatchCandidateQuery] = []

    def list_candidates(self, query: BatchCandidateQuery) -> BatchCandidatePage:
        self.queries.append(query)
        return BatchCandidatePage((self.candidate,), 1)

    def get_candidate(self, candidate_id: str) -> PersistedBatchCandidate | None:
        return self.candidate if candidate_id == self.candidate.id else None

    def selectable_ids(self, query: BatchCandidateQuery, *, limit: int = 500) -> tuple[str, ...]:
        self.queries.append(query)
        return (self.candidate.id,)[:limit]


class FakeBatchDiscovery:
    def __init__(self) -> None:
        self.requests: list[BatchScanRequest] = []

    def run(self, request: BatchScanRequest, context) -> BatchScanSummary:
        self.requests.append(request)
        context.report(1, 1, "完成")
        return BatchScanSummary(
            session_id="session-1",
            status="completed",
            new_count=1,
            pending_count=1,
            recorded_count=0,
            ignored_count=0,
            unavailable_count=0,
            group_count=1,
            inaccessible_scope_count=0,
            truncated_scope_count=0,
            total_entries=12,
            elapsed_seconds=0.5,
        )


class FakeBatchReview:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def accept(self, ids, *, confirm_registry: bool) -> BatchAcceptResult:
        self.calls.append(("accept", tuple(ids), confirm_registry))
        return BatchAcceptResult((), 0, 1)

    def reassociate_many(self, ids, game_id: str) -> int:
        self.calls.append(("reassociate", tuple(ids), game_id))
        return len(ids)

    def ignore(self, ids) -> int:
        self.calls.append(("ignore", tuple(ids)))
        return len(ids)

    def restore(self, ids) -> int:
        self.calls.append(("restore", tuple(ids)))
        return len(ids)

    def clear_unavailable(self, ids) -> int:
        self.calls.append(("clear", tuple(ids)))
        return len(ids)


class FakeExternalLookup:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def open(self, candidate_id: str, provider: str) -> str:
        self.calls.append((candidate_id, provider))
        if provider == "bad":
            raise BatchExternalLookupError("batch_lookup_provider_invalid", "无效来源")
        return "https://vndb.org/v?q=Alice"


class FakeCandidateOpener:
    def __init__(self) -> None:
        self.ids: list[str] = []

    def open(self, candidate_id: str) -> None:
        self.ids.append(candidate_id)


class FakeWindow:
    def create_file_dialog(self, _dialog_type: object, **_options: object) -> tuple[str]:
        return (r"C:\Save Archive",)


def test_batch_candidate_page_uses_complete_camel_case_dto(tmp_path: Path) -> None:
    api, tasks, _, repository, _, _, _ = _api(tmp_path)
    try:
        result = api.list_batch_save_candidates(
            {
                "status": "pending",
                "keyword": "Alice",
                "confidence": "high",
                "source": "ludusavi",
                "offset": 0,
                "limit": 20,
            }
        )
    finally:
        tasks.close()

    assert result["ok"] is True
    assert result["data"]["total"] == 1
    assert result["data"]["items"][0] == {
        "id": "candidate-1",
        "scopeKey": "documents",
        "kind": "directory",
        "displayPath": r"C:\Users\Alice\Documents\Alice",
        "availability": "available",
        "classification": "installed",
        "confidence": "high",
        "suggestedGameId": "game-1",
        "suggestedTitle": "Alice",
        "externalProductId": "RJ123456",
        "engineId": "unity",
        "strongGroupKey": "product:rj123456",
        "reviewGameId": None,
        "reviewStatus": "pending",
        "saveLocationId": None,
        "sources": ["ludusavi"],
        "evidence": ["Ludusavi 精确规则"],
        "representativeFiles": [
            {"name": "slot1.sav", "size": 42, "modifiedTimeNs": 100}
        ],
        "matchedFileCount": 1,
        "representativesTruncated": False,
        "alternatives": [
            {"title": "Alice 2", "reason": "标题相近", "gameId": "game-2"}
        ],
        "lookupQuery": "RJ123456",
        "firstSeenAt": "2026-08-19T00:00:00+00:00",
        "lastSeenAt": "2026-08-19T01:00:00+00:00",
    }
    assert repository.queries[0].limit == 20


def test_historical_custom_source_is_displayed_as_legacy_only(tmp_path: Path) -> None:
    api, tasks, _, repository, _, _, _ = _api(tmp_path)
    repository.candidate = replace(
        repository.candidate,
        sources=("custom",),  # type: ignore[arg-type]
    )
    try:
        result = api.list_batch_save_candidates({"offset": 0, "limit": 20})
    finally:
        tasks.close()

    assert result["ok"] is True
    assert result["data"]["items"][0]["sources"] == ["旧自定义清单"]


def test_batch_candidate_query_rejects_extra_fields_and_unsafe_page_size(
    tmp_path: Path,
) -> None:
    api, tasks, *_ = _api(tmp_path)
    try:
        too_small = api.list_batch_save_candidates({"offset": 0, "limit": 19})
        extra = api.get_batch_save_candidate({"candidateId": "candidate-1", "url": "x"})
    finally:
        tasks.close()

    assert too_small["error"]["code"] == "invalid_request"
    assert extra["error"]["code"] == "invalid_request"


def test_batch_custom_root_commands_persist_and_picker_is_explicit(tmp_path: Path) -> None:
    api, tasks, config, *_ = _api(tmp_path)
    api.attach_window(FakeWindow())
    try:
        chosen = api.choose_batch_save_custom_root()
        added = api.add_batch_save_custom_root(
            {"displayPath": chosen["data"], "enabled": True, "maxDepth": 4}
        )
        updated = api.update_batch_save_custom_root(
            {"rootId": added["data"]["id"], "enabled": False, "maxDepth": 6}
        )
        removed = api.remove_batch_save_custom_root({"rootId": added["data"]["id"]})
    finally:
        tasks.close()

    assert chosen == {"ok": True, "data": r"C:\Save Archive"}
    assert added["data"]["displayPath"] == r"C:\Save Archive"
    assert updated["data"]["enabled"] is False
    assert removed == {"ok": True, "data": {"removed": True}}
    assert config.current.batch_save_custom_roots == ()


def test_batch_scan_submission_and_current_task_snapshot(tmp_path: Path) -> None:
    api, tasks, _, _, discovery, _, _ = _api(tmp_path)
    try:
        started = api.start_batch_save_scan(
            {"standardScopeIds": ["documents"], "customRootIds": []}
        )
        snapshot = tasks.wait(started["data"]["taskId"], timeout=2)
        current = api.current_batch_save_task()
    finally:
        tasks.close()

    assert discovery.requests == [BatchScanRequest(("documents",), ())]
    assert snapshot.result["sessionId"] == "session-1"
    assert current["data"]["kind"] == "batch_save_scan"
    assert current["data"]["status"] == "completed"


def test_batch_scan_uses_shared_disk_scan_exclusion(tmp_path: Path) -> None:
    api, tasks, *_ = _api(tmp_path)
    entered = Event()
    release = Event()

    def active_scan(_context) -> None:
        entered.set()
        release.wait(2)

    try:
        existing = tasks.submit("library_scan", active_scan, exclusive_group="disk_scan")
        assert entered.wait(1)
        result = api.start_batch_save_scan(
            {"standardScopeIds": ["documents"], "customRootIds": []}
        )
        release.set()
        tasks.wait(existing, timeout=2)
    finally:
        release.set()
        tasks.close()

    assert result["error"]["code"] == "disk_scan_active"


def test_batch_review_and_open_commands_forward_only_validated_ids(tmp_path: Path) -> None:
    api, tasks, _, _, _, review, external = _api(tmp_path)
    try:
        accepted = api.accept_batch_save_candidates(
            {"candidateIds": ["candidate-1"], "confirmRegistry": False}
        )
        reassociated = api.reassociate_batch_save_candidates(
            {"candidateIds": ["candidate-1"], "gameId": "game-1"}
        )
        ignored = api.ignore_batch_save_candidates({"candidateIds": ["candidate-1"]})
        restored = api.restore_batch_save_candidates({"candidateIds": ["candidate-1"]})
        opened = api.open_batch_save_candidate({"candidateId": "candidate-1"})
        lookup = api.open_batch_save_lookup(
            {"candidateId": "candidate-1", "provider": "vndb"}
        )
    finally:
        tasks.close()

    assert accepted["data"] == {
        "locations": [],
        "recordedCount": 0,
        "unchangedCount": 1,
    }
    assert reassociated["data"] == {"updatedCount": 1}
    assert ignored["data"] == {"updatedCount": 1}
    assert restored["data"] == {"updatedCount": 1}
    assert opened == {"ok": True, "data": {"opened": True}}
    assert lookup == {
        "ok": True,
        "data": {"opened": True, "url": "https://vndb.org/v?q=Alice"},
    }
    assert review.calls[:4] == [
        ("accept", ("candidate-1",), False),
        ("reassociate", ("candidate-1",), "game-1"),
        ("ignore", ("candidate-1",)),
        ("restore", ("candidate-1",)),
    ]
    assert external.calls == [("candidate-1", "vndb")]


def _api(tmp_path: Path):
    paths = AppPaths.from_root(tmp_path / "portable")
    config = ConfigService(JsonConfigStore(paths.config_file))
    tasks = TaskRegistry(max_workers=1)
    repository = FakeBatchRepository()
    discovery = FakeBatchDiscovery()
    review = FakeBatchReview()
    external = FakeExternalLookup()
    opener = FakeCandidateOpener()
    api = BridgeApi(
        paths,
        tasks,
        schema_version=4,
        config=config,
        batch_repository=repository,
        batch_saves=discovery,
        batch_review=review,
        batch_external=external,
        batch_candidate_opener=opener,
    )
    return api, tasks, config, repository, discovery, review, external


def _candidate() -> PersistedBatchCandidate:
    return PersistedBatchCandidate(
        id="candidate-1",
        scope_key="documents",
        kind="directory",
        path_template=r"<winDocuments>\Alice",
        display_path=r"C:\Users\Alice\Documents\Alice",
        path_key=r"c:\users\alice\documents\alice",
        availability="available",
        classification="installed",
        confidence="high",
        suggested_game_id="game-1",
        suggested_title="Alice",
        external_product_id="RJ123456",
        engine_id="unity",
        strong_group_key="product:rj123456",
        review_game_id=None,
        review_status="pending",
        save_location_id=None,
        latest_session_id="session-1",
        first_seen_at="2026-08-19T00:00:00+00:00",
        last_seen_at="2026-08-19T01:00:00+00:00",
        updated_at="2026-08-19T01:00:00+00:00",
        sources=("ludusavi",),
        evidence=("Ludusavi 精确规则",),
        representative_files=(RepresentativeFile("slot1.sav", 42, 100),),
        matched_file_count=1,
        representatives_truncated=False,
        alternatives=(CandidateAlternative("Alice 2", "标题相近", "game-2"),),
    )
