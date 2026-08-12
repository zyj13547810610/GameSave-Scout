"""Narrow, validated pywebview API exposed to the Vue frontend."""

from __future__ import annotations

import base64
import binascii
from pathlib import Path
from typing import Any, cast

from gameshelf.bootstrap.paths import AppPaths
from gameshelf.bridge.contracts import ApiResult, JSONValue, failure, success
from gameshelf.bridge.tasks import TaskRegistry, TaskSnapshot
from gameshelf.covers.image_pipeline import MAX_SOURCE_BYTES, InvalidCoverImage
from gameshelf.covers.service import CoverService
from gameshelf.library.launcher import (
    GameLauncher,
    InvalidLaunchConfiguration,
)
from gameshelf.library.launcher import (
    GameNotFoundError as LauncherGameNotFoundError,
)
from gameshelf.library.models import Game, ScanRoot
from gameshelf.library.service import (
    GameNotFoundError,
    InvalidExecutableError,
    InvalidGameConfiguration,
    InvalidRootConfiguration,
    LibraryService,
    RootNotFoundError,
)
from gameshelf.scanning.service import ConfirmMoveError, ScanService, ScanSummary


class InvalidRequest(ValueError):
    """Raised when a bridge payload does not match its public JSON contract."""


class BridgeApi:
    def __init__(
        self,
        paths: AppPaths,
        tasks: TaskRegistry,
        *,
        schema_version: int,
        library: LibraryService | None = None,
        scanner: ScanService | None = None,
        launcher: GameLauncher | None = None,
        covers: CoverService | None = None,
        asset_session_token: str | None = None,
    ) -> None:
        self._paths = paths
        self._tasks = tasks
        self._schema_version = schema_version
        self._library = library
        self._scanner = scanner
        self._launcher = launcher
        self._covers = covers
        self._asset_session_token = asset_session_token
        self._window: Any | None = None

    def attach_window(self, window: object) -> None:
        """Attach only the native window needed by whitelisted file dialogs."""
        self._window = window

    def bootstrap(self) -> ApiResult:
        state: dict[str, JSONValue] = {
            "appName": "GameShelf",
            "schemaVersion": self._schema_version,
            "portable": True,
        }
        if self._asset_session_token is not None:
            state["assetSessionToken"] = self._asset_session_token
        return success(state)

    def list_roots(self) -> ApiResult:
        library = self._require_library()
        return success([_root_dto(root) for root in library.list_roots()])

    def add_root(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            root = self._require_library().add_root(
                _string(payload, "displayPath"),
                _scan_mode(payload),
                _integer(payload, "maxDepth"),
                _string_list(payload, "exclusions"),
            )
            return success(_root_dto(root))
        except (InvalidRequest, InvalidRootConfiguration) as error:
            return failure("invalid_request", str(error))

    def update_root(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            root = self._require_library().update_root(
                _string(payload, "rootId"),
                enabled=_boolean(payload, "enabled"),
                scan_mode=_scan_mode(payload),
                max_depth=_integer(payload, "maxDepth"),
                exclusions=_string_list(payload, "exclusions"),
            )
            return success(_root_dto(root))
        except (InvalidRequest, InvalidRootConfiguration) as error:
            return failure("invalid_request", str(error))
        except RootNotFoundError:
            return failure("root_not_found", "没有找到对应的游戏根目录。")

    def remove_root(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            self._require_library().remove_root(_string(payload, "rootId"))
            return success({"removed": True})
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except RootNotFoundError:
            return failure("root_not_found", "没有找到对应的游戏根目录。")

    def remap_root(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            root = self._require_library().remap_root(
                _string(payload, "rootId"), _string(payload, "displayPath")
            )
            return success(_root_dto(root))
        except (InvalidRequest, InvalidRootConfiguration) as error:
            return failure("invalid_request", str(error))
        except RootNotFoundError:
            return failure("root_not_found", "没有找到对应的游戏根目录。")

    def list_games(self) -> ApiResult:
        library = self._require_library()
        return success([self._game_dto(game) for game in library.list_games()])

    def start_scan(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            root_id = _string(payload, "rootId")
            kind = _string(payload, "kind")
            if kind not in {"quick", "full"}:
                raise InvalidRequest("kind must be 'quick' or 'full'.")
            scanner = self._require_scanner()
            task_id = self._tasks.submit(
                "library_scan",
                lambda context: _scan_summary_dto(
                    scanner.scan_root(root_id, cast(Any, kind), context)
                ),
            )
            return success({"taskId": task_id})
        except InvalidRequest as error:
            return failure("invalid_request", str(error))

    def confirm_move(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            game = self._require_scanner().confirm_move(
                _string(payload, "sessionId"),
                _string(payload, "existingGameId"),
                _string(payload, "candidateRelativeDir"),
            )
            return success(self._game_dto(game))
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except ConfirmMoveError as error:
            return failure("invalid_move", str(error))

    def set_game_title(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            game = self._require_library().set_game_title(
                _string(payload, "gameId"), _string(payload, "title")
            )
            return success(self._game_dto(game))
        except (InvalidRequest, InvalidGameConfiguration) as error:
            return failure("invalid_request", str(error))
        except GameNotFoundError:
            return failure("game_not_found", "没有找到对应的游戏。")

    def set_game_executable(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            game = self._require_library().set_game_executable(
                _string(payload, "gameId"), _string(payload, "selectedPath")
            )
            return success(self._game_dto(game))
        except (InvalidRequest, InvalidExecutableError) as error:
            return failure("invalid_executable", str(error))
        except GameNotFoundError:
            return failure("game_not_found", "没有找到对应的游戏。")

    def update_launch_configuration(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            working = payload.get("workingDirRelpath")
            if working is not None and not isinstance(working, str):
                raise InvalidRequest("workingDirRelpath must be a string or null.")
            environment = payload.get("environment")
            if not isinstance(environment, dict) or not all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in environment.items()
            ):
                raise InvalidRequest("environment must contain string keys and values.")
            game = self._require_library().update_launch_configuration(
                _string(payload, "gameId"),
                working_dir_relpath=working,
                launch_args=_string_list(payload, "launchArgs"),
                environment=cast(dict[str, str], environment),
            )
            return success(self._game_dto(game))
        except (InvalidRequest, InvalidGameConfiguration) as error:
            return failure("invalid_request", str(error))
        except GameNotFoundError:
            return failure("game_not_found", "没有找到对应的游戏。")

    def launch_game(self, request: object) -> ApiResult:
        try:
            receipt = self._require_launcher().launch(
                _string(_payload(request), "gameId")
            )
            return success(
                {
                    "gameId": receipt.game_id,
                    "pid": receipt.pid,
                    "launchedAt": receipt.launched_at,
                }
            )
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except (InvalidLaunchConfiguration, LauncherGameNotFoundError) as error:
            return failure("launch_failed", str(error))

    def choose_cover_file(self, request: object) -> ApiResult:
        try:
            _payload(request)
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        return success(
            self._choose_native_path(
                directory=False,
                file_types=("Images (*.png;*.jpg;*.jpeg;*.webp;*.bmp)",),
            )
        )

    def set_cover_from_file(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            game_id = _string(payload, "gameId")
            self._require_covers().import_file(
                game_id, Path(_string(payload, "selectedPath"))
            )
            return success(self._game_dto(self._require_game(game_id)))
        except (InvalidRequest, InvalidCoverImage) as error:
            return failure("invalid_cover", str(error))
        except GameNotFoundError:
            return failure("game_not_found", "没有找到对应的游戏。")

    def set_cover_from_clipboard(self, request: object) -> ApiResult:
        try:
            payload = _payload(request)
            game_id = _string(payload, "gameId")
            encoded = _string(payload, "pngBase64")
            if len(encoded) > (MAX_SOURCE_BYTES * 4 // 3) + 8:
                raise InvalidCoverImage("Clipboard image exceeds the 50 MiB limit.")
            try:
                png_bytes = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error) as error:
                raise InvalidCoverImage("Clipboard image is not valid base64.") from error
            if len(png_bytes) > MAX_SOURCE_BYTES:
                raise InvalidCoverImage("Clipboard image exceeds the 50 MiB limit.")
            self._require_covers().import_clipboard_png(game_id, png_bytes)
            return success(self._game_dto(self._require_game(game_id)))
        except (InvalidRequest, InvalidCoverImage) as error:
            return failure("invalid_cover", str(error))
        except GameNotFoundError:
            return failure("game_not_found", "没有找到对应的游戏。")

    def remove_cover(self, request: object) -> ApiResult:
        try:
            game_id = _string(_payload(request), "gameId")
            self._require_covers().remove(game_id)
            return success(self._game_dto(self._require_game(game_id)))
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except GameNotFoundError:
            return failure("game_not_found", "没有找到对应的游戏。")

    def open_install_directory(self, request: object) -> ApiResult:
        try:
            self._require_launcher().open_install_directory(
                _string(_payload(request), "gameId")
            )
            return success({"opened": True})
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except (InvalidLaunchConfiguration, LauncherGameNotFoundError) as error:
            return failure("open_failed", str(error))

    def choose_directory(self) -> ApiResult:
        return success(self._choose_native_path(directory=True))

    def choose_game_executable(self, request: object) -> ApiResult:
        try:
            game_id = _string(_payload(request), "gameId")
            initial = self._require_library().install_directory(game_id)
            return success(self._choose_native_path(directory=False, initial=initial))
        except InvalidRequest as error:
            return failure("invalid_request", str(error))
        except (GameNotFoundError, InvalidGameConfiguration) as error:
            return failure("game_not_found", str(error))

    def task_snapshot(self, task_id: str) -> ApiResult:
        try:
            snapshot = self._tasks.get_snapshot(task_id)
        except KeyError:
            return failure("task_not_found", "没有找到对应的后台任务。")
        return success(self._snapshot_data(snapshot))

    def cancel_task(self, task_id: str) -> ApiResult:
        try:
            self._tasks.get_snapshot(task_id)
        except KeyError:
            return failure("task_not_found", "没有找到对应的后台任务。")
        return success({"cancelled": self._tasks.cancel(task_id)})

    def _choose_native_path(
        self,
        *,
        directory: bool,
        initial: Path | None = None,
        file_types: tuple[str, ...] | None = None,
    ) -> str | None:
        if self._window is None:
            return None
        import webview

        dialog_type = webview.FOLDER_DIALOG if directory else webview.OPEN_DIALOG
        options: dict[str, object] = {"allow_multiple": False}
        if initial is not None:
            options["directory"] = str(initial)
        if not directory:
            options["file_types"] = file_types or ("Windows 可执行文件 (*.exe)",)
        selected = self._window.create_file_dialog(dialog_type, **options)
        if not selected:
            return None
        return str(selected[0])

    def _game_dto(self, game: Game) -> dict[str, JSONValue]:
        install_path: str | None
        try:
            install_path = str(self._require_library().install_directory(game.id))
        except InvalidGameConfiguration:
            install_path = None
        return {
            "id": game.id,
            "scanRootId": game.scan_root_id,
            "relativeDir": game.relative_dir,
            "installPath": install_path,
            "title": game.title,
            "status": game.status,
            "mainExeRelpath": game.main_exe_relpath,
            "mainExeIsManual": game.main_exe_is_manual,
            "workingDirRelpath": game.working_dir_relpath,
            "launchArgs": list(game.launch_args),
            "environment": dict(game.environment),
            "exeArch": game.exe_arch,
            "coverRevision": game.cover_revision,
            "coverThumbUrl": self._cover_url(game, "thumb"),
            "coverOriginalUrl": self._cover_url(game, "original"),
            "lastLaunchedAt": game.last_launched_at,
            "missingSince": game.missing_since,
        }

    def _require_library(self) -> LibraryService:
        if self._library is None:
            raise RuntimeError("Library services are not configured.")
        return self._library

    def _require_scanner(self) -> ScanService:
        if self._scanner is None:
            raise RuntimeError("Scan services are not configured.")
        return self._scanner

    def _require_launcher(self) -> GameLauncher:
        if self._launcher is None:
            raise RuntimeError("Launch services are not configured.")
        return self._launcher

    def _require_covers(self) -> CoverService:
        if self._covers is None:
            raise RuntimeError("Cover services are not configured.")
        return self._covers

    def _require_game(self, game_id: str) -> Game:
        game = self._require_library().get_game(game_id)
        if game is None:
            raise GameNotFoundError(game_id)
        return game

    def _cover_url(self, game: Game, variant: str) -> str | None:
        relative = (
            game.cover_thumb_relpath if variant == "thumb" else game.cover_original_relpath
        )
        if relative is None or self._asset_session_token is None:
            return None
        return (
            f"/session/{self._asset_session_token}/cover/{game.id}/{variant}"
            f"?v={game.cover_revision}"
        )

    @staticmethod
    def _snapshot_data(snapshot: TaskSnapshot) -> dict[str, JSONValue]:
        return {
            "id": snapshot.id,
            "kind": snapshot.kind,
            "status": snapshot.status,
            "progress": cast(dict[str, JSONValue], snapshot.progress),
            "message": snapshot.message,
            "result": cast(JSONValue, snapshot.result),
            "error": cast(JSONValue, snapshot.error),
        }


def _root_dto(root: ScanRoot) -> dict[str, JSONValue]:
    return {
        "id": root.id,
        "displayPath": root.display_path,
        "pathKey": root.path_key,
        "enabled": root.enabled,
        "scanMode": root.scan_mode,
        "maxDepth": root.max_depth,
        "exclusions": list(root.exclusions),
        "lastScannedAt": root.last_scanned_at,
        "lastScanStatus": root.last_scan_status,
        "lastError": root.last_error,
        "createdAt": root.created_at,
    }


def _scan_summary_dto(summary: ScanSummary) -> dict[str, JSONValue]:
    return {
        "sessionId": summary.session_id,
        "status": summary.status,
        "discovered": summary.discovered,
        "added": summary.added,
        "updated": summary.updated,
        "missing": summary.missing,
        "warnings": summary.warnings,
        "moveSuggestions": [
            {
                "existingGameId": suggestion.existing_game_id,
                "candidateRelativeDir": suggestion.candidate_relative_dir,
                "confidence": suggestion.confidence,
                "evidence": list(suggestion.evidence),
            }
            for suggestion in summary.move_suggestions
        ],
    }


def _payload(request: object) -> dict[str, object]:
    if not isinstance(request, dict) or not all(isinstance(key, str) for key in request):
        raise InvalidRequest("Request must be a JSON object.")
    return cast(dict[str, object], request)


def _string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InvalidRequest(f"{key} must be a non-empty string.")
    return value


def _integer(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise InvalidRequest(f"{key} must be an integer.")
    return value


def _boolean(payload: dict[str, object], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise InvalidRequest(f"{key} must be a boolean.")
    return value


def _string_list(payload: dict[str, object], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise InvalidRequest(f"{key} must be an array of strings.")
    return cast(list[str], value)


def _scan_mode(payload: dict[str, object]) -> Any:
    mode = _string(payload, "scanMode")
    if mode not in {"children", "recursive"}:
        raise InvalidRequest("scanMode must be 'children' or 'recursive'.")
    return mode
