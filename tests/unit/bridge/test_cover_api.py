import base64
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from gamesave_scout.bootstrap.paths import AppPaths
from gamesave_scout.bridge.api import BridgeApi
from gamesave_scout.bridge.tasks import TaskRegistry
from gamesave_scout.covers.service import CoverService
from gamesave_scout.db.connection import ConnectionFactory
from gamesave_scout.db.migrator import Migrator
from gamesave_scout.db.writer import DbWriter
from gamesave_scout.library.repository import LibraryRepository
from gamesave_scout.library.service import LibraryService


def test_clipboard_api_rejects_non_png_and_oversize_payload(cover_api) -> None:
    api, _, _, game_id = cover_api
    invalid = api.set_cover_from_clipboard(
        {
            "gameId": game_id,
            "pngBase64": base64.b64encode(b"GIF89a").decode(),
        }
    )

    assert invalid["ok"] is False
    assert invalid["error"]["code"] == "invalid_cover"


def test_file_picker_limits_extensions(cover_api) -> None:
    api, _, window, _ = cover_api

    api.choose_cover_file({})

    assert window.dialog_file_types == (
        "Images (*.png;*.jpg;*.jpeg;*.webp;*.bmp)",
    )


def test_successful_clipboard_cover_returns_versioned_controlled_urls(cover_api) -> None:
    api, _, _, game_id = cover_api
    result = api.set_cover_from_clipboard(
        {
            "gameId": game_id,
            "pngBase64": base64.b64encode(_png()).decode("ascii"),
        }
    )

    assert result["ok"] is True
    assert result["data"]["coverRevision"] == 1
    assert result["data"]["coverThumbUrl"].endswith(f"/cover/{game_id}/thumb?v=1")
    assert "data/covers" not in result["data"]["coverThumbUrl"]


@pytest.fixture
def cover_api(tmp_path: Path):
    paths = AppPaths.from_root(tmp_path / "portable")
    paths.ensure_writable()
    factory = ConnectionFactory(paths.database_file)
    Migrator(factory, paths.backups_dir).migrate()
    writer = DbWriter(factory)
    writer.start()
    tasks = TaskRegistry(max_workers=1)
    repository = LibraryRepository(factory)
    library = LibraryService(repository, writer)
    game_root = tmp_path / "games"
    (game_root / "Alice").mkdir(parents=True)
    root = library.add_root(str(game_root), "children", 1, [])
    game = library.create_game_for_test(root.id, "Alice", "Alice")
    api = BridgeApi(
        paths,
        tasks,
        schema_version=1,
        library=library,
        covers=CoverService(paths, repository, writer),
        asset_session_token="session-token",
    )
    window = FakeWindow()
    api.attach_window(window)
    try:
        yield api, writer, window, game.id
    finally:
        tasks.close()
        writer.close()


class FakeWindow:
    dialog_file_types: tuple[str, ...] | None = None

    def create_file_dialog(self, _dialog_type, **options):
        self.dialog_file_types = options.get("file_types")
        return None


def _png() -> bytes:
    stream = BytesIO()
    Image.new("RGB", (40, 60), "purple").save(stream, format="PNG")
    return stream.getvalue()
