from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from gamesave_scout.bootstrap.paths import AppPaths
from gamesave_scout.bridge.api import BridgeApi
from gamesave_scout.bridge.tasks import TaskRegistry
from gamesave_scout.library.service import LibraryService
from gamesave_scout.saves.guided_models import (
    GuidedRegistryTarget,
    GuidedSaveDiscovery,
    GuidedSavePreview,
    GuidedSaveSession,
    GuidedScopeOption,
)
from gamesave_scout.saves.guided_repository import GuidedSaveRepository
from gamesave_scout.saves.guided_review import GuidedReviewError, GuidedSaveReviewService
from gamesave_scout.saves.guided_scope import InvalidGuidedScope
from gamesave_scout.saves.guided_service import GuidedSaveError, GuidedSaveSessionService
from gamesave_scout.saves.models import SaveLocation


class FakeLibrary:
    def get_game(self, game_id: str) -> object | None:
        if game_id == "missing-game":
            return None
        return SimpleNamespace(id=game_id, title="Alice")


class FakeGuidedService:
    def __init__(self) -> None:
        self.session = _session()
        self.mark_calls = 0
        self.close_requested = True
        self.resolutions: list[str] = []

    def preview(self, _game_id: str) -> GuidedSavePreview:
        return _preview()

    def start(
        self,
        _game_id: str,
        selected_scope_ids: tuple[str, ...],
        _additional_directories: tuple[str, ...],
    ) -> GuidedSaveSession:
        if "unknown" in selected_scope_ids:
            raise InvalidGuidedScope("未知的监控范围：unknown")
        return self.session

    def current(self) -> GuidedSaveSession | None:
        return self.session

    def status(self, session_id: str) -> GuidedSaveSession:
        if session_id == "bad-state":
            raise GuidedSaveError("guided_session_not_active", "内部状态细节")
        if session_id == "missing":
            raise GuidedSaveError("guided_session_not_found", "内部查询细节")
        return self.session

    def latest_for_game(self, game_id: str) -> GuidedSaveSession | None:
        return replace(self.session, game_id=game_id)

    def mark_saved(self, _session_id: str) -> GuidedSaveSession:
        self.mark_calls += 1
        self.session = replace(
            self.session,
            status="settling",
            save_marked_at="2026-08-15T00:00:10+00:00",
        )
        return self.session

    def stop_and_analyze(self, session_id: str) -> GuidedSaveSession:
        if session_id == "bad-state":
            raise GuidedSaveError("guided_session_not_active", "WinError 6")
        return self.session

    def cancel(self, _session_id: str) -> GuidedSaveSession:
        self.session = replace(
            self.session,
            status="cancelled",
            finished_at="2026-08-15T00:00:20+00:00",
        )
        return self.session

    def resolve_close(self, resolution: str) -> None:
        if resolution not in {"return", "cancel_and_exit", "analyze_and_exit"}:
            raise GuidedSaveError("invalid_close_resolution", "内部处理细节")
        self.resolutions.append(resolution)


class FakeGuidedRepository:
    def list_discoveries(self, _session_id: str) -> tuple[GuidedSaveDiscovery, ...]:
        return (_discovery(),)


class FakeGuidedReview:
    def accept(
        self,
        _session_id: str,
        discovery_ids: tuple[str, ...],
        confirm_registry: bool,
    ) -> tuple[SaveLocation, ...]:
        if "invalid" in discovery_ids:
            raise GuidedReviewError("guided_discovery_invalid", "内部候选细节")
        if not confirm_registry:
            raise GuidedReviewError(
                "registry_confirmation_required", "注册表候选需要额外确认。"
            )
        return (_location(),)

    def discard(self, _session_id: str) -> int:
        return 1


def test_preview_returns_camel_case_scope_contract(tmp_path: Path) -> None:
    api, tasks, _, _ = _api(tmp_path)
    try:
        result = api.preview_guided_save_detection({"gameId": "game-1"})
    finally:
        tasks.close()

    assert result["ok"] is True
    assert result["data"] == {
        "gameId": "game-1",
        "gameTitle": "Alice",
        "executable": r"C:\Games\Alice\Alice.exe",
        "scopes": [
            {
                "id": "default:game",
                "label": "游戏安装目录",
                "displayPath": r"C:\Games\Alice",
                "pathTemplate": "<game>",
                "source": "game",
                "defaultSelected": True,
                "available": True,
                "unavailableReason": None,
            }
        ],
        "registryTargets": [
            {
                "key": r"HKEY_CURRENT_USER\Software\Studio\Alice",
                "source": "Ludusavi",
                "available": True,
            }
        ],
        "privacyNotice": "只读取文件路径、大小和修改时间等元数据，不读取或修改存档内容。",
    }


def test_start_rejects_empty_or_unknown_scopes_with_stable_codes(tmp_path: Path) -> None:
    api, tasks, _, _ = _api(tmp_path)
    try:
        empty = api.start_guided_save_detection(
            {
                "gameId": "game-1",
                "selectedScopeIds": [],
                "additionalDirectories": [],
            }
        )
        unknown = api.start_guided_save_detection(
            {
                "gameId": "game-1",
                "selectedScopeIds": ["unknown"],
                "additionalDirectories": [],
            }
        )
    finally:
        tasks.close()

    assert empty["error"]["code"] == "guided_scope_empty"
    assert unknown["error"]["code"] == "invalid_guided_scope"


def test_session_commands_are_idempotent_and_hide_internal_state_details(
    tmp_path: Path,
) -> None:
    api, tasks, guided, _ = _api(tmp_path)
    try:
        current = api.current_guided_save_detection()
        first_mark = api.mark_guided_save_saved({"sessionId": "session-1"})
        second_mark = api.mark_guided_save_saved({"sessionId": "session-1"})
        invalid_stop = api.stop_guided_save_detection({"sessionId": "bad-state"})
        cancelled = api.cancel_guided_save_detection({"sessionId": "session-1"})
    finally:
        tasks.close()

    assert current["data"]["gameTitle"] == "Alice"
    assert current["data"]["changeCount"] == 12
    assert current["data"]["closeRequested"] is True
    assert "approvedScopes" not in current["data"]
    assert first_mark["ok"] is True and second_mark["ok"] is True
    assert guided.mark_calls == 2
    assert invalid_stop["error"] == {
        "code": "guided_session_not_active",
        "message": "该引导式寻找会话当前不能执行此操作。",
    }
    assert "WinError" not in str(invalid_stop)
    assert cancelled["data"]["status"] == "cancelled"


def test_discovery_review_contract_hides_path_key_and_requires_registry_confirmation(
    tmp_path: Path,
) -> None:
    api, tasks, _, _ = _api(tmp_path)
    try:
        listed = api.list_guided_save_discoveries({"sessionId": "session-1"})
        unconfirmed = api.accept_guided_save_discoveries(
            {
                "sessionId": "session-1",
                "discoveryIds": ["discovery-1"],
                "confirmRegistry": False,
            }
        )
        invalid = api.accept_guided_save_discoveries(
            {
                "sessionId": "session-1",
                "discoveryIds": ["invalid"],
                "confirmRegistry": True,
            }
        )
        accepted = api.accept_guided_save_discoveries(
            {
                "sessionId": "session-1",
                "discoveryIds": ["discovery-1"],
                "confirmRegistry": True,
            }
        )
        discarded = api.discard_guided_save_detection({"sessionId": "session-1"})
    finally:
        tasks.close()

    assert listed["ok"] is True
    assert listed["data"][0]["candidateTemplate"] == (
        r"HKEY_CURRENT_USER\Software\Studio\Alice"
    )
    assert "pathKey" not in listed["data"][0]
    assert unconfirmed["error"]["code"] == "registry_confirmation_required"
    assert invalid["error"] == {
        "code": "guided_discovery_invalid",
        "message": "引导式存档候选已经失效，请刷新后重试。",
    }
    assert accepted["data"][0]["id"] == "save-1"
    assert discarded == {"ok": True, "data": {"discarded": 1}}


def test_status_latest_and_close_resolution_use_narrow_requests(tmp_path: Path) -> None:
    api, tasks, guided, _ = _api(tmp_path)
    try:
        status = api.guided_save_detection_status({"sessionId": "session-1"})
        latest = api.latest_guided_save_detection_for_game({"gameId": "game-1"})
        resolved = api.resolve_guided_close({"resolution": "return"})
        invalid = api.resolve_guided_close({"resolution": "shutdown"})
    finally:
        tasks.close()

    assert status["data"]["id"] == "session-1"
    assert latest["data"]["gameId"] == "game-1"
    assert resolved == {"ok": True, "data": {"resolved": True}}
    assert guided.resolutions == ["return"]
    assert invalid["error"]["code"] == "invalid_close_resolution"


def test_missing_session_game_returns_game_not_found(tmp_path: Path) -> None:
    api, tasks, guided, _ = _api(tmp_path)
    guided.session = replace(guided.session, game_id="missing-game")
    try:
        result = api.current_guided_save_detection()
    finally:
        tasks.close()

    assert result["error"]["code"] == "game_not_found"


def _api(
    tmp_path: Path,
) -> tuple[BridgeApi, TaskRegistry, FakeGuidedService, FakeGuidedReview]:
    tasks = TaskRegistry(max_workers=1)
    guided = FakeGuidedService()
    review = FakeGuidedReview()
    api = BridgeApi(
        AppPaths.from_root(tmp_path / "portable"),
        tasks,
        schema_version=1,
        library=cast(LibraryService, FakeLibrary()),
        guided_saves=cast(GuidedSaveSessionService, guided),
        guided_repository=cast(GuidedSaveRepository, FakeGuidedRepository()),
        guided_review=cast(GuidedSaveReviewService, review),
    )
    return api, tasks, guided, review


def _preview() -> GuidedSavePreview:
    return GuidedSavePreview(
        game_id="game-1",
        game_title="Alice",
        executable=r"C:\Games\Alice\Alice.exe",
        scopes=(
            GuidedScopeOption(
                "default:game",
                "游戏安装目录",
                r"C:\Games\Alice",
                "<game>",
                "game",
                True,
                True,
            ),
        ),
        registry_targets=(
            GuidedRegistryTarget(
                r"HKEY_CURRENT_USER\Software\Studio\Alice", "Ludusavi", True
            ),
        ),
    )


def _session() -> GuidedSaveSession:
    return GuidedSaveSession(
        id="session-1",
        game_id="game-1",
        status="monitoring",
        started_at="2026-08-15T00:00:00+00:00",
        monitoring_started_at="2026-08-15T00:00:01+00:00",
        save_marked_at=None,
        finished_at=None,
        root_pid=123,
        approved_scopes=(),
        unavailable_scopes=(),
        overflowed_scopes=(),
        truncated_scopes=(),
        process_tracking_degraded=False,
        result_summary={"eventCount": 12, "candidateCount": 1},
        error_code=None,
        error_summary=None,
    )


def _discovery() -> GuidedSaveDiscovery:
    key = r"HKEY_CURRENT_USER\Software\Studio\Alice"
    return GuidedSaveDiscovery(
        id="discovery-1",
        detection_session_id="session-1",
        candidate_template=key,
        display_path=key,
        path_key=key.casefold(),
        kind="registry",
        confidence=0.8,
        evidence=("定向注册表键的元数据发生变化",),
        representative_files=(),
        first_changed_at=None,
        last_changed_at=None,
        mark_offset_ms=None,
        affected_by_overflow=False,
        affected_by_truncation=False,
        preselected=False,
        review_status="unreviewed",
        save_location_id=None,
    )


def _location() -> SaveLocation:
    key = r"HKEY_CURRENT_USER\Software\Studio\Alice"
    return SaveLocation(
        id="save-1",
        game_id="game-1",
        kind="registry",
        path_template=key,
        display_path=key,
        path_key=key.casefold(),
        source="dynamic",
        confidence=0.8,
        evidence=("定向注册表键的元数据发生变化",),
        confirmed=True,
        enabled=True,
        last_verified_at=None,
    )
