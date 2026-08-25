from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.request import Request

import pytest
from PIL import Image

from gameshelf.covers import vndb
from gameshelf.covers.vndb import VndbClient, VndbError


class _Response:
    def __init__(
        self,
        payload: bytes,
        *,
        status: int = 200,
        headers: Mapping[str, str] | None = None,
        url: str = "https://api.vndb.org/kana/vn",
    ) -> None:
        self._stream = BytesIO(payload)
        self.status = status
        self.headers = headers or {}
        self._url = url

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def geturl(self) -> str:
        return self._url

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: object) -> None:
        return None


@dataclass
class _Transport:
    responses: list[_Response | BaseException]
    now: Callable[[], float] | None = None
    requests: list[Request] = field(default_factory=list)
    opened_at: list[float] = field(default_factory=list)

    def open(self, request: Request, timeout: float) -> _Response:
        del timeout
        self.requests.append(request)
        if self.now is not None:
            self.opened_at.append(self.now())
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


@dataclass
class _Progress:
    checks: int = 0

    def report(
        self,
        completed: int,
        total: int | None,
        message: str,
        *,
        details: object = None,
    ) -> None:
        del completed, total, message, details

    def raise_if_cancelled(self) -> None:
        self.checks += 1


def _image_bytes() -> bytes:
    stream = BytesIO()
    Image.new("RGB", (400, 600), (40, 70, 100)).save(stream, "JPEG")
    return stream.getvalue()


def _api_response(results: list[dict[str, Any]]) -> _Response:
    return _Response(json.dumps({"results": results}).encode())


def _entry(
    entry_id: str = "v17", *, title: str = "千恋＊万花", url: str = "https://t.vndb.org/cv/17.jpg"
) -> dict[str, Any]:
    return {
        "id": entry_id,
        "title": title,
        "alttitle": "Senren Banka",
        "titles": [
            {
                "lang": "ja",
                "title": "千恋＊万花",
                "latin": "Senren Banka",
                "official": True,
                "main": True,
            }
        ],
        "aliases": ["千恋万花"],
        "image": {"id": "cv17", "url": url, "dims": [400, 600]},
    }


def test_search_sends_exact_post_contract_and_builds_candidate(tmp_path: Path) -> None:
    transport = _Transport(
        [
            _api_response([_entry()]),
            _Response(_image_bytes(), url="https://t.vndb.org/cv/17.jpg"),
        ]
    )
    client = VndbClient(transport=transport, sleep=lambda _: None, minimum_interval=0)

    candidates = client.search("千恋＊万花", 5, tmp_path, "game-1", _Progress())

    request = transport.requests[0]
    assert request.full_url == "https://api.vndb.org/kana/vn"
    assert request.method == "POST"
    assert json.loads(request.data or b"") == {
        "filters": ["search", "=", "千恋＊万花"],
        "fields": (
            "id,title,alttitle,titles{lang,title,latin,official,main},"
            "aliases,image{id,url,dims}"
        ),
        "sort": "searchrank",
        "results": 20,
    }
    assert request.get_header("Content-type") == "application/json"
    assert request.get_header("Accept") == "application/json"
    assert request.get_header("User-agent") == "GameShelf/0.3.2"
    assert len(candidates) == 1
    assert candidates[0].source == "vndb"
    assert candidates[0].vndb_id == "v17"
    assert candidates[0].file_ref.temporary is True


def test_invalid_entries_are_skipped_but_invalid_root_fails(tmp_path: Path) -> None:
    transport = _Transport(
        [
            _api_response([{"id": 17}, _entry()]),
            _Response(_image_bytes(), url="https://t.vndb.org/cv/17.jpg"),
        ]
    )
    client = VndbClient(transport=transport, sleep=lambda _: None, minimum_interval=0)

    assert len(client.search("千恋＊万花", 5, tmp_path, "game-1", _Progress())) == 1
    assert len(client.last_warnings) == 1

    invalid = VndbClient(
        transport=_Transport([_Response(b"[]")]), sleep=lambda _: None, minimum_interval=0
    )
    with pytest.raises(VndbError) as captured:
        invalid.search("Alice", 5, tmp_path, "game-1", _Progress())
    assert captured.value.code == "invalid_response"


def test_local_matching_beats_api_order_before_limit(tmp_path: Path) -> None:
    transport = _Transport(
        [
            _api_response(
                [
                    _entry("v1", title="Something Else", url="https://t.vndb.org/cv/1.jpg"),
                    _entry("v2", title="Alice", url="https://t.vndb.org/cv/2.jpg"),
                ]
            ),
            _Response(_image_bytes(), url="https://t.vndb.org/cv/2.jpg"),
        ]
    )

    candidates = VndbClient(
        transport=transport, sleep=lambda _: None, minimum_interval=0
    ).search(
        "Alice", 1, tmp_path, "game-1", _Progress()
    )

    assert [item.vndb_id for item in candidates] == ["v2"]


def test_shared_rate_limit_waits_in_cancellable_slices(tmp_path: Path) -> None:
    now = [0.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    transport = _Transport([_api_response([]), _api_response([])], now=lambda: now[0])
    client = VndbClient(transport=transport, monotonic=lambda: now[0], sleep=sleep)
    progress = _Progress()

    client.search("Alice", 1, tmp_path, "game-1", progress)
    client.search("Bob", 1, tmp_path, "game-2", progress)

    assert transport.opened_at[1] - transport.opened_at[0] >= 2.0
    assert sleeps
    assert max(sleeps) <= 0.1
    assert progress.checks >= len(sleeps)


def test_429_retries_once_and_caps_retry_after(tmp_path: Path) -> None:
    now = [0.0]

    def sleep(seconds: float) -> None:
        now[0] += seconds

    transport = _Transport(
        [
            _Response(b"", status=429, headers={"Retry-After": "90"}),
            _api_response([]),
        ],
        now=lambda: now[0],
    )
    client = VndbClient(transport=transport, monotonic=lambda: now[0], sleep=sleep)

    client.search("Alice", 1, tmp_path, "game-1", _Progress())

    assert len(transport.requests) == 2
    assert now[0] >= 60


def test_429_wait_is_cooperatively_cancellable_before_retry(tmp_path: Path) -> None:
    class Cancelled(RuntimeError):
        pass

    class CancellingProgress(_Progress):
        def raise_if_cancelled(self) -> None:
            super().raise_if_cancelled()
            if self.checks >= 2:
                raise Cancelled

    transport = _Transport(
        [
            _Response(b"", status=429, headers={"Retry-After": "60"}),
            _api_response([]),
        ]
    )
    client = VndbClient(transport=transport, sleep=lambda _: None)

    with pytest.raises(Cancelled):
        client.search("Alice", 1, tmp_path, "game-1", CancellingProgress())

    assert len(transport.requests) == 1


@pytest.mark.parametrize(
    "url",
    [
        "http://t.vndb.org/cv/1.jpg",
        "https://example.com/cv/1.jpg",
        "https://user@t.vndb.org/cv/1.jpg",
        "https://127.0.0.1/cv/1.jpg",
        "https://t.vndb.org:444/cv/1.jpg",
    ],
)
def test_unsafe_image_urls_are_rejected_without_downloading(
    tmp_path: Path, url: str
) -> None:
    transport = _Transport([_api_response([_entry(url=url)])])
    client = VndbClient(transport=transport, sleep=lambda _: None, minimum_interval=0)

    assert client.search("千恋＊万花", 5, tmp_path, "game-1", _Progress()) == ()
    assert len(transport.requests) == 1
    assert client.last_warnings


def test_oversized_download_is_removed_and_other_results_continue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(vndb, "MAX_SOURCE_BYTES", 10)
    transport = _Transport(
        [
            _api_response([_entry()]),
            _Response(b"x" * 11, url="https://t.vndb.org/cv/17.jpg"),
        ]
    )
    client = VndbClient(transport=transport, sleep=lambda _: None, minimum_interval=0)

    assert client.search("千恋＊万花", 5, tmp_path, "game-1", _Progress()) == ()
    assert not tuple(tmp_path.rglob("*.part"))
    assert not tuple((tmp_path / "sources").rglob("*.*"))
    assert client.last_warnings


def test_query_timeout_has_stable_network_error(tmp_path: Path) -> None:
    client = VndbClient(
        transport=_Transport([TimeoutError("offline")]),
        sleep=lambda _: None,
        minimum_interval=0,
    )

    with pytest.raises(VndbError) as captured:
        client.search("Alice", 5, tmp_path, "game-1", _Progress())

    assert captured.value.code == "network_error"
