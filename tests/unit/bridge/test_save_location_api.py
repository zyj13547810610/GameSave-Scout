from dataclasses import replace
from pathlib import Path
from typing import cast

from gamesave_scout.bootstrap.paths import AppPaths
from gamesave_scout.bridge.api import BridgeApi
from gamesave_scout.bridge.tasks import TaskRegistry
from gamesave_scout.saves.ludusavi_provider import (
    LudusaviStatus,
    SnapshotMetadata,
    SnapshotUpdateError,
    UpdateResult,
)
from gamesave_scout.saves.models import (
    SaveLocation,
    SaveLocationSuggestion,
    SuggestionEvidence,
)
from gamesave_scout.saves.service import InvalidSaveLocation, SaveLocationService


class FakeSaveService:
    def __init__(self) -> None:
        self.accepted_sources: list[str] = []
        self.location = SaveLocation(
            id="save-1",
            game_id="game-1",
            kind="directory",
            path_template=r"<home>\Saves\Alice",
            display_path=r"C:\Users\Alice\Saves\Alice",
            path_key=r"c:\users\alice\saves\alice",
            source="manual",
            confidence=1.0,
            evidence=("用户手动添加",),
            confirmed=True,
            enabled=True,
            last_verified_at="2026-08-12T00:00:00+00:00",
            exists=False,
        )

    def list_for_game(self, _game_id: str) -> tuple[SaveLocation, ...]:
        return (self.location,)

    def add_manual(self, _game_id: str, kind: str, _selected: str) -> SaveLocation:
        if kind == "socket":
            raise InvalidSaveLocation("未知的存档位置类型：socket")
        return self.location

    def remove(self, _location_id: str) -> None:
        return None

    def verify_game(self, _game_id: str) -> tuple[SaveLocation, ...]:
        return (replace(self.location, exists=True),)

    def open_location(self, _location_id: str) -> None:
        return None

    def accept_suggestion(self, _game_id: str, suggestion: SaveLocationSuggestion) -> SaveLocation:
        self.accepted_sources.append(suggestion.source)
        return replace(self.location, source=suggestion.source)


class FakeWindow:
    def __init__(self) -> None:
        self.options: dict[str, object] = {}

    def create_file_dialog(self, _dialog_type: object, **options: object) -> tuple[str]:
        self.options = options
        return (r"C:\Users\Alice\Saves",)


class FakeDiscovery:
    def __init__(self) -> None:
        self.invalidated = False
        self.suggestion = SaveLocationSuggestion(
            kind="registry",
            path_template=r"HKEY_CURRENT_USER\Software\Studio\Alice",
            display_path=r"HKEY_CURRENT_USER\Software\Studio\Alice",
            source="engine",
            confidence=0.9,
            evidence=("Unity PlayerPrefs",),
            source_evidence=(SuggestionEvidence("builtin", "Unity PlayerPrefs"),),
            suggestion_id="suggestion-1",
            group="exact",
            availability="found",
        )

    def suggest_for_game(self, _game_id: str) -> tuple[SaveLocationSuggestion, ...]:
        return (self.suggestion,)

    def invalidate_ludusavi(self) -> None:
        self.invalidated = True


class FakeSnapshotProvider:
    def __init__(self) -> None:
        self.update_calls = 0
        self.restore_calls = 0
        self.result: UpdateResult | None = None

    def metadata(self) -> SnapshotMetadata:
        return SnapshotMetadata(
            etag='"etag"',
            sha256="a" * 64,
            downloaded_at="2026-08-12T00:00:00+00:00",
            source_url="https://example.test/manifest.yaml",
            upstream_commit="b" * 40,
        )

    def update_explicitly(self, report=None) -> UpdateResult:
        self.update_calls += 1
        for stage in (
            "connecting",
            "downloading",
            "validating",
            "indexing",
            "probing",
            "replacing",
        ):
            if report is not None:
                report(stage)
        return self.result or UpdateResult("updated", "已更新", self.metadata())

    def status(self) -> LudusaviStatus:
        metadata = self.metadata()
        return LudusaviStatus(True, "active", metadata, "c" * 64, None)

    def restore_bundled(self) -> LudusaviStatus:
        self.restore_calls += 1
        metadata = self.metadata()
        return LudusaviStatus(True, "bundled", metadata, "c" * 64, None)


class UnavailableSnapshotProvider(FakeSnapshotProvider):
    def metadata(self) -> SnapshotMetadata:
        raise SnapshotUpdateError("内置清单损坏")

    def status(self) -> LudusaviStatus:
        return LudusaviStatus(False, None, None, None, "内置清单损坏")


def test_manual_api_requires_supported_kind(tmp_path: Path) -> None:
    api, tasks = _api(tmp_path)
    try:
        result = api.add_manual_save_location(
            {
                "gameId": "game-1",
                "kind": "socket",
                "selectedPath": r"C:\Save",
            }
        )
    finally:
        tasks.close()

    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_save_location"


def test_list_api_returns_camel_case_location_dto(tmp_path: Path) -> None:
    api, tasks = _api(tmp_path)
    try:
        result = api.list_save_locations({"gameId": "game-1"})
    finally:
        tasks.close()

    assert result["ok"] is True
    assert result["data"][0] == {
        "id": "save-1",
        "gameId": "game-1",
        "kind": "directory",
        "pathTemplate": r"<home>\Saves\Alice",
        "displayPath": r"C:\Users\Alice\Saves\Alice",
        "source": "manual",
        "confidence": 1.0,
        "evidence": ["用户手动添加"],
        "confirmed": True,
        "enabled": True,
        "lastVerifiedAt": "2026-08-12T00:00:00+00:00",
        "exists": False,
        "matchCount": None,
        "matchesTruncated": False,
    }


def test_save_path_picker_uses_directory_dialog_for_glob(tmp_path: Path) -> None:
    api, tasks = _api(tmp_path)
    window = FakeWindow()
    api.attach_window(window)
    try:
        result = api.choose_save_path({"gameId": "game-1", "kind": "glob"})
    finally:
        tasks.close()

    assert result == {"ok": True, "data": r"C:\Users\Alice\Saves"}
    assert window.options["allow_multiple"] is False


def test_registry_suggestion_requires_explicit_confirmation(tmp_path: Path) -> None:
    api, tasks = _api(tmp_path, discovery=FakeDiscovery())
    try:
        result = api.accept_save_suggestions(
            {
                "gameId": "game-1",
                "suggestionIds": ["suggestion-1"],
                "confirmRegistry": False,
            }
        )
    finally:
        tasks.close()

    assert result["ok"] is False
    assert result["error"]["code"] == "registry_confirmation_required"


def test_suggestion_dto_exposes_builtin_evidence_and_availability(
    tmp_path: Path,
) -> None:
    api, tasks = _api(tmp_path, discovery=FakeDiscovery())
    try:
        result = api.suggest_save_locations({"gameId": "game-1"})
    finally:
        tasks.close()

    assert result["ok"] is True
    assert result["data"][0]["availability"] == "found"
    assert result["data"][0]["sourceEvidence"] == [
        {"source": "builtin", "detail": "Unity PlayerPrefs"}
    ]


def test_accepting_builtin_suggestion_keeps_persisted_source_compatible(
    tmp_path: Path,
) -> None:
    service = FakeSaveService()
    discovery = FakeDiscovery()
    discovery.suggestion = replace(discovery.suggestion, kind="directory")
    api, tasks = _api(
        tmp_path,
        discovery=discovery,
        save_service=service,
    )
    try:
        result = api.accept_save_suggestions(
            {
                "gameId": "game-1",
                "suggestionIds": ["suggestion-1"],
                "confirmRegistry": False,
            }
        )
    finally:
        tasks.close()

    assert result["ok"] is True
    assert result["data"][0]["source"] == "engine"
    assert service.accepted_sources == ["engine"]


def test_ludusavi_update_is_submitted_only_after_explicit_api_call(tmp_path: Path) -> None:
    discovery = FakeDiscovery()
    provider = FakeSnapshotProvider()
    api, tasks = _api(tmp_path, discovery=discovery, snapshot_provider=provider)
    try:
        assert provider.update_calls == 0
        result = api.update_ludusavi({})
        assert result["ok"] is True
        task_id = result["data"]["taskId"]
        snapshot = tasks.wait(task_id, timeout=2)
    finally:
        tasks.close()

    assert provider.update_calls == 1
    assert discovery.invalidated is True
    assert snapshot.status == "completed"
    assert snapshot.progress == {"completed": 1, "total": 1}
    assert snapshot.message == "已更新"


def test_ludusavi_status_reports_unavailable_without_failing_api(
    tmp_path: Path,
) -> None:
    api, tasks = _api(tmp_path, snapshot_provider=UnavailableSnapshotProvider())
    try:
        result = api.ludusavi_status()
    finally:
        tasks.close()

    assert result["ok"] is True
    assert result["data"]["available"] is False
    assert result["data"]["unavailableReason"] == "内置清单损坏"
    assert result["data"]["sha256"] is None
    assert result["data"]["source"] is None
    assert result["data"]["bundledSha256"] is None


def test_restore_bundled_is_explicit_strict_and_invalidates_cache(
    tmp_path: Path,
) -> None:
    discovery = FakeDiscovery()
    provider = FakeSnapshotProvider()
    api, tasks = _api(tmp_path, discovery=discovery, snapshot_provider=provider)
    try:
        rejected = api.restore_bundled_ludusavi({"unexpected": True})
        restored = api.restore_bundled_ludusavi({})
    finally:
        tasks.close()

    assert rejected["error"]["code"] == "invalid_request"
    assert restored["ok"] is True
    assert restored["data"]["source"] == "bundled"
    assert provider.restore_calls == 1
    assert discovery.invalidated is True


def test_failed_update_result_does_not_invalidate_cache(tmp_path: Path) -> None:
    discovery = FakeDiscovery()
    provider = FakeSnapshotProvider()
    provider.result = UpdateResult(
        "failed",
        "网络失败，旧清单仍可使用。",
        provider.metadata(),
    )
    api, tasks = _api(tmp_path, discovery=discovery, snapshot_provider=provider)
    try:
        task = api.update_ludusavi({})
        tasks.wait(task["data"]["taskId"], timeout=2)
    finally:
        tasks.close()

    assert discovery.invalidated is False


def _api(
    tmp_path: Path,
    *,
    discovery: FakeDiscovery | None = None,
    snapshot_provider: FakeSnapshotProvider | None = None,
    save_service: FakeSaveService | None = None,
) -> tuple[BridgeApi, TaskRegistry]:
    paths = AppPaths.from_root(tmp_path / "portable")
    tasks = TaskRegistry(max_workers=1)
    api = BridgeApi(
        paths,
        tasks,
        schema_version=1,
        save_locations=cast(SaveLocationService, save_service or FakeSaveService()),
        static_discovery=discovery,
        ludusavi_provider=snapshot_provider,
    )
    return api, tasks
