from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from gameshelf.web.asset_server import AssetServer


@pytest.fixture
def asset_server(tmp_path: Path):
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("<h1>GameShelf</h1>", encoding="utf-8")
    covers = tmp_path / "covers"
    covers.mkdir()
    thumb = covers / "game-1.webp"
    thumb.write_bytes(b"RIFF-test-WEBP")
    server = AssetServer(
        ui,
        lambda game_id, variant: thumb
        if (game_id, variant) == ("game-1", "thumb")
        else None,
        managed_cover_roots=(covers,),
    )
    try:
        yield server
    finally:
        server.stop()


def test_server_serves_known_thumb_with_private_cache(asset_server: AssetServer) -> None:
    address = asset_server.start()

    with urlopen(
        f"{address.origin}/session/{address.session_token}/cover/game-1/thumb",
        timeout=2,
    ) as response:
        assert response.status == 200
        assert response.headers["Content-Type"] == "image/webp"
        assert response.headers["Cache-Control"].startswith("private")
        assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_server_serves_ui_and_head_without_directory_listing(
    asset_server: AssetServer,
) -> None:
    address = asset_server.start()
    with urlopen(address.ui_url, timeout=2) as response:
        assert response.read() == b"<h1>GameShelf</h1>"
        assert "default-src 'self'" in response.headers["Content-Security-Policy"]
    request = Request(address.ui_url, method="HEAD")
    with urlopen(request, timeout=2) as response:
        assert response.read() == b""


@pytest.mark.parametrize(
    "path",
    [
        "/session/wrong/ui/index.html",
        "/session/{token}/ui/%2e%2e/data/library.db",
        "/session/{token}/cover/%2e%2e/thumb",
        "/session/{token}/ui/",
    ],
)
def test_server_rejects_wrong_token_traversal_and_directory_listing(
    asset_server: AssetServer, path: str
) -> None:
    address = asset_server.start()
    with pytest.raises(HTTPError) as captured:
        urlopen(
            address.origin + path.format(token=address.session_token),
            timeout=2,
        )
    assert captured.value.code in {403, 404}
