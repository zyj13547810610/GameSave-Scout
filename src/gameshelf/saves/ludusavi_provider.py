"""Validated offline snapshot and explicit-only Ludusavi updates."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import threading
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
type ProgressReporter = Callable[[str], None]


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


@dataclass(frozen=True, slots=True)
class SnapshotPair:
    manifest: Path
    metadata: Path


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
        self._lock = threading.RLock()

    def ensure_initial_snapshot(self) -> None:
        with self._lock:
            self.active_dir.mkdir(parents=True, exist_ok=True)
            self.temp_dir.mkdir(parents=True, exist_ok=True)
            self.previous_dir.mkdir(parents=True, exist_ok=True)
            active = SnapshotPair(self.active_manifest, self.active_metadata)
            try:
                self._validate_pair(active, allow_crlf_repair=False)
                return
            except SnapshotUpdateError:
                pass

            if self._restore_latest_valid_backup():
                return

            resource = SnapshotPair(
                self.resource_dir / "manifest.yaml",
                self.resource_dir / "manifest-meta.json",
            )
            try:
                _, manifest_bytes = self._validate_pair(
                    resource,
                    allow_crlf_repair=True,
                )
            except SnapshotUpdateError as error:
                raise SnapshotUpdateError(
                    f"缺少有效的内置 Ludusavi 清单或元数据：{error}"
                ) from error
            self._install_pair_bytes(manifest_bytes, resource.metadata.read_bytes())

    def load(self) -> LudusaviManifest:
        with self._lock:
            self.ensure_initial_snapshot()
            with self.active_manifest.open(encoding="utf-8") as stream:
                return parse_manifest(stream, skip_invalid_paths=True)

    def metadata(self) -> SnapshotMetadata:
        with self._lock:
            self.ensure_initial_snapshot()
            return _read_metadata(self.active_metadata)

    def update_explicitly(
        self,
        report: ProgressReporter | None = None,
    ) -> UpdateResult:
        with self._lock:
            try:
                self.ensure_initial_snapshot()
                current: SnapshotMetadata | None = _read_metadata(
                    self.active_metadata
                )
            except SnapshotUpdateError:
                current = None
            headers = {"User-Agent": "GameShelf/0.1 Ludusavi snapshot updater"}
            if current is not None and current.etag:
                headers["If-None-Match"] = current.etag
            _report(report, "connecting")
            try:
                response = self._http_open(
                    self.update_url,
                    headers,
                    DOWNLOAD_TIMEOUT_SECONDS,
                )
                with response:
                    if response.status == 304:
                        if current is None:
                            return UpdateResult(
                                "failed",
                                _failure_message(
                                    "服务器返回未修改，但本地没有可用清单。",
                                    current,
                                ),
                                current,
                            )
                        return UpdateResult(
                            "not_modified",
                            "Ludusavi 清单已是最新。",
                            current,
                        )
                    if response.status != 200:
                        return UpdateResult(
                            "failed",
                            _failure_message(
                                f"Ludusavi 服务器返回 HTTP {response.status}。",
                                current,
                            ),
                            current,
                        )
                    length = _content_length(response)
                    if length is not None and length > MAX_DOWNLOAD_BYTES:
                        return UpdateResult(
                            "invalid",
                            "下载内容超过 64 MiB 限制。",
                            current,
                        )
                    etag = response.getheader("ETag")
                    return self._download_and_replace(
                        response,
                        current,
                        etag,
                        report,
                    )
            except (OSError, urllib.error.URLError) as error:
                return UpdateResult(
                    "failed",
                    _failure_message(f"无法下载 Ludusavi 清单：{error}", current),
                    current,
                )

    def _download_and_replace(
        self,
        response: HttpResponse,
        current: SnapshotMetadata | None,
        etag: str | None,
        report: ProgressReporter | None,
    ) -> UpdateResult:
        download = self.temp_dir / f"ludusavi-download-{uuid4().hex}.yaml"
        metadata_temporary = self.temp_dir / f"ludusavi-metadata-{uuid4().hex}.json"
        digest = hashlib.sha256()
        total = 0
        try:
            _report(report, "downloading")
            with download.open("xb") as stream:
                while chunk := response.read(_CHUNK_BYTES):
                    total += len(chunk)
                    if total > MAX_DOWNLOAD_BYTES:
                        return UpdateResult("invalid", "下载内容超过 64 MiB 限制。", current)
                    digest.update(chunk)
                    stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
            downloaded_sha256 = digest.hexdigest()
            if _sha256_file(download) != downloaded_sha256:
                return UpdateResult(
                    "invalid",
                    "下载内容落盘后的 SHA-256 校验失败。",
                    current,
                )
            _report(report, "validating")
            try:
                _validate_manifest_file(download)
            except (InvalidLudusaviManifest, UnicodeError) as error:
                return UpdateResult("invalid", f"下载的清单无效：{error}", current)

            metadata = SnapshotMetadata(
                etag=etag,
                sha256=downloaded_sha256,
                downloaded_at=_utc_now(),
                source_url=self.update_url,
                upstream_commit=None,
            )
            backup = self._backup_active_pair()
            try:
                _write_bytes_fsynced(
                    metadata_temporary,
                    _metadata_json_bytes(metadata),
                )
                _report(report, "replacing")
                self._replace_pair(download, metadata_temporary, backup)
            except (OSError, SnapshotUpdateError) as error:
                return UpdateResult(
                    "failed",
                    _failure_message(f"替换清单失败：{error}", current),
                    current,
                )
            self._prune_previous()
            return UpdateResult("updated", "Ludusavi 清单已更新。", metadata)
        finally:
            with suppress(OSError):
                download.unlink(missing_ok=True)
            with suppress(OSError):
                metadata_temporary.unlink(missing_ok=True)

    def _replace_pair(
        self,
        new_manifest: Path,
        new_metadata: Path,
        backup: SnapshotPair | None,
    ) -> None:
        try:
            os.replace(new_manifest, self.active_manifest)
            os.replace(new_metadata, self.active_metadata)
            self._validate_pair(
                SnapshotPair(self.active_manifest, self.active_metadata),
                allow_crlf_repair=False,
            )
        except (OSError, SnapshotUpdateError) as error:
            with suppress(OSError):
                self.active_manifest.unlink(missing_ok=True)
            with suppress(OSError):
                self.active_metadata.unlink(missing_ok=True)
            if backup is not None:
                try:
                    _, manifest_bytes = self._validate_pair(
                        backup,
                        allow_crlf_repair=False,
                    )
                    self._install_pair_bytes(
                        manifest_bytes,
                        backup.metadata.read_bytes(),
                    )
                except (OSError, SnapshotUpdateError) as restore_error:
                    raise SnapshotUpdateError(
                        "新清单替换失败，旧清单恢复也失败。"
                    ) from restore_error
            raise SnapshotUpdateError("新清单替换失败，已恢复旧清单。") from error

    def _validate_pair(
        self,
        pair: SnapshotPair,
        *,
        allow_crlf_repair: bool,
    ) -> tuple[SnapshotMetadata, bytes]:
        if not pair.manifest.is_file() or not pair.metadata.is_file():
            raise SnapshotUpdateError("Ludusavi 清单文件组不完整。")
        metadata = _read_metadata(pair.metadata)
        manifest_bytes = _validated_manifest_bytes(
            pair.manifest,
            metadata.sha256,
            allow_crlf_repair=allow_crlf_repair,
        )
        _validate_manifest_bytes(manifest_bytes)
        return metadata, manifest_bytes

    def _backup_active_pair(self) -> SnapshotPair | None:
        with self._lock:
            active = SnapshotPair(self.active_manifest, self.active_metadata)
            try:
                self._validate_pair(active, allow_crlf_repair=False)
            except SnapshotUpdateError:
                return None
            self.previous_dir.mkdir(parents=True, exist_ok=True)
            key = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}"
            backup = SnapshotPair(
                self.previous_dir / f"manifest-{key}.yaml",
                self.previous_dir / f"manifest-{key}.json",
            )
            try:
                shutil.copy2(active.manifest, backup.manifest)
                shutil.copy2(active.metadata, backup.metadata)
            except OSError:
                with suppress(OSError):
                    backup.manifest.unlink(missing_ok=True)
                with suppress(OSError):
                    backup.metadata.unlink(missing_ok=True)
                raise
            return backup

    def _restore_pair(self, pair: SnapshotPair) -> bool:
        try:
            _, manifest_bytes = self._validate_pair(
                pair,
                allow_crlf_repair=False,
            )
            self._install_pair_bytes(manifest_bytes, pair.metadata.read_bytes())
        except (OSError, SnapshotUpdateError):
            return False
        return True

    def _restore_latest_valid_backup(self) -> bool:
        return any(self._restore_pair(pair) for pair in self._previous_pairs())

    def _previous_pairs(self) -> list[SnapshotPair]:
        pairs: list[SnapshotPair] = []
        for manifest in self.previous_dir.glob("manifest-*.yaml"):
            metadata = manifest.with_suffix(".json")
            if metadata.is_file():
                pairs.append(SnapshotPair(manifest, metadata))
        return sorted(
            pairs,
            key=lambda pair: (
                max(pair.manifest.stat().st_mtime_ns, pair.metadata.stat().st_mtime_ns),
                pair.manifest.name,
            ),
            reverse=True,
        )

    def _prune_previous(self) -> None:
        pairs = self._previous_pairs()
        keep = {
            path
            for pair in pairs[:2]
            for path in (pair.manifest, pair.metadata)
        }
        for path in self.previous_dir.glob("manifest-*.*"):
            if path not in keep and path.suffix in {".yaml", ".json"}:
                path.unlink()

    def _install_pair_bytes(self, manifest_bytes: bytes, metadata_bytes: bytes) -> None:
        manifest_temporary = self.temp_dir / f"manifest-{uuid4().hex}.tmp"
        metadata_temporary = self.temp_dir / f"metadata-{uuid4().hex}.tmp"
        replaced_manifest = False
        try:
            _write_bytes_fsynced(manifest_temporary, manifest_bytes)
            _write_bytes_fsynced(metadata_temporary, metadata_bytes)
            os.replace(manifest_temporary, self.active_manifest)
            replaced_manifest = True
            os.replace(metadata_temporary, self.active_metadata)
        except OSError:
            if replaced_manifest:
                with suppress(OSError):
                    self.active_manifest.unlink(missing_ok=True)
                with suppress(OSError):
                    self.active_metadata.unlink(missing_ok=True)
            raise
        finally:
            with suppress(OSError):
                manifest_temporary.unlink(missing_ok=True)
            with suppress(OSError):
                metadata_temporary.unlink(missing_ok=True)

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


def _report(reporter: ProgressReporter | None, stage: str) -> None:
    if reporter is not None:
        reporter(stage)


def _failure_message(detail: str, current: SnapshotMetadata | None) -> str:
    suffix = (
        "当前有效清单仍可使用。"
        if current is not None
        else "当前没有可用的 Ludusavi 官方清单。"
    )
    return f"{detail}{suffix}"


def _validate_manifest_file(path: Path) -> None:
    with path.open(encoding="utf-8") as stream:
        parse_manifest(stream, skip_invalid_paths=True)


def _validate_manifest_bytes(content: bytes) -> None:
    try:
        parse_manifest(io.StringIO(content.decode("utf-8")), skip_invalid_paths=True)
    except (InvalidLudusaviManifest, UnicodeError) as error:
        raise SnapshotUpdateError(f"Ludusavi 清单内容无效：{error}") from error


def _validated_manifest_bytes(
    path: Path,
    expected_sha256: str,
    *,
    allow_crlf_repair: bool,
) -> bytes:
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() == expected_sha256:
        return content
    if allow_crlf_repair:
        normalized = content.replace(b"\r\n", b"\n")
        if (
            normalized != content
            and hashlib.sha256(normalized).hexdigest() == expected_sha256
        ):
            return normalized
    raise SnapshotUpdateError("Ludusavi 清单的 SHA-256 与元数据不一致。")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _write_bytes_fsynced(path: Path, content: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


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


def _metadata_json_bytes(metadata: SnapshotMetadata) -> bytes:
    data = {
        "etag": metadata.etag,
        "sha256": metadata.sha256,
        "downloadedAt": metadata.downloaded_at,
        "sourceUrl": metadata.source_url,
        "upstreamCommit": metadata.upstream_commit,
    }
    return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
