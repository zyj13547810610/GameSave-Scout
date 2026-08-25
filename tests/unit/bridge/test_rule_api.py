from __future__ import annotations

from pathlib import Path
from typing import cast

import webview

from gamesave_scout.bootstrap.paths import AppPaths
from gamesave_scout.bridge.api import BridgeApi
from gamesave_scout.bridge.rule_controller import RuleBridgeController
from gamesave_scout.bridge.tasks import TaskRegistry
from gamesave_scout.rules.import_export import RuleImportExportService
from gamesave_scout.saves.ludusavi_provider import (
    LudusaviProvider,
    LudusaviStatus,
    SnapshotMetadata,
    UpdateResult,
)
from tests.unit.rules.test_rule_management import _service


class FakeWindow:
    def __init__(self, selections: list[tuple[str, ...]]) -> None:
        self.selections = selections
        self.calls: list[tuple[object, dict[str, object]]] = []

    def create_file_dialog(self, dialog_type: object, **options: object) -> tuple[str, ...]:
        self.calls.append((dialog_type, options))
        return self.selections.pop(0) if self.selections else ()


class DirectoryOpener:
    def __init__(self) -> None:
        self.paths: list[Path] = []

    def __call__(self, path: Path) -> None:
        self.paths.append(path)


class FakeLudusaviProvider:
    def __init__(self) -> None:
        self.restore_calls = 0
        self.update_calls = 0
        self.reported_stages: list[str] = []
        self.metadata = SnapshotMetadata(
            etag='"active"',
            sha256="a" * 64,
            downloaded_at="2026-08-23T00:00:00+00:00",
            source_url="https://example.test/manifest.yaml",
            upstream_commit=None,
        )

    def status(self) -> LudusaviStatus:
        return LudusaviStatus(True, "active", self.metadata, "b" * 64, None)

    def restore_bundled(self) -> LudusaviStatus:
        self.restore_calls += 1
        return LudusaviStatus(True, "bundled", self.metadata, "b" * 64, None)

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
            self.reported_stages.append(stage)
            if report is not None:
                report(stage)
        return UpdateResult("updated", "已更新", self.metadata)


def test_rule_api_rejects_unknown_fields_and_maps_management_dtos(
    tmp_path: Path,
) -> None:
    api, tasks, _, _ = _api(tmp_path)
    try:
        rejected = api.list_rules(
            {
                "kind": "all",
                "source": "all",
                "status": "all",
                "enabled": "all",
                "query": "",
                "offset": 0,
                "limit": 20,
                "extra": True,
            }
        )
        listed = api.list_rules(
            {
                "kind": "engine",
                "source": "builtin",
                "status": "all",
                "enabled": "all",
                "query": "declared",
                "offset": 0,
                "limit": 20,
            }
        )
        detail = api.get_rule({"qualifiedId": "builtin:declared_engine"})
        readonly = api.delete_rule({"qualifiedId": "builtin:declared_engine"})
    finally:
        tasks.close()

    assert rejected == {
        "ok": False,
        "error": {"code": "invalid_request", "message": "请求包含不受支持的字段：extra"},
    }
    assert listed["ok"] is True
    assert listed["data"]["items"][0]["qualifiedId"] == "builtin:declared_engine"
    assert detail["data"]["capabilities"]["edit"] is False
    assert readonly["error"]["code"] == "builtin_rule_readonly"


def test_rule_api_enforces_pagination_query_and_discriminated_draft_fields(
    tmp_path: Path,
) -> None:
    api, tasks, _, _ = _api(tmp_path)
    common_filters = {
        "kind": "all",
        "source": "all",
        "status": "all",
        "enabled": "all",
        "offset": 0,
    }
    drafts: list[dict[str, object]] = [
        {
            "version": "test",
            "id": "engine",
            "label": "Engine",
            "type": "engine",
            "all": [{"op": "path_exists", "path": "x", "weight": 1.0}],
            "unexpected": True,
        },
        {
            "version": "test",
            "id": "game_save",
            "label": "Game Save",
            "type": "save_game",
            "titles": ["Game"],
            "locations": [
                {
                    "kind": "directory",
                    "path": "<winDocuments>\\Game",
                    "category": "save",
                    "confidence": 1.0,
                }
            ],
            "unexpected": True,
        },
        {
            "version": "test",
            "id": "engine_save",
            "label": "Engine Save",
            "type": "save_engine",
            "engine_ids": ["unity"],
            "locations": [
                {
                    "kind": "directory",
                    "path": "<winAppData>\\Game",
                    "category": "save",
                    "confidence": 1.0,
                }
            ],
            "unexpected": True,
        },
    ]
    try:
        excessive_page = api.list_rules(
            {**common_filters, "query": "", "limit": 201}
        )
        excessive_query = api.list_rules(
            {**common_filters, "query": "x" * 201, "limit": 20}
        )
        validations = [api.validate_rule_draft({"draft": draft}) for draft in drafts]
    finally:
        tasks.close()

    assert excessive_page["error"]["code"] == "invalid_request"
    assert excessive_query["error"]["code"] == "invalid_request"
    assert all(result["ok"] is True for result in validations)
    assert all(result["data"]["valid"] is False for result in validations)
    assert all(
        result["data"]["errorCode"] == "invalid_rule_draft"
        for result in validations
    )


def test_rule_api_uses_multi_open_save_dialog_and_restricted_directories(
    tmp_path: Path,
) -> None:
    incoming = tmp_path / "incoming.yaml"
    incoming.write_text(
        "version: 1\nrules:\n  - id: incoming\n    label: Incoming\n"
        "    type: engine\n    all: [{op: path_exists, path: x, weight: 1}]\n",
        encoding="utf-8",
    )
    export_path = tmp_path / "export.yaml"
    api, tasks, window, opener = _api(
        tmp_path,
        selections=[(str(incoming),), (str(export_path),)],
    )
    try:
        begun = api.begin_rule_import({})
        exported = api.export_rule({"qualifiedId": "builtin:declared_engine"})
        opened_user = api.open_rule_directory({"target": "user"})
        missing_legacy = api.open_rule_directory({"target": "legacy"})
    finally:
        tasks.close()

    assert begun["ok"] is True
    assert exported == {
        "ok": True,
        "data": {"cancelled": False, "fileName": "export.yaml"},
    }
    assert window.calls[0][1] == {
        "allow_multiple": True,
        "file_types": ("GameSave Scout 规则 (*.yaml;*.yml)",),
    }
    assert window.calls[1][1]["allow_multiple"] is False
    assert window.calls[1][0] is webview.SAVE_DIALOG
    assert window.calls[1][1]["save_filename"] == "declared_engine.yaml"
    assert opened_user["ok"] is True
    assert opener.paths == [tmp_path / "portable" / "data" / "rules" / "user"]
    assert missing_legacy["error"]["code"] == "legacy_manifest_not_found"


def test_rule_api_cancelled_dialogs_are_successful(tmp_path: Path) -> None:
    api, tasks, _, _ = _api(tmp_path, selections=[(), ()])
    try:
        begun = api.begin_rule_import({})
        exported = api.export_rule({"qualifiedId": "builtin:declared_engine"})
    finally:
        tasks.close()

    assert begun == {"ok": True, "data": {"cancelled": True}}
    assert exported == {"ok": True, "data": {"cancelled": True}}


def test_rule_api_reports_source_and_restores_bundled_snapshot_strictly(
    tmp_path: Path,
) -> None:
    provider = FakeLudusaviProvider()
    invalidations: list[str] = []
    api, tasks, _, _ = _api(
        tmp_path,
        snapshot_provider=provider,
        invalidations=invalidations,
    )
    try:
        status = api.ludusavi_status()
        rejected = api.restore_bundled_ludusavi({"extra": True})
        restored = api.restore_bundled_ludusavi({})
    finally:
        tasks.close()

    assert status["data"]["source"] == "active"
    assert status["data"]["bundledSha256"] == "b" * 64
    assert rejected["error"]["code"] == "invalid_request"
    assert restored["data"]["source"] == "bundled"
    assert provider.restore_calls == 1
    assert invalidations == ["invalidated"]


def test_rule_api_runs_explicit_ludusavi_update_with_cold_probe_progress(
    tmp_path: Path,
) -> None:
    provider = FakeLudusaviProvider()
    invalidations: list[str] = []
    api, tasks, _, _ = _api(
        tmp_path,
        snapshot_provider=provider,
        invalidations=invalidations,
    )
    try:
        rejected = api.update_ludusavi({"extra": True})
        started = api.update_ludusavi({})
        snapshot = tasks.wait(started["data"]["taskId"], timeout=2)
    finally:
        tasks.close()

    assert rejected["error"]["code"] == "invalid_request"
    assert snapshot.status == "completed"
    assert snapshot.message == "已更新"
    assert provider.update_calls == 1
    assert provider.reported_stages == [
        "connecting",
        "downloading",
        "validating",
        "indexing",
        "probing",
        "replacing",
    ]
    assert invalidations == ["invalidated"]


def _api(
    tmp_path: Path,
    *,
    selections: list[tuple[str, ...]] | None = None,
    snapshot_provider: FakeLudusaviProvider | None = None,
    invalidations: list[str] | None = None,
) -> tuple[BridgeApi, TaskRegistry, FakeWindow, DirectoryOpener]:
    management, catalog, repository, _ = _service(tmp_path)
    paths = AppPaths.from_root(tmp_path / "portable")
    opener = DirectoryOpener()
    tasks = TaskRegistry(max_workers=1)
    controller = RuleBridgeController(
        management=management,
        catalog=catalog,
        import_export=RuleImportExportService(
            catalog=catalog,
            repository=repository,
        ),
        user_rule_directory=paths.user_rules_dir,
        legacy_manifest_directory=paths.legacy_manifests_dir,
        directory_opener=opener,
        tasks=tasks,
        ludusavi_provider=(
            None
            if snapshot_provider is None
            else cast(LudusaviProvider, snapshot_provider)
        ),
        ludusavi_invalidator=(
            None
            if invalidations is None
            else lambda: invalidations.append("invalidated")
        ),
    )
    api = BridgeApi(paths, tasks, schema_version=4, rule_controller=controller)
    window = FakeWindow(selections or [])
    api.attach_window(window)
    return api, tasks, window, opener
