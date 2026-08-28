from __future__ import annotations

import base64
from dataclasses import dataclass, replace
from pathlib import Path

from gamesave_scout.bootstrap.config import ConfigService, JsonConfigStore
from gamesave_scout.bootstrap.paths import AppPaths
from gamesave_scout.bridge.api import BridgeApi
from gamesave_scout.bridge.tasks import TaskRegistry
from gamesave_scout.covers.candidates import (
    CandidateFileRef,
    CoverCandidate,
    CoverWizardQueueItem,
    CoverWizardSnapshot,
)
from gamesave_scout.covers.local_discovery import LocalDiscoverySummary
from gamesave_scout.covers.wizard_service import (
    ActiveCoverWizardError,
    CandidateSourceChangedError,
    CoverWizardBusyError,
)
from gamesave_scout.library.models import Game


class _Library:
    def __init__(self, game: Game) -> None:
        self.game = game

    def install_directory(self, game_id: str) -> Path:
        assert game_id == self.game.id
        return Path(r"D:\Games\Alice")


@dataclass
class _Wizard:
    state: CoverWizardSnapshot
    candidate: CoverCandidate
    game: Game
    shallow_summary: LocalDiscoverySummary | None = None
    added_payload: bytes | None = None
    failure: Exception | None = None
    shallow_call: tuple[str, str, int, int] | None = None

    def start(self, include_existing: bool = False) -> CoverWizardSnapshot:
        if self.failure is not None:
            raise self.failure
        return replace(self.state, include_existing=include_existing)

    def snapshot(self, session_id: str) -> CoverWizardSnapshot:
        assert session_id == self.state.id
        return self.state

    def set_include_existing(
        self, session_id: str, include_existing: bool
    ) -> CoverWizardSnapshot:
        assert session_id == self.state.id
        self.state = replace(self.state, include_existing=include_existing)
        return self.state

    def list_candidates(self, session_id: str, game_id: str):
        assert (session_id, game_id) == (self.state.id, self.game.id)
        return (self.candidate,)

    def add_candidate_bytes(
        self, session_id: str, game_id: str, *, file_name, payload, source
    ) -> CoverCandidate:
        assert (session_id, game_id, file_name, source) == (
            self.state.id,
            self.game.id,
            "drop.png",
            "drop",
        )
        self.added_payload = payload
        return self.candidate

    def collect_vndb(self, session_id, game_ids, limit, context):
        del limit, context
        assert session_id == self.state.id
        assert game_ids == [self.game.id]
        return self.state

    def collect_shallow(self, session_id, game_id, limit, depth, context):
        del context
        assert (session_id, game_id) == (self.state.id, self.game.id)
        self.shallow_call = (session_id, game_id, limit, depth)
        if self.shallow_summary is not None:
            return self.shallow_summary
        return LocalDiscoverySummary((self.candidate,), 1, 0, False, ())

    def collect_directory(self, session_id, directory, context):
        del directory, context
        assert session_id == self.state.id
        return {
            self.game.id: LocalDiscoverySummary((self.candidate,), 1, 0, False, ())
        }

    def adopt(self, session_id: str, candidate_id: str) -> Game:
        if self.failure is not None:
            raise self.failure
        assert (session_id, candidate_id) == (self.state.id, self.candidate.id)
        return self.game

    def skip(self, session_id: str, game_id: str) -> CoverWizardSnapshot:
        assert (session_id, game_id) == (self.state.id, self.game.id)
        return self.state

    def close(self, session_id: str) -> None:
        if self.failure is not None:
            raise self.failure
        assert session_id == self.state.id


def _api(tmp_path: Path, *, online: bool = False):
    paths = AppPaths.from_root(tmp_path / "portable")
    paths.ensure_writable()
    config = ConfigService(JsonConfigStore(paths.config_file))
    if online:
        config.set_cover_wizard_settings(
            online_enabled=True,
            vndb_candidate_limit=5,
            local_scan_candidate_limit=10,
            optimize_enabled=True,
            local_scan_depth=2,
        )
    game = _game()
    candidate = CoverCandidate(
        id="candidate-1",
        game_id=game.id,
        source="vndb",
        source_label="VNDB",
        display_name="千恋＊万花",
        width=600,
        height=900,
        sha256="a" * 64,
        match_kind="exact",
        score=100.0,
        evidence=("标题精确匹配",),
        file_ref=CandidateFileRef(tmp_path / "source.jpg", True, "a" * 64),
        preview_path=tmp_path / "preview.webp",
        vndb_id="v19073",
    )
    state = CoverWizardSnapshot(
        id="wizard-1",
        queue=(
            CoverWizardQueueItem(
                game_id=game.id,
                title=game.title,
                initial_has_cover=False,
                version=game.version,
                status="ready",
                candidate_count=1,
            ),
        ),
        current_game_id=game.id,
        include_existing=False,
        source_operation_active=False,
    )
    wizard = _Wizard(state, candidate, game)
    tasks = TaskRegistry(max_workers=1)
    api = BridgeApi(
        paths,
        tasks,
        schema_version=1,
        config=config,
        library=_Library(game),  # type: ignore[arg-type]
        cover_wizard=wizard,  # type: ignore[arg-type]
        asset_session_token="asset-token",
    )
    return api, tasks, wizard


def test_snapshot_and_candidate_dtos_hide_backend_paths(tmp_path: Path) -> None:
    api, tasks, _ = _api(tmp_path)
    try:
        started = api.start_cover_wizard({"includeExisting": False})
        candidates = api.list_cover_candidates(
            {"sessionId": "wizard-1", "gameId": "game-1"}
        )

        assert started["data"] == {
            "id": "wizard-1",
            "queue": [
                {
                    "gameId": "game-1",
                    "title": "Alice",
                    "version": "v1.0.8",
                    "initialHasCover": False,
                    "status": "ready",
                    "candidateCount": 1,
                    "error": None,
                }
            ],
            "currentGameId": "game-1",
            "includeExisting": False,
            "sourceOperationActive": False,
        }
        assert candidates["data"] == [
            {
                "id": "candidate-1",
                "gameId": "game-1",
                "source": "vndb",
                "sourceLabel": "VNDB",
                "displayName": "千恋＊万花",
                "width": 600,
                "height": 900,
                "matchKind": "exact",
                "score": 100.0,
                "evidence": ["标题精确匹配"],
                "previewUrl": (
                    "/session/asset-token/candidate/wizard-1/candidate-1"
                ),
                "vndbId": "v19073",
            }
        ]
        assert "file_ref" not in str(candidates)
        assert str(tmp_path) not in str(candidates)
    finally:
        tasks.close()


def test_base64_input_is_strict_and_bounded_before_service(tmp_path: Path) -> None:
    api, tasks, wizard = _api(tmp_path)
    try:
        invalid = api.add_cover_candidate_bytes(
            {
                "sessionId": "wizard-1",
                "gameId": "game-1",
                "source": "drop",
                "fileName": "drop.png",
                "contentType": "image/png",
                "dataBase64": "%%%",
            }
        )
        assert invalid["error"]["code"] == "invalid_request"
        assert wizard.added_payload is None

        result = api.add_cover_candidate_bytes(
            {
                "sessionId": "wizard-1",
                "gameId": "game-1",
                "source": "drop",
                "fileName": "drop.png",
                "contentType": "image/png",
                "dataBase64": base64.b64encode(b"image").decode(),
            }
        )
        assert result["ok"] is True
        assert wizard.added_payload == b"image"
    finally:
        tasks.close()


def test_online_disabled_never_submits_vndb_task(tmp_path: Path) -> None:
    api, tasks, _ = _api(tmp_path)
    try:
        result = api.start_cover_vndb_search(
            {"sessionId": "wizard-1", "gameIds": ["game-1"], "limit": 5}
        )
        assert result["error"]["code"] == "cover_online_disabled"
    finally:
        tasks.close()


def test_source_tasks_return_json_safe_counts(tmp_path: Path) -> None:
    api, tasks, wizard = _api(tmp_path, online=True)
    try:
        result = api.start_cover_shallow_scan(
            {"sessionId": "wizard-1", "gameId": "game-1", "limit": 10, "depth": 3}
        )
        task = tasks.wait(result["data"]["taskId"], timeout=5)
        assert task.status == "completed"
        assert task.progress == {"completed": 1, "total": 1}
        assert task.message == "浅层扫描完成，找到 1 张候选封面。"
        assert task.result == {
            "sessionId": "wizard-1",
            "completedCount": 1,
            "failedCount": 0,
            "truncated": False,
        }
        assert wizard.shallow_call == ("wizard-1", "game-1", 10, 3)
    finally:
        tasks.close()


def test_empty_shallow_scan_reports_completed_without_candidates(
    tmp_path: Path,
) -> None:
    api, tasks, wizard = _api(tmp_path)
    wizard.shallow_summary = LocalDiscoverySummary((), 0, 0, False, ())
    try:
        result = api.start_cover_shallow_scan(
            {"sessionId": "wizard-1", "gameId": "game-1", "limit": 10, "depth": 2}
        )
        task = tasks.wait(result["data"]["taskId"], timeout=5)

        assert task.status == "completed"
        assert task.progress == {"completed": 1, "total": 1}
        assert task.message == "浅层扫描完成，未找到候选封面。"
        assert task.result == {
            "sessionId": "wizard-1",
            "completedCount": 0,
            "failedCount": 0,
            "truncated": False,
        }
    finally:
        tasks.close()


def test_shallow_scan_rejects_missing_boolean_and_out_of_range_depths(
    tmp_path: Path,
) -> None:
    api, tasks, wizard = _api(tmp_path)
    try:
        for depth in (None, True, 0, 4):
            request = {"sessionId": "wizard-1", "gameId": "game-1", "limit": 10}
            if depth is not None:
                request["depth"] = depth

            result = api.start_cover_shallow_scan(request)

            assert result["ok"] is False
            assert result["error"]["code"] == "invalid_request"
        assert wizard.shallow_call is None
    finally:
        tasks.close()


def test_stable_wizard_error_codes(tmp_path: Path) -> None:
    api, tasks, wizard = _api(tmp_path)
    try:
        wizard.failure = ActiveCoverWizardError("active")
        assert api.start_cover_wizard({})["error"]["code"] == "cover_wizard_active"
        wizard.failure = CandidateSourceChangedError("changed")
        assert (
            api.adopt_cover_candidate(
                {"sessionId": "wizard-1", "candidateId": "candidate-1"}
            )["error"]["code"]
            == "cover_candidate_changed"
        )
        wizard.failure = CoverWizardBusyError("busy")
        assert (
            api.close_cover_wizard({"sessionId": "wizard-1"})["error"]["code"]
            == "cover_wizard_busy"
        )
    finally:
        tasks.close()


def _game() -> Game:
    return Game(
        id="game-1",
        scan_root_id="root-1",
        relative_dir="Alice",
        install_path_key=r"d:\games\alice",
        title="Alice",
        detected_title="Alice",
        status="installed",
        detected_engine_id=None,
        detected_engine_variant=None,
        engine_id=None,
        engine_variant=None,
        engine_is_manual=False,
        engine_confidence=None,
        engine_evidence=(),
        engine_rules_version=None,
        main_exe_relpath=None,
        main_exe_is_manual=False,
        working_dir_relpath=None,
        launch_args=(),
        environment={},
        exe_arch="unknown",
        cover_original_relpath=None,
        cover_thumb_relpath=None,
        cover_revision=0,
        last_launched_at=None,
        missing_since=None,
        version="v1.0.8",
    )
