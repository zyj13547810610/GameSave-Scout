"""Validated offline snapshot and explicit-only Ludusavi updates."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol, cast
from urllib.parse import urlparse
from uuid import uuid4

from gameshelf.saves.ludusavi_models import LudusaviManifest
from gameshelf.saves.ludusavi_parser import InvalidLudusaviManifest, parse_manifest

MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
DOWNLOAD_TIMEOUT_SECONDS = 30.0
_CHUNK_BYTES = 1024 * 1024


class SnapshotUpdateError(RuntimeError):
    """Snapshot setup or update configuration is invalid."""


class HttpResponse(Protocol):
    status: int

    def read(self, size: int = -1) -> bytes: ...

    def getheader(self, name: str, default: str | None = None) -> str | None: ...

    def __enter__(self) -> HttpResponse: ...

    def __exit__(self, *args: object) -> object: ...


type HttpOpen = Callable[[str, dict[str, str], float], HttpResponse]
type UpdateStatus = Literal["updated", "not_modified", "invalid", "failed"]


@dataclass(frozen=True, slots=True)
class SnapshotMetadata:
    etag: str | None
    sha256: str
    downloaded_at: str
    source_url: str
    upstream_commit: str | None


@dataclass(frozen=True, slots=True)
class UpdateResult:
    status: UpdateStatus
    message: str
    metadata: SnapshotMetadata | None


class LudusaviProvider:
    UPDATE_URL = (
        "https://raw.githubusercontent.com/mtkennerly/"
        "ludusavi-manifest/master/data/manifest.yaml"
    )

    def __init__(
        self,
        *,
        resource_dir: Path,
        active_dir: Path,
        temp_dir: Path,
        update_url: str = UPDATE_URL,
        http_open: HttpOpen | None = None,
    ) -> None:
        if urlparse(update_url).scheme.casefold() != "https":
            raise SnapshotUpdateError("Ludusavi 更新地址必须使用 HTTPS。")
        self.resource_dir = resource_dir
        self.active_dir = active_dir
        self.temp_dir = temp_dir
        self.update_url = update_url
        self.active_manifest = active_dir / "manifest.yaml"
        self.active_metadata = active_dir / "manifest-meta.json"
        self.previous_dir = active_dir / "previous"
        self._http_open = http_open or _urllib_open

    def ensure_initial_snapshot(self) -> None:
        self.active_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.previous_dir.mkdir(parents=True, exist_ok=True)
        if self.active_manifest.is_file() and self.active_metadata.is_file():
            return

        resource_manifest = self.resource_dir / "manifest.yaml"
        resource_metadata = self.resource_dir / "manifest-meta.json"
        if not resource_manifest.is_file() or not resource_metadata.is_file():
            raise SnapshotUpdateError("缺少内置 Ludusavi 清单或元数据。")
        metadata = _read_metadata(resource_metadata)
        if _sha256_file(resource_manifest) != metadata.sha256:
            raise SnapshotUpdateError("内置 Ludusavi 清单的 SHA-256 与元数据不一致。")
        self._atomic_copy(resource_manifest, self.active_manifest)
        self._atomic_copy(resource_metadata, self.active_metadata)

    def load(self) -> LudusaviManifest:
        self.ensure_initial_snapshot()
        with self.active_manifest.open(encoding="utf-8") as stream:
            return parse_manifest(stream, skip_invalid_paths=True)

    def metadata(self) -> SnapshotMetadata:
        self.ensure_initial_snapshot()
        return _read_metadata(self.active_metadata)

    def update_explicitly(self) -> UpdateResult:
        self.ensure_initial_snapshot()
        current = self.metadata()
        headers = {"User-Agent": "GameShelf/0.1 Ludusavi snapshot updater"}
        if current.etag:
            headers["If-None-Match"] = current.etag
        try:
            response = self._http_open(
                self.update_url,
                headers,
                DOWNLOAD_TIMEOUT_SECONDS,
            )
            with response:
                if response.status == 304:
                    return UpdateResult("not_modified", "Ludusavi 清单已是最新。", current)
                if response.status != 200:
                    return UpdateResult(
                        "failed",
                        f"Ludusavi 服务器返回 HTTP {response.status}。",
                        current,
                    )
                length = _content_length(response)
                if length is not None and length > MAX_DOWNLOAD_BYTES:
                    return UpdateResult("invalid", "下载内容超过 64 MiB 限制。", current)
                etag = response.getheader("ETag")
                return self._download_and_replace(response, current, etag)
        except (OSError, urllib.error.URLError) as error:
            return UpdateResult("failed", f"无法下载 Ludusavi 清单：{error}", current)

    def _download_and_replace(
        self,
        response: HttpResponse,
        current: SnapshotMetadata,
        etag: str | None,
    ) -> UpdateResult:
        download = self.temp_dir / f"ludusavi-download-{uuid4().hex}.yaml"
        digest = hashlib.sha256()
        total = 0
        try:
            with download.open("xb") as stream:
                while chunk := response.read(_CHUNK_BYTES):
                    total += len(chunk)
                    if total > MAX_DOWNLOAD_BYTES:
                        return UpdateResult("invalid", "下载内容超过 64 MiB 限制。", current)
                    digest.update(chunk)
                    stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                _validate_manifest_file(download)
            except (InvalidLudusaviManifest, UnicodeError) as error:
                return UpdateResult("invalid", f"下载的清单无效：{error}", current)

            metadata = SnapshotMetadata(
                etag=etag,
                sha256=digest.hexdigest(),
                downloaded_at=_utc_now(),
                source_url=self.update_url,
                upstream_commit=None,
            )
            backup = self._backup_active()
            try:
                os.replace(download, self.active_manifest)
                _write_metadata_atomic(self.active_metadata, metadata, self.temp_dir)
            except OSError as error:
                self._restore_backup(backup)
                return UpdateResult("failed", f"替换清单失败，已恢复旧版本：{error}", current)
            self._prune_previous()
            return UpdateResult("updated", "Ludusavi 清单已更新。", metadata)
        finally:
            with suppress(OSError):
                download.unlink(missing_ok=True)

    def _backup_active(self) -> Path:
        self.previous_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup = self.previous_dir / f"manifest-{stamp}-{uuid4().hex[:8]}.yaml"
        shutil.copy2(self.active_manifest, backup)
        return backup

    def _restore_backup(self, backup: Path) -> None:
        rollback = self.temp_dir / f"ludusavi-rollback-{uuid4().hex}.yaml"
        with suppress(OSError):
            shutil.copy2(backup, rollback)
            os.replace(rollback, self.active_manifest)
        with suppress(OSError):
            rollback.unlink(missing_ok=True)

    def _prune_previous(self) -> None:
        backups = sorted(
            self.previous_dir.glob("manifest-*.yaml"),
            key=lambda path: (path.stat().st_mtime_ns, path.name),
            reverse=True,
        )
        for old in backups[2:]:
            old.unlink()

    def _atomic_copy(self, source: Path, destination: Path) -> None:
        temporary = self.temp_dir / f"copy-{uuid4().hex}.tmp"
        try:
            shutil.copy2(source, temporary)
            os.replace(temporary, destination)
        finally:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)


def _urllib_open(url: str, headers: dict[str, str], timeout: float) -> HttpResponse:
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        return cast(HttpResponse, urllib.request.urlopen(request, timeout=timeout))
    except urllib.error.HTTPError as error:
        if error.code == 304:
            return cast(HttpResponse, error)
        raise


def _content_length(response: HttpResponse) -> int | None:
    raw = response.getheader("Content-Length")
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _validate_manifest_file(path: Path) -> None:
    with path.open(encoding="utf-8") as stream:
        parse_manifest(stream, skip_invalid_paths=True)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _read_metadata(path: Path) -> SnapshotMetadata:
    try:
        loaded: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SnapshotUpdateError(f"无法读取 Ludusavi 元数据：{path}") from error
    if not isinstance(loaded, dict):
        raise SnapshotUpdateError("Ludusavi 元数据必须是 JSON 对象。")
    data = cast(Mapping[str, Any], loaded)
    sha256 = data.get("sha256")
    downloaded_at = data.get("downloadedAt")
    source_url = data.get("sourceUrl")
    etag = data.get("etag")
    upstream_commit = data.get("upstreamCommit")
    if (
        not isinstance(sha256, str)
        or re_full_sha256(sha256) is False
        or not isinstance(downloaded_at, str)
        or not isinstance(source_url, str)
        or (etag is not None and not isinstance(etag, str))
        or (upstream_commit is not None and not isinstance(upstream_commit, str))
    ):
        raise SnapshotUpdateError("Ludusavi 元数据字段无效。")
    return SnapshotMetadata(etag, sha256, downloaded_at, source_url, upstream_commit)


def re_full_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _write_metadata_atomic(
    destination: Path,
    metadata: SnapshotMetadata,
    temp_dir: Path,
) -> None:
    temporary = temp_dir / f"metadata-{uuid4().hex}.json"
    data = {
        "etag": metadata.etag,
        "sha256": metadata.sha256,
        "downloadedAt": metadata.downloaded_at,
        "sourceUrl": metadata.source_url,
        "upstreamCommit": metadata.upstream_commit,
    }
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
