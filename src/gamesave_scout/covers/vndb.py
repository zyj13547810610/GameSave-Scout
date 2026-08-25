"""Bounded, rate-limited VNDB cover lookup with a restricted image host."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager, suppress
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Lock
from typing import Any, Protocol, cast
from urllib.parse import urlsplit
from uuid import uuid4

from gamesave_scout import __version__
from gamesave_scout.covers.candidate_images import stage_candidate_file
from gamesave_scout.covers.candidates import (
    MATCH_PRIORITY,
    CoverCandidate,
    CoverMatchKind,
    CoverProgress,
    match_cover_title,
)
from gamesave_scout.covers.image_pipeline import MAX_SOURCE_BYTES, InvalidCoverImage

VNDB_API_URL = "https://api.vndb.org/kana/vn"
VNDB_FIELDS = (
    "id,title,alttitle,titles{lang,title,latin,official,main},"
    "aliases,image{id,url,dims}"
)
USER_AGENT = f"GameSaveScout/{__version__}"
REQUEST_TIMEOUT_SECONDS = 20.0
MINIMUM_REQUEST_INTERVAL_SECONDS = 2.0
MAX_API_RESPONSE_BYTES = 8 * 1024 * 1024
DOWNLOAD_CHUNK_SIZE = 64 * 1024


class VndbError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class VndbResponse(Protocol):
    status: int
    headers: Mapping[str, str]

    def read(self, size: int = -1) -> bytes: ...

    def geturl(self) -> str: ...


class VndbTransport(Protocol):
    def open(
        self, request: urllib.request.Request, timeout: float
    ) -> AbstractContextManager[VndbResponse]: ...


@dataclass(frozen=True)
class VndbEntry:
    id: str
    title: str
    names: tuple[str, ...]
    image_url: str | None


@dataclass(frozen=True)
class VndbCoverResult:
    candidate: CoverCandidate
    entry_id: str


class VndbClient:
    def __init__(
        self,
        *,
        transport: VndbTransport | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        minimum_interval: float = MINIMUM_REQUEST_INTERVAL_SECONDS,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self._transport = transport or _UrllibTransport()
        self._monotonic = monotonic
        self._sleep = sleep
        self._minimum_interval = minimum_interval
        self._timeout = timeout
        self._request_lock = Lock()
        self._last_request_at: float | None = None
        self._last_warnings: tuple[str, ...] = ()

    @property
    def last_warnings(self) -> tuple[str, ...]:
        return self._last_warnings

    def search(
        self,
        title: str,
        limit: int,
        session_root: Path,
        game_id: str,
        context: CoverProgress,
    ) -> tuple[CoverCandidate, ...]:
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError("VNDB 封面候选数量必须为 1 到 20。")
        if not title.strip():
            raise ValueError("VNDB 查询标题不能为空。")

        warnings: list[str] = []
        entries = self._query(title, context, warnings)
        ranked = _rank_entries(title, entries)[:limit]
        candidates: list[CoverCandidate] = []
        for index, (entry, kind, score, matched) in enumerate(ranked, start=1):
            context.raise_if_cancelled()
            if entry.image_url is None:
                continue
            try:
                _validate_image_url(entry.image_url)
                candidate = self._download_candidate(
                    entry,
                    game_id,
                    session_root,
                    kind,
                    score,
                    matched,
                    context,
                )
            except (VndbError, InvalidCoverImage) as error:
                warnings.append(f"{entry.id}：{error}")
            else:
                candidates.append(candidate)
            context.report(
                index,
                len(ranked),
                f"正在获取 VNDB 封面：{entry.title}",
                details={"gameId": game_id, "vndbId": entry.id},
            )
        self._last_warnings = tuple(warnings)
        return tuple(candidates)

    def _query(
        self, title: str, context: CoverProgress, warnings: list[str]
    ) -> tuple[VndbEntry, ...]:
        payload = json.dumps(
            {
                "filters": ["search", "=", title],
                "fields": VNDB_FIELDS,
                "sort": "searchrank",
                "results": 20,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            VNDB_API_URL,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
            method="POST",
        )
        response_payload = self._request_api(request, context)
        try:
            raw = json.loads(response_payload.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise VndbError("invalid_response", "VNDB 返回了无效 JSON。") from error
        return _parse_entries(raw, warnings)

    def _request_api(
        self, request: urllib.request.Request, context: CoverProgress
    ) -> bytes:
        for attempt in range(2):
            try:
                with self._open(request, context) as response:
                    if response.status == 429 and attempt == 0:
                        retry_after = _retry_after(response.headers)
                    elif not 200 <= response.status < 300:
                        raise VndbError(
                            "network_error", f"VNDB 请求失败（HTTP {response.status}）。"
                        )
                    else:
                        return _read_bounded_response(
                            response, MAX_API_RESPONSE_BYTES, context
                        )
            except urllib.error.HTTPError as error:
                if error.code == 429 and attempt == 0:
                    retry_after = _retry_after(cast(Mapping[str, str], error.headers))
                else:
                    raise VndbError(
                        "network_error", f"VNDB 请求失败（HTTP {error.code}）。"
                    ) from error
            except (TimeoutError, OSError, urllib.error.URLError) as error:
                raise VndbError("network_error", "无法连接 VNDB。") from error
            if attempt == 0:
                self._wait(retry_after, context)
        raise VndbError("network_error", "VNDB 限流后重试仍然失败。")

    def _download_candidate(
        self,
        entry: VndbEntry,
        game_id: str,
        session_root: Path,
        kind: CoverMatchKind,
        score: float,
        matched: str,
        context: CoverProgress,
    ) -> CoverCandidate:
        assert entry.image_url is not None
        candidate_id = uuid4().hex
        source = session_root / "sources" / game_id / f"{candidate_id}.image"
        preview = session_root / "previews" / game_id / f"{candidate_id}.webp"
        part = source.with_name(f".{source.name}.part")
        request = urllib.request.Request(
            entry.image_url,
            headers={"Accept": "image/*", "User-Agent": USER_AGENT},
            method="GET",
        )
        source.parent.mkdir(parents=True, exist_ok=True)
        total = 0
        try:
            with self._open(request, context) as response:
                _validate_image_url(response.geturl())
                if not 200 <= response.status < 300:
                    raise VndbError(
                        "network_error", f"VNDB 图片下载失败（HTTP {response.status}）。"
                    )
                with part.open("wb") as stream:
                    while True:
                        context.raise_if_cancelled()
                        chunk = response.read(DOWNLOAD_CHUNK_SIZE)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > MAX_SOURCE_BYTES:
                            raise VndbError("image_too_large", "VNDB 图片超过 50 MiB。")
                        stream.write(chunk)
                    stream.flush()
                    os.fsync(stream.fileno())
            os.replace(part, source)
            staged = stage_candidate_file(source, preview)
        except VndbError:
            _cleanup_download(source, preview, part)
            raise
        except (TimeoutError, OSError, urllib.error.URLError) as error:
            _cleanup_download(source, preview, part)
            raise VndbError("network_error", "VNDB 图片下载失败。") from error
        except InvalidCoverImage:
            _cleanup_download(source, preview, part)
            raise
        finally:
            with suppress(OSError):
                part.unlink(missing_ok=True)

        file_ref = replace(staged.file_ref, temporary=True)
        return CoverCandidate(
            id=candidate_id,
            game_id=game_id,
            source="vndb",
            source_label="VNDB",
            display_name=entry.title,
            width=staged.width,
            height=staged.height,
            sha256=staged.sha256,
            match_kind=kind,
            score=score,
            evidence=("VNDB", f"匹配标题：{matched}"),
            file_ref=file_ref,
            preview_path=staged.preview_path,
            vndb_id=entry.id,
        )

    def _open(
        self, request: urllib.request.Request, context: CoverProgress
    ) -> AbstractContextManager[VndbResponse]:
        with self._request_lock:
            if self._last_request_at is not None:
                remaining = self._minimum_interval - (
                    self._monotonic() - self._last_request_at
                )
                if remaining > 0:
                    self._wait(remaining, context)
            context.raise_if_cancelled()
            self._last_request_at = self._monotonic()
            return self._transport.open(request, self._timeout)

    def _wait(self, seconds: float, context: CoverProgress) -> None:
        deadline = self._monotonic() + max(0.0, seconds)
        while True:
            context.raise_if_cancelled()
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                return
            self._sleep(min(0.1, remaining))


def _parse_entries(raw: object, warnings: list[str]) -> tuple[VndbEntry, ...]:
    if not isinstance(raw, dict) or not isinstance(raw.get("results"), list):
        raise VndbError("invalid_response", "VNDB 响应结构无效。")
    entries: list[VndbEntry] = []
    for index, item in enumerate(raw["results"]):
        try:
            entries.append(_parse_entry(item))
        except ValueError:
            warnings.append(f"VNDB 第 {index + 1} 条结果结构无效，已跳过。")
    return tuple(entries)


def _parse_entry(raw: object) -> VndbEntry:
    if not isinstance(raw, dict):
        raise ValueError
    entry_id = raw.get("id")
    title = raw.get("title")
    alttitle = raw.get("alttitle")
    titles = raw.get("titles", [])
    aliases = raw.get("aliases", [])
    image = raw.get("image")
    if not isinstance(entry_id, str) or not entry_id:
        raise ValueError
    if not isinstance(title, str) or not title:
        raise ValueError
    if alttitle is not None and not isinstance(alttitle, str):
        raise ValueError
    if not isinstance(titles, list) or not isinstance(aliases, list):
        raise ValueError
    if not all(isinstance(alias, str) for alias in aliases):
        raise ValueError

    names: list[str] = [title]
    if alttitle:
        names.append(alttitle)
    for localized in titles:
        if not isinstance(localized, dict):
            raise ValueError
        for key in ("title", "latin"):
            value = localized.get(key)
            if value is not None and not isinstance(value, str):
                raise ValueError
            if value:
                names.append(value)
    names.extend(cast(Sequence[str], aliases))

    image_url: str | None = None
    if image is not None:
        if not isinstance(image, dict):
            raise ValueError
        value = image.get("url")
        if value is not None and not isinstance(value, str):
            raise ValueError
        image_url = value
    return VndbEntry(entry_id, title, tuple(dict.fromkeys(names)), image_url)


def _rank_entries(
    query: str, entries: Sequence[VndbEntry]
) -> list[tuple[VndbEntry, CoverMatchKind, float, str]]:
    ranked: list[tuple[VndbEntry, CoverMatchKind, float, str, int]] = []
    for index, entry in enumerate(entries):
        if entry.image_url is None:
            continue
        kind, score, matched = match_cover_title(query, entry.names)
        ranked.append((entry, kind, score, matched, index))
    ranked.sort(key=lambda item: (MATCH_PRIORITY[item[1]], -item[2], item[4]))
    return [(entry, kind, score, matched) for entry, kind, score, matched, _ in ranked]


def _validate_image_url(url: str) -> None:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise VndbError("unsafe_image_url", "VNDB 图片地址无效。") from error
    if (
        parsed.scheme != "https"
        or parsed.hostname != "t.vndb.org"
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
    ):
        raise VndbError("unsafe_image_url", "VNDB 图片地址不受信任。")


def _read_bounded_response(
    response: VndbResponse, limit: int, context: CoverProgress
) -> bytes:
    payload = bytearray()
    while True:
        context.raise_if_cancelled()
        chunk = response.read(min(DOWNLOAD_CHUNK_SIZE, limit + 1 - len(payload)))
        if not chunk:
            return bytes(payload)
        payload.extend(chunk)
        if len(payload) > limit:
            raise VndbError("invalid_response", "VNDB 响应过大。")


def _retry_after(headers: Mapping[str, str]) -> float:
    value = next(
        (header for key, header in headers.items() if key.casefold() == "retry-after"),
        "2",
    )
    try:
        return float(min(max(int(value), 0), 60))
    except (TypeError, ValueError):
        return 2.0


def _cleanup_download(source: Path, preview: Path, part: Path) -> None:
    for path in (source, preview, part):
        with suppress(OSError):
            path.unlink(missing_ok=True)


class _RestrictedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        if req.full_url != VNDB_API_URL:
            _validate_image_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _UrllibTransport:
    def __init__(self) -> None:
        self._opener = urllib.request.build_opener(_RestrictedRedirectHandler())

    def open(
        self, request: urllib.request.Request, timeout: float
    ) -> AbstractContextManager[VndbResponse]:
        return cast(
            AbstractContextManager[VndbResponse],
            self._opener.open(request, timeout=timeout),
        )
