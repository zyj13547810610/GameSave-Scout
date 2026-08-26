"""Validated bundled fallback and explicit-only Ludusavi updates."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol, cast
from urllib.parse import urlparse
from uuid import uuid4

from gamesave_scout.saves.ludusavi_index import InvalidLudusaviIndex, LudusaviIndex
from gamesave_scout.saves.ludusavi_index_builder import build_ludusavi_index
from gamesave_scout.saves.ludusavi_models import LudusaviManifest
from gamesave_scout.saves.ludusavi_parser import InvalidLudusaviManifest, parse_manifest

MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
DOWNLOAD_TIMEOUT_SECONDS = 30.0
_CHUNK_BYTES = 1024 * 1024


class SnapshotUpdateError(RuntimeError):
    """Snapshot setup, selection, update, or restore failed safely."""


class HttpResponse(Protocol):
    status: int

    def read(self, size: int = -1) -> bytes: ...

    def getheader(self, name: str, default: str | None = None) -> str | None: ...

    def __enter__(self) -> HttpResponse: ...

    def __exit__(self, *args: object) -> object: ...


type HttpOpen = Callable[[str, dict[str, str], float], HttpResponse]
type UpdateStatus = Literal["updated", "not_modified", "invalid", "failed"]
type ProgressReporter = Callable[[str], None]
type SnapshotSource = Literal["bundled", "active"]


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
class SnapshotBundle:
    manifest: Path
    metadata: Path
    index: Path


@dataclass(frozen=True, slots=True)
class LudusaviStatus:
    available: bool
    source: SnapshotSource | None
    metadata: SnapshotMetadata | None
    bundled_sha256: str | None
    unavailable_reason: str | None


@dataclass(frozen=True, slots=True)
class _SelectedBundle:
    source: SnapshotSource
    bundle: SnapshotBundle
    metadata: SnapshotMetadata


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
        self.active_index = active_dir / "manifest-index.sqlite"
        self._bundled = SnapshotBundle(
            resource_dir / "manifest.yaml",
            resource_dir / "manifest-meta.json",
            resource_dir / "manifest-index.sqlite",
        )
        self._active = SnapshotBundle(
            self.active_manifest,
            self.active_metadata,
            self.active_index,
        )
        self._http_open = http_open or _urllib_open
        self._lock = threading.RLock()

    def ensure_initial_snapshot(self) -> None:
        """Compatibility guard that validates availability without copying resources."""
        status = self.status()
        if not status.available:
            raise SnapshotUpdateError(
                status.unavailable_reason or "没有可用的 Ludusavi 清单。"
            )

    def status(self) -> LudusaviStatus:
        with self._lock:
            self._prepare_directories()
            bundled_sha256 = self._bundled_sha256()
            try:
                selected = self._select_bundle(rebuild_active_index=False)
            except SnapshotUpdateError as error:
                return LudusaviStatus(
                    available=False,
                    source=None,
                    metadata=None,
                    bundled_sha256=bundled_sha256,
                    unavailable_reason=str(error),
                )
            return LudusaviStatus(
                available=True,
                source=selected.source,
                metadata=selected.metadata,
                bundled_sha256=bundled_sha256,
                unavailable_reason=None,
            )

    def metadata(self) -> SnapshotMetadata:
        status = self.status()
        if not status.available or status.metadata is None:
            raise SnapshotUpdateError(
                status.unavailable_reason or "没有可用的 Ludusavi 清单。"
            )
        return status.metadata

    @contextmanager
    def index_session(self) -> Iterator[LudusaviIndex]:
        with self._lock:
            self._prepare_directories()
            selected = self._select_bundle(rebuild_active_index=True)
            try:
                index = LudusaviIndex.open(
                    selected.bundle.index,
                    manifest_sha256=selected.metadata.sha256,
                )
            except InvalidLudusaviIndex as error:
                raise SnapshotUpdateError("Ludusavi 索引不可用。") from error
            yield index

    def restore_bundled(self) -> LudusaviStatus:
        with self._lock:
            self._prepare_directories()
            self._validate_bundled()
            backups: dict[Path, Path] = {}
            try:
                for target in self._active_paths():
                    if not target.exists():
                        continue
                    backup = self.temp_dir / f"restore-{uuid4().hex}-{target.name}"
                    _copy_file_fsynced(target, backup)
                    backups[target] = backup
            except OSError as error:
                for backup in backups.values():
                    with suppress(OSError):
                        backup.unlink(missing_ok=True)
                raise SnapshotUpdateError(
                    "恢复随包 Ludusavi 版本失败，无法建立活动文件临时副本。"
                ) from error
            try:
                for target in self._active_paths():
                    target.unlink(missing_ok=True)
            except OSError as error:
                restore_errors = self._restore_copies(backups)
                message = (
                    "恢复随包 Ludusavi 版本失败，活动文件恢复也失败。"
                    if restore_errors
                    else "恢复随包 Ludusavi 版本失败，活动文件已恢复。"
                )
                raise SnapshotUpdateError(message) from error
            finally:
                for backup in backups.values():
                    with suppress(OSError):
                        backup.unlink(missing_ok=True)
            selected = self._select_bundle(rebuild_active_index=False)
            return LudusaviStatus(
                available=True,
                source=selected.source,
                metadata=selected.metadata,
                bundled_sha256=self._bundled_sha256(),
                unavailable_reason=None,
            )

    def update_explicitly(
        self,
        report: ProgressReporter | None = None,
    ) -> UpdateResult:
        with self._lock:
            self._prepare_directories()
            current_status = self.status()
            current = current_status.metadata if current_status.available else None
            headers = {"User-Agent": "GameSaveScout/0.3.4 Ludusavi snapshot updater"}
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
                    return self._download_and_replace(
                        response,
                        current,
                        response.getheader("ETag"),
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
        metadata_temporary = self.temp_dir / f"ludusavi-meta-{uuid4().hex}.json"
        index_temporary = self.temp_dir / f"ludusavi-index-{uuid4().hex}.sqlite"
        digest = hashlib.sha256()
        total = 0
        try:
            _report(report, "downloading")
            with download.open("xb") as stream:
                while chunk := response.read(_CHUNK_BYTES):
                    total += len(chunk)
                    if total > MAX_DOWNLOAD_BYTES:
                        return UpdateResult(
                            "invalid",
                            "下载内容超过 64 MiB 限制。",
                            current,
                        )
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
                manifest = _parse_manifest_file(download)
            except (InvalidLudusaviManifest, UnicodeError) as error:
                return UpdateResult("invalid", f"下载的清单无效：{error}", current)

            _report(report, "indexing")
            try:
                build_ludusavi_index(
                    index_temporary,
                    manifest,
                    manifest_sha256=downloaded_sha256,
                )
                index = LudusaviIndex.open(
                    index_temporary,
                    manifest_sha256=downloaded_sha256,
                )
                _report(report, "probing")
                index.probe()
            except (InvalidLudusaviIndex, OSError, sqlite3.Error, ValueError) as error:
                return UpdateResult(
                    "failed",
                    _failure_message(f"构建或冷查询 Ludusavi 索引失败：{error}", current),
                    current,
                )

            metadata = SnapshotMetadata(
                etag=etag,
                sha256=downloaded_sha256,
                downloaded_at=_utc_now(),
                source_url=self.update_url,
                upstream_commit=None,
            )
            try:
                _write_bytes_fsynced(
                    metadata_temporary,
                    _metadata_json_bytes(metadata),
                )
                _report(report, "replacing")
                self._replace_active_bundle(
                    SnapshotBundle(download, metadata_temporary, index_temporary)
                )
            except (OSError, SnapshotUpdateError) as error:
                return UpdateResult(
                    "failed",
                    _failure_message(f"替换清单失败：{error}", current),
                    current,
                )
            return UpdateResult("updated", "Ludusavi 清单已更新。", metadata)
        finally:
            for temporary in (download, metadata_temporary, index_temporary):
                with suppress(OSError):
                    temporary.unlink(missing_ok=True)

    def _select_bundle(self, *, rebuild_active_index: bool) -> _SelectedBundle:
        errors: list[str] = []
        if any(path.exists() for path in self._active_paths()):
            try:
                metadata, _ = self._validate_source(
                    self._active,
                    allow_crlf_repair=False,
                )
                try:
                    LudusaviIndex.open(
                        self.active_index,
                        manifest_sha256=metadata.sha256,
                    )
                except InvalidLudusaviIndex as error:
                    if not rebuild_active_index:
                        raise SnapshotUpdateError(
                            "活动 Ludusavi 索引不可用。"
                        ) from error
                    self._rebuild_active_index(metadata)
                return _SelectedBundle("active", self._active, metadata)
            except (OSError, SnapshotUpdateError) as error:
                errors.append(f"活动快照不可用：{error}")
        try:
            metadata, _ = self._validate_bundled()
            return _SelectedBundle("bundled", self._bundled, metadata)
        except (OSError, SnapshotUpdateError) as error:
            errors.append(f"随包快照不可用：{error}")
        raise SnapshotUpdateError("；".join(errors) or "没有可用的 Ludusavi 快照。")

    def _validate_bundled(self) -> tuple[SnapshotMetadata, bytes]:
        if not (self.resource_dir / "LICENSE").is_file():
            raise SnapshotUpdateError("Ludusavi 随包许可证缺失。")
        return self._validate_bundle(self._bundled, allow_crlf_repair=True)

    def _validate_source(
        self,
        bundle: SnapshotBundle,
        *,
        allow_crlf_repair: bool,
    ) -> tuple[SnapshotMetadata, bytes]:
        if not bundle.manifest.is_file() or not bundle.metadata.is_file():
            raise SnapshotUpdateError("Ludusavi 清单文件组不完整。")
        metadata = _read_metadata(bundle.metadata)
        manifest_bytes = _validated_manifest_bytes(
            bundle.manifest,
            metadata.sha256,
            allow_crlf_repair=allow_crlf_repair,
        )
        return metadata, manifest_bytes

    def _validate_bundle(
        self,
        bundle: SnapshotBundle,
        *,
        allow_crlf_repair: bool,
    ) -> tuple[SnapshotMetadata, bytes]:
        metadata, manifest_bytes = self._validate_source(
            bundle,
            allow_crlf_repair=allow_crlf_repair,
        )
        try:
            LudusaviIndex.open(bundle.index, manifest_sha256=metadata.sha256)
        except InvalidLudusaviIndex as error:
            raise SnapshotUpdateError("Ludusavi 索引不可用。") from error
        return metadata, manifest_bytes

    def _rebuild_active_index(self, metadata: SnapshotMetadata) -> None:
        temporary = self.temp_dir / f"active-index-{uuid4().hex}.sqlite"
        try:
            manifest = _parse_manifest_file(self.active_manifest)
            build_ludusavi_index(
                temporary,
                manifest,
                manifest_sha256=metadata.sha256,
            )
            index = LudusaviIndex.open(temporary, manifest_sha256=metadata.sha256)
            index.probe()
            os.replace(temporary, self.active_index)
        except (
            InvalidLudusaviIndex,
            InvalidLudusaviManifest,
            OSError,
            sqlite3.Error,
            UnicodeError,
            ValueError,
        ) as error:
            raise SnapshotUpdateError("无法重建活动 Ludusavi 索引。") from error
        finally:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)

    def _replace_active_bundle(self, staged: SnapshotBundle) -> None:
        backups: dict[Path, Path] = {}
        try:
            for target in self._active_paths():
                if not target.exists():
                    continue
                backup = self.temp_dir / f"replace-{uuid4().hex}-{target.name}"
                _copy_file_fsynced(target, backup)
                backups[target] = backup
        except OSError:
            for backup in backups.values():
                with suppress(OSError):
                    backup.unlink(missing_ok=True)
            raise

        try:
            for source, target in zip(
                (staged.manifest, staged.metadata, staged.index),
                self._active_paths(),
                strict=True,
            ):
                os.replace(source, target)
            self._validate_bundle(self._active, allow_crlf_repair=False)
        except (OSError, SnapshotUpdateError) as error:
            restore_errors = self._restore_replaced_targets(backups)
            if restore_errors:
                raise SnapshotUpdateError(
                    "新清单替换失败，旧活动快照恢复也失败。"
                ) from error
            raise SnapshotUpdateError("新清单替换失败，旧活动快照已恢复。") from error
        finally:
            for backup in backups.values():
                with suppress(OSError):
                    backup.unlink(missing_ok=True)

    def _restore_replaced_targets(self, backups: Mapping[Path, Path]) -> bool:
        failed = False
        for target in self._active_paths():
            backup = backups.get(target)
            try:
                if backup is None:
                    target.unlink(missing_ok=True)
                else:
                    os.replace(backup, target)
            except OSError:
                failed = True
        return failed

    def _restore_copies(self, backups: Mapping[Path, Path]) -> bool:
        failed = False
        for target, backup in backups.items():
            try:
                _copy_file_replacing(backup, target)
            except OSError:
                failed = True
        return failed

    def _prepare_directories(self) -> None:
        self.active_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def _active_paths(self) -> tuple[Path, Path, Path]:
        return self.active_manifest, self.active_metadata, self.active_index

    def _bundled_sha256(self) -> str | None:
        try:
            return _read_metadata(self._bundled.metadata).sha256
        except SnapshotUpdateError:
            return None


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


def _parse_manifest_file(path: Path) -> LudusaviManifest:
    with path.open(encoding="utf-8") as stream:
        return parse_manifest(stream, skip_invalid_paths=True)


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


def _copy_file_fsynced(source: Path, destination: Path) -> None:
    with source.open("rb") as source_stream, destination.open("xb") as destination_stream:
        while chunk := source_stream.read(_CHUNK_BYTES):
            destination_stream.write(chunk)
        destination_stream.flush()
        os.fsync(destination_stream.fileno())


def _copy_file_replacing(source: Path, destination: Path) -> None:
    temporary = destination.parent / f".{destination.name}-{uuid4().hex}.tmp"
    try:
        _copy_file_fsynced(source, temporary)
        os.replace(temporary, destination)
    finally:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)


def _read_metadata(path: Path) -> SnapshotMetadata:
    try:
        loaded: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SnapshotUpdateError("无法读取 Ludusavi 元数据文件。") from error
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
        or not re_full_sha256(sha256)
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
