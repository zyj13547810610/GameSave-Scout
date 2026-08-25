from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from gamesave_scout.web.asset_server import AssetServer


@pytest.fixture
def asset_server(tmp_path: Path):
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("<h1>GameSave Scout</h1>", encoding="utf-8")
    covers = tmp_path / "covers"
    covers.mkdir()
    thumb = covers / "game-1.webp"
    thumb.write_bytes(b"RIFF-test-WEBP")
    candidate_root = tmp_path / "cover-wizard"
    candidate = candidate_root / "wizard-1" / "candidate.webp"
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(b"RIFF-candidate-WEBP")
    server = AssetServer(
        ui,
        lambda game_id, variant: thumb
        if (game_id, variant) == ("game-1", "thumb")
        else None,
        managed_cover_roots=(covers,),
        candidate_lookup=lambda session_id, candidate_id: candidate
        if (session_id, candidate_id) == ("wizard-1", "candidate-1")
        else None,
        candidate_root=candidate_root,
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
        assert response.read() == b"<h1>GameSave Scout</h1>"
        assert "default-src 'self'" in response.headers["Content-Security-Policy"]
    request = Request(address.ui_url, method="HEAD")
    with urlopen(request, timeout=2) as response:
        assert response.read() == b""


def test_server_serves_candidate_with_no_store(asset_server: AssetServer) -> None:
    address = asset_server.start()

    with urlopen(
        f"{address.origin}/session/{address.session_token}/candidate/"
        "wizard-1/candidate-1",
        timeout=2,
    ) as response:
        assert response.status == 200
        assert response.headers["Content-Type"] == "image/webp"
        assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize(
    "path",
    [
        "/session/wrong/ui/index.html",
        "/session/{token}/ui/%2e%2e/data/library.db",
        "/session/{token}/cover/%2e%2e/thumb",
        "/session/{token}/ui/",
        "/session/{token}/candidate/%2e%2e/candidate-1",
        "/session/{token}/candidate/wizard-1/%5ccandidate-1",
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


def test_candidate_callback_cannot_escape_root_or_serve_non_webp(
    tmp_path: Path,
) -> None:
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("ui", encoding="utf-8")
    root = tmp_path / "cover-wizard"
    root.mkdir()
    outside = tmp_path / "outside.webp"
    outside.write_bytes(b"outside")
    non_webp = root / "preview.png"
    non_webp.write_bytes(b"png")
    current = [outside]
    server = AssetServer(
        ui,
        lambda *_: None,
        candidate_lookup=lambda *_: current[0],
        candidate_root=root,
    )
    try:
        address = server.start()
        url = (
            f"{address.origin}/session/{address.session_token}/candidate/"
            "wizard-1/candidate-1"
        )
        with pytest.raises(HTTPError) as captured:
            urlopen(url, timeout=2)
        assert captured.value.code == 404
        current[0] = non_webp
        with pytest.raises(HTTPError) as captured:
            urlopen(url, timeout=2)
        assert captured.value.code == 404
    finally:
        server.stop()
