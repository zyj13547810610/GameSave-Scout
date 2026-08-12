from dataclasses import replace
from pathlib import Path
from typing import cast

from gameshelf.bootstrap.paths import AppPaths
from gameshelf.bridge.api import BridgeApi
from gameshelf.bridge.tasks import TaskRegistry
from gameshelf.saves.models import SaveLocation
from gameshelf.saves.service import InvalidSaveLocation, SaveLocationService


class FakeSaveService:
    def __init__(self) -> None:
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


class FakeWindow:
    def __init__(self) -> None:
        self.options: dict[str, object] = {}

    def create_file_dialog(self, _dialog_type: object, **options: object) -> tuple[str]:
        self.options = options
        return (r"C:\Users\Alice\Saves",)


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


def _api(tmp_path: Path) -> tuple[BridgeApi, TaskRegistry]:
    paths = AppPaths.from_root(tmp_path / "portable")
    tasks = TaskRegistry(max_workers=1)
    api = BridgeApi(
        paths,
        tasks,
        schema_version=1,
        save_locations=cast(SaveLocationService, FakeSaveService()),
    )
    return api, tasks

