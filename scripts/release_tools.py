"""Offline release primitives shared by the Windows build entry point."""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tomllib
import zipfile
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any, cast
from urllib.parse import urlparse
from uuid import uuid4

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_VERSION_PATTERN = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?")
_WEBVIEW_ARCHIVE_CONFIG_KEYS = {
    "formatVersion",
    "version",
    "architecture",
    "archiveFileName",
    "sha256",
    "sourceUrl",
}
_WEBVIEW_BOOTSTRAPPER_CONFIG_KEYS = {
    "formatVersion",
    "fileName",
    "fileVersion",
    "sha256",
    "sourceUrl",
}


class ReleaseToolError(RuntimeError):
    """Raised when release input or a managed output boundary is invalid."""


class ReleaseMode(StrEnum):
    """Mutually exclusive WebView2 layouts produced by one build."""

    FIXED = "fixed"
    EVERGREEN = "evergreen"


@dataclass(frozen=True)
class ReleaseVersions:
    version: str

    @classmethod
    def load(cls, repository_root: Path) -> ReleaseVersions:
        root = repository_root.resolve(strict=True)
        project = _project_version(root / "pyproject.toml")
        package = _package_version(root / "src" / "gameshelf" / "__init__.py")
        frontend = _frontend_version(root / "frontend" / "package.json")
        if len({project, package, frontend}) != 1:
            raise ReleaseToolError(
                "GameShelf 版本不一致："
                f"pyproject={project}, package={package}, frontend={frontend}"
            )
        if _VERSION_PATTERN.fullmatch(project) is None:
            raise ReleaseToolError(f"GameShelf 版本格式无效：{project}")
        return cls(project)

    @property
    def release_name(self) -> str:
        return self.name_for(ReleaseMode.FIXED)

    def name_for(self, mode: ReleaseMode) -> str:
        base = f"GameShelf-{self.version}-win-x64"
        return base if mode is ReleaseMode.FIXED else f"{base}-lite"


@dataclass(frozen=True)
class ReleaseMetadata:
    app_version: str
    build_utc: str
    git_commit: str
    git_dirty: bool
    python_version: str
    node_version: str
    npm_version: str
    pyinstaller_version: str
    pywebview_version: str
    database_schema_version: int
    engine_rules_version: str
    ludusavi_sha256: str
    ludusavi_upstream_commit: str
    webview2_version: str
    webview2_archive_sha256: str


@dataclass(frozen=True)
class StagedRelease:
    mode: ReleaseMode
    directory: Path
    archive: Path
    checksum: Path


@dataclass(frozen=True)
class WebViewArchiveConfig:
    format_version: int
    version: str
    architecture: str
    archive_file_name: str
    sha256: str
    source_url: str

    @classmethod
    def load(cls, path: Path) -> WebViewArchiveConfig:
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ReleaseToolError(f"无法读取 WebView2 受控配置：{error}") from error
        if not isinstance(loaded, dict) or not all(
            isinstance(key, str) for key in loaded
        ):
            raise ReleaseToolError("WebView2 受控配置必须是 JSON 对象。")
        raw = cast(dict[str, Any], loaded)
        unknown = sorted(set(raw) - _WEBVIEW_ARCHIVE_CONFIG_KEYS)
        if unknown:
            raise ReleaseToolError(
                f"WebView2 受控配置包含未知字段：{', '.join(unknown)}"
            )
        missing = sorted(_WEBVIEW_ARCHIVE_CONFIG_KEYS - set(raw))
        if missing:
            raise ReleaseToolError(
                f"WebView2 受控配置缺少字段：{', '.join(missing)}"
            )
        format_version = raw["formatVersion"]
        version = raw["version"]
        architecture = raw["architecture"]
        archive_file_name = raw["archiveFileName"]
        digest = raw["sha256"]
        source_url = raw["sourceUrl"]
        if format_version != 1 or isinstance(format_version, bool):
            raise ReleaseToolError("WebView2 受控配置 formatVersion 必须为 1。")
        if not isinstance(version, str) or not version.strip():
            raise ReleaseToolError("WebView2 版本无效。")
        if architecture != "x64":
            raise ReleaseToolError("WebView2 受控配置只允许 x64 架构。")
        if (
            not isinstance(archive_file_name, str)
            or Path(archive_file_name).name != archive_file_name
            or not archive_file_name.casefold().endswith(".cab")
        ):
            raise ReleaseToolError("WebView2 CAB 文件名无效。")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ReleaseToolError("WebView2 受控配置中的 SHA-256 无效。")
        if not isinstance(source_url, str):
            raise ReleaseToolError("WebView2 来源 URL 无效。")
        parsed_url = urlparse(source_url)
        if parsed_url.scheme != "https" or not parsed_url.netloc:
            raise ReleaseToolError("WebView2 来源 URL 必须使用 HTTPS。")
        return cls(
            format_version=format_version,
            version=version,
            architecture=architecture,
            archive_file_name=archive_file_name,
            sha256=digest,
            source_url=source_url,
        )


@dataclass(frozen=True)
class WebViewBootstrapperConfig:
    format_version: int
    file_name: str
    file_version: str
    sha256: str
    source_url: str

    @classmethod
    def load(cls, path: Path) -> WebViewBootstrapperConfig:
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ReleaseToolError(
                f"无法读取 WebView2 Bootstrapper 受控配置：{error}"
            ) from error
        if not isinstance(loaded, dict) or not all(
            isinstance(key, str) for key in loaded
        ):
            raise ReleaseToolError("WebView2 Bootstrapper 受控配置必须是 JSON 对象。")
        raw = cast(dict[str, Any], loaded)
        unknown = sorted(set(raw) - _WEBVIEW_BOOTSTRAPPER_CONFIG_KEYS)
        if unknown:
            raise ReleaseToolError(
                "WebView2 Bootstrapper 受控配置包含未知字段："
                f"{', '.join(unknown)}"
            )
        missing = sorted(_WEBVIEW_BOOTSTRAPPER_CONFIG_KEYS - set(raw))
        if missing:
            raise ReleaseToolError(
                "WebView2 Bootstrapper 受控配置缺少字段："
                f"{', '.join(missing)}"
            )
        format_version = raw["formatVersion"]
        file_name = raw["fileName"]
        file_version = raw["fileVersion"]
        digest = raw["sha256"]
        source_url = raw["sourceUrl"]
        if format_version != 1 or isinstance(format_version, bool):
            raise ReleaseToolError(
                "WebView2 Bootstrapper 受控配置 formatVersion 必须为 1。"
            )
        if file_name != "MicrosoftEdgeWebview2Setup.exe":
            raise ReleaseToolError("WebView2 Bootstrapper 文件名无效。")
        if not isinstance(file_version, str) or re.fullmatch(
            r"[0-9]+(?:\.[0-9]+){1,3}", file_version
        ) is None:
            raise ReleaseToolError("WebView2 Bootstrapper 文件版本无效。")
        if not _valid_digest(digest):
            raise ReleaseToolError(
                "WebView2 Bootstrapper 受控配置中的 SHA-256 无效。"
            )
        if not isinstance(source_url, str):
            raise ReleaseToolError("WebView2 Bootstrapper 来源 URL 无效。")
        parsed_url = urlparse(source_url)
        if parsed_url.scheme != "https" or not parsed_url.netloc:
            raise ReleaseToolError("WebView2 Bootstrapper 来源 URL 必须使用 HTTPS。")
        return cls(
            format_version=format_version,
            file_name=file_name,
            file_version=file_version,
            sha256=cast(str, digest),
            source_url=source_url,
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def validate_webview_archive(
    archive: Path,
    config: WebViewArchiveConfig,
) -> Path:
    if not archive.is_absolute():
        raise ReleaseToolError("WebView2 CAB 必须使用绝对路径。")
    if _is_reparse_point(archive) or not archive.is_file():
        raise ReleaseToolError("WebView2 CAB 必须是普通文件，不能是目录或链接。")
    if archive.name != config.archive_file_name:
        raise ReleaseToolError(
            "WebView2 CAB 文件名与受控配置不一致："
            f"期望 {config.archive_file_name}，实际 {archive.name}"
        )
    actual_digest = sha256_file(archive)
    if actual_digest != config.sha256:
        raise ReleaseToolError(
            "WebView2 CAB 的 SHA-256 与受控配置不一致："
            f"期望 {config.sha256}，实际 {actual_digest}"
        )
    return archive


def validate_webview_bootstrapper(
    bootstrapper: Path,
    config: WebViewBootstrapperConfig,
) -> Path:
    if not bootstrapper.is_absolute():
        raise ReleaseToolError("WebView2 Bootstrapper 必须使用绝对路径。")
    if _is_reparse_point(bootstrapper) or not bootstrapper.is_file():
        raise ReleaseToolError(
            "WebView2 Bootstrapper 必须是普通文件，不能是目录或链接。"
        )
    if bootstrapper.name != config.file_name:
        raise ReleaseToolError(
            "WebView2 Bootstrapper 文件名与受控配置不一致："
            f"期望 {config.file_name}，实际 {bootstrapper.name}"
        )
    actual_digest = sha256_file(bootstrapper)
    if actual_digest != config.sha256:
        raise ReleaseToolError(
            "WebView2 Bootstrapper 的 SHA-256 与受控配置不一致："
            f"期望 {config.sha256}，实际 {actual_digest}"
        )
    return bootstrapper


def validate_managed_target(
    repository_root: Path,
    target: Path,
    versions: ReleaseVersions,
) -> Path:
    root = repository_root.resolve(strict=True)
    if not target.is_absolute():
        raise ReleaseToolError("受控发布目标必须使用绝对路径。")
    if ".." in target.parts:
        raise ReleaseToolError("受控发布目标不能包含父目录跳转。")
    candidate = Path(os.path.abspath(target))
    allowed = [root / "build" / "release"]
    for mode in ReleaseMode:
        release_name = versions.name_for(mode)
        allowed.extend(
            (
                root / "dist" / release_name,
                root / "dist" / f"{release_name}.zip",
                root / "dist" / f"{release_name}.zip.sha256",
            )
        )
    if _path_key(candidate) not in {_path_key(path) for path in allowed}:
        raise ReleaseToolError(f"路径不是当前版本的受控发布目标：{candidate}")
    current = candidate
    while current != root:
        if _is_reparse_point(current):
            raise ReleaseToolError(f"受控发布目标不能经过重解析点或链接：{current}")
        parent = current.parent
        if parent == current:
            raise ReleaseToolError(f"受控发布目标不在仓库内：{candidate}")
        current = parent
    return candidate


def extract_webview2_cab(
    archive: Path,
    destination: Path,
    expand_executable: Path,
    *,
    release_root: Path,
) -> Path:
    """Expand a CAB into one new direct child of the validated release root."""

    if not archive.is_absolute() or _is_reparse_point(archive) or not archive.is_file():
        raise ReleaseToolError("待解包的 WebView2 CAB 必须是绝对路径普通文件。")
    if (
        not expand_executable.is_absolute()
        or expand_executable.name.casefold() != "expand.exe"
        or _is_reparse_point(expand_executable)
        or not expand_executable.is_file()
    ):
        raise ReleaseToolError("expand.exe 必须是绝对路径普通系统文件。")
    if not release_root.is_absolute() or not release_root.is_dir():
        raise ReleaseToolError("build/release 受控根目录不存在或不是绝对路径。")
    release = Path(os.path.abspath(release_root))
    if _is_reparse_point(release):
        raise ReleaseToolError("build/release 受控根目录不能是重解析点或链接。")
    if not destination.is_absolute():
        raise ReleaseToolError("CAB 解包目标必须使用绝对路径。")
    candidate = Path(os.path.abspath(destination))
    if candidate.parent != release:
        raise ReleaseToolError("CAB 解包目标必须是 build/release 下的直接受控目录。")
    if candidate.exists() or candidate.is_symlink():
        raise ReleaseToolError(f"CAB 解包目标必须是尚不存在的新目录：{candidate}")
    candidate.mkdir()
    result = subprocess.run(
        [
            str(expand_executable),
            str(archive),
            "-F:*",
            str(candidate),
        ],
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
        shell=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "未知错误"
        raise ReleaseToolError(f"expand.exe 解包 WebView2 CAB 失败：{detail}")
    return candidate


def normalize_webview_runtime(extracted_root: Path) -> Path:
    """Return the unique direct runtime root after rejecting unsafe layouts."""

    if not extracted_root.is_dir() or _is_reparse_point(extracted_root):
        raise ReleaseToolError("WebView2 解包目录不存在或是重解析点/链接。")
    _reject_reparse_descendants(extracted_root)
    candidates: list[Path] = []
    if (extracted_root / "msedgewebview2.exe").is_file():
        candidates.append(extracted_root)
    top_level = tuple(extracted_root.iterdir())
    candidates.extend(
        child
        for child in top_level
        if child.is_dir() and (child / "msedgewebview2.exe").is_file()
    )
    if not candidates:
        raise ReleaseToolError("WebView2 CAB 中找不到 msedgewebview2.exe。")
    if len(candidates) != 1:
        raise ReleaseToolError("WebView2 CAB 必须包含唯一的运行时根目录，不能有多个候选。")
    runtime_root = candidates[0]
    if runtime_root != extracted_root and top_level != (runtime_root,):
        raise ReleaseToolError("WebView2 CAB 的单层包装目录之外包含意外内容。")
    return runtime_root


def build_release_manifest(
    release_root: Path,
    metadata: ReleaseMetadata,
    mode: ReleaseMode,
    *,
    bootstrapper_config: WebViewBootstrapperConfig | None = None,
) -> dict[str, object]:
    """Build a complete payload manifest, excluding the manifest itself."""

    versions = ReleaseVersions(metadata.app_version)
    _validate_release_layout(
        release_root,
        versions,
        mode,
        require_manifest=False,
    )
    if mode is ReleaseMode.EVERGREEN:
        if bootstrapper_config is None:
            raise ReleaseToolError("轻量版发布清单缺少 Bootstrapper 受控配置。")
        validate_webview_bootstrapper(
            release_root
            / "prerequisites"
            / "MicrosoftEdgeWebview2Setup.exe",
            bootstrapper_config,
        )
    files = [
        {
            "path": relative,
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for relative, path in _release_payload_files(release_root)
    ]
    return {
        "formatVersion": 2,
        "runtimeMode": mode.value,
        "appVersion": metadata.app_version,
        "buildUtc": metadata.build_utc,
        "gitCommit": metadata.git_commit,
        "gitDirty": metadata.git_dirty,
        "platform": "windows-x64",
        "pythonVersion": metadata.python_version,
        "nodeVersion": metadata.node_version,
        "npmVersion": metadata.npm_version,
        "pyinstallerVersion": metadata.pyinstaller_version,
        "pywebviewVersion": metadata.pywebview_version,
        "databaseSchemaVersion": metadata.database_schema_version,
        "engineRulesVersion": metadata.engine_rules_version,
        "ludusaviSha256": metadata.ludusavi_sha256,
        "ludusaviUpstreamCommit": metadata.ludusavi_upstream_commit,
        "webview2Version": (
            metadata.webview2_version if mode is ReleaseMode.FIXED else None
        ),
        "webview2ArchiveSha256": (
            metadata.webview2_archive_sha256
            if mode is ReleaseMode.FIXED
            else None
        ),
        "webview2BootstrapperFileVersion": (
            bootstrapper_config.file_version
            if mode is ReleaseMode.EVERGREEN and bootstrapper_config is not None
            else None
        ),
        "webview2BootstrapperSha256": (
            bootstrapper_config.sha256
            if mode is ReleaseMode.EVERGREEN and bootstrapper_config is not None
            else None
        ),
        "webview2BootstrapperSignatureValid": (
            True if mode is ReleaseMode.EVERGREEN else None
        ),
        "fixedRuntime": mode is ReleaseMode.FIXED,
        "signed": False,
        "files": files,
    }


def write_release_manifest(
    release_root: Path,
    metadata: ReleaseMetadata,
    mode: ReleaseMode,
    *,
    bootstrapper_config: WebViewBootstrapperConfig | None = None,
) -> Path:
    destination = release_root / "release-manifest.json"
    payload = build_release_manifest(
        release_root,
        metadata,
        mode,
        bootstrapper_config=bootstrapper_config,
    )
    _write_json_atomic(destination, payload)
    return destination


def verify_release_tree(
    release_root: Path,
    versions: ReleaseVersions,
    mode: ReleaseMode,
) -> None:
    """Verify layout and every payload hash against release-manifest.json."""

    _validate_release_layout(
        release_root,
        versions,
        mode,
        require_manifest=True,
    )
    manifest_file = release_root / "release-manifest.json"
    try:
        loaded = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReleaseToolError(f"无法读取发布清单：{error}") from error
    if not isinstance(loaded, dict):
        raise ReleaseToolError("发布清单必须是 JSON 对象。")
    manifest = cast(dict[str, Any], loaded)
    if manifest.get("formatVersion") != 2:
        raise ReleaseToolError("发布清单 formatVersion 必须为 2。")
    if manifest.get("appVersion") != versions.version:
        raise ReleaseToolError("发布清单中的 GameShelf 版本不匹配。")
    if manifest.get("platform") != "windows-x64":
        raise ReleaseToolError("发布清单平台必须为 windows-x64。")
    if manifest.get("runtimeMode") != mode.value:
        raise ReleaseToolError("发布清单 runtimeMode 与发布模式不匹配。")
    if manifest.get("signed") is not False:
        raise ReleaseToolError("发布清单必须记录 signed=false。")
    if manifest.get("fixedRuntime") is not (mode is ReleaseMode.FIXED):
        raise ReleaseToolError("发布清单 fixedRuntime 与发布模式不匹配。")
    if mode is ReleaseMode.FIXED:
        if (
            not isinstance(manifest.get("webview2Version"), str)
            or not _valid_digest(manifest.get("webview2ArchiveSha256"))
            or manifest.get("webview2BootstrapperFileVersion") is not None
            or manifest.get("webview2BootstrapperSha256") is not None
            or manifest.get("webview2BootstrapperSignatureValid") is not None
        ):
            raise ReleaseToolError("完整版发布清单中的 WebView2 字段无效。")
    else:
        bootstrapper_version = manifest.get("webview2BootstrapperFileVersion")
        bootstrapper_digest = manifest.get("webview2BootstrapperSha256")
        if (
            manifest.get("webview2Version") is not None
            or manifest.get("webview2ArchiveSha256") is not None
            or not isinstance(bootstrapper_version, str)
            or re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", bootstrapper_version)
            is None
            or not _valid_digest(bootstrapper_digest)
            or manifest.get("webview2BootstrapperSignatureValid") is not True
        ):
            raise ReleaseToolError("轻量版发布清单中的 WebView2 字段无效。")
        bootstrapper = (
            release_root
            / "prerequisites"
            / "MicrosoftEdgeWebview2Setup.exe"
        )
        if sha256_file(bootstrapper) != bootstrapper_digest:
            raise ReleaseToolError("轻量版 Bootstrapper SHA-256 与发布清单不一致。")
    raw_files = manifest.get("files")
    if not isinstance(raw_files, list):
        raise ReleaseToolError("发布清单 files 必须是数组。")
    recorded: dict[str, tuple[int, str]] = {}
    ordered_paths: list[str] = []
    for raw_entry in raw_files:
        if not isinstance(raw_entry, dict) or set(raw_entry) != {
            "path",
            "size",
            "sha256",
        }:
            raise ReleaseToolError("发布清单文件条目格式无效。")
        relative = raw_entry["path"]
        size = raw_entry["size"]
        digest = raw_entry["sha256"]
        if (
            not isinstance(relative, str)
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or not _valid_digest(digest)
        ):
            raise ReleaseToolError("发布清单文件条目的路径、大小或 SHA-256 无效。")
        portable = PurePosixPath(relative)
        if portable.is_absolute() or ".." in portable.parts or "\\" in relative:
            raise ReleaseToolError(f"发布清单包含不安全相对路径：{relative}")
        if relative in recorded:
            raise ReleaseToolError(f"发布清单包含重复路径：{relative}")
        recorded[relative] = (size, digest)
        ordered_paths.append(relative)
    if ordered_paths != sorted(ordered_paths):
        raise ReleaseToolError("发布清单文件路径必须稳定排序。")
    actual_files = dict(_release_payload_files(release_root))
    if set(recorded) != set(actual_files):
        missing = sorted(set(actual_files) - set(recorded))
        extra = sorted(set(recorded) - set(actual_files))
        raise ReleaseToolError(
            f"发布清单文件集合不匹配：缺少 {missing}，多余 {extra}"
        )
    for relative, path in actual_files.items():
        expected_size, expected_digest = recorded[relative]
        if path.stat().st_size != expected_size:
            raise ReleaseToolError(f"发布文件大小与清单不一致：{relative}")
        if sha256_file(path) != expected_digest:
            raise ReleaseToolError(f"发布文件 SHA-256 与清单不一致：{relative}")


def create_release_zip(
    release_root: Path,
    archive: Path,
    versions: ReleaseVersions,
    mode: ReleaseMode,
) -> Path:
    """Create a sorted ZIP containing one verified release root."""

    verify_release_tree(release_root, versions, mode)
    release_name = versions.name_for(mode)
    if not archive.is_absolute():
        raise ReleaseToolError("发布 ZIP 必须使用绝对路径。")
    if archive.name != f"{release_name}.zip":
        raise ReleaseToolError("发布 ZIP 文件名与当前版本不匹配。")
    if archive.exists() or archive.is_symlink():
        raise ReleaseToolError(f"发布 ZIP 目标必须尚不存在：{archive}")
    try:
        archive.relative_to(release_root)
    except ValueError:
        pass
    else:
        raise ReleaseToolError("发布 ZIP 不能写入待压缩的发布目录内部。")
    archive.parent.mkdir(parents=True, exist_ok=True)
    files = [
        *(_release_payload_files(release_root)),
        ("release-manifest.json", release_root / "release-manifest.json"),
    ]
    files.sort(key=lambda entry: entry[0])
    try:
        with zipfile.ZipFile(
            archive,
            "x",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
            allowZip64=True,
        ) as bundle:
            for relative, path in files:
                bundle.write(
                    path,
                    arcname=f"{release_name}/{relative}",
                )
    except Exception:
        with suppress(OSError):
            archive.unlink(missing_ok=True)
        raise
    return archive


def verify_release_zip(
    archive: Path,
    versions: ReleaseVersions,
    mode: ReleaseMode,
) -> None:
    """Reopen a release ZIP and verify its embedded manifest and payload bytes."""

    if not archive.is_absolute() or _is_reparse_point(archive) or not archive.is_file():
        raise ReleaseToolError("发布 ZIP 必须是绝对路径普通文件。")
    expected_prefix = f"{versions.name_for(mode)}/"
    try:
        with zipfile.ZipFile(archive, "r") as bundle:
            names = bundle.namelist()
            if len(names) != len(set(names)):
                raise ReleaseToolError("发布 ZIP 包含重复归档路径。")
            if names != sorted(names):
                raise ReleaseToolError("发布 ZIP 路径必须稳定排序。")
            relative_names: list[str] = []
            for name in names:
                portable = PurePosixPath(name)
                if (
                    portable.is_absolute()
                    or ".." in portable.parts
                    or "\\" in name
                    or name.endswith("/")
                ):
                    raise ReleaseToolError(f"发布 ZIP 包含不安全归档路径：{name}")
                if not name.startswith(expected_prefix):
                    raise ReleaseToolError("发布 ZIP 必须只包含一个当前版本根目录。")
                relative = name.removeprefix(expected_prefix)
                if not relative or any(
                    part.casefold() == "data" for part in PurePosixPath(relative).parts
                ):
                    raise ReleaseToolError("发布 ZIP 归档路径无效或包含 data。")
                relative_names.append(relative)
            manifest_name = f"{expected_prefix}release-manifest.json"
            if manifest_name not in names:
                raise ReleaseToolError("发布 ZIP 缺少 release-manifest.json。")
            try:
                manifest = json.loads(bundle.read(manifest_name).decode("utf-8"))
            except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ReleaseToolError(f"发布 ZIP 内清单无效：{error}") from error
            if (
                not isinstance(manifest, dict)
                or manifest.get("appVersion") != versions.version
                or manifest.get("formatVersion") != 2
                or manifest.get("runtimeMode") != mode.value
            ):
                raise ReleaseToolError("发布 ZIP 内清单版本无效。")
            raw_files = manifest.get("files")
            if not isinstance(raw_files, list):
                raise ReleaseToolError("发布 ZIP 内清单 files 无效。")
            recorded: dict[str, tuple[int, str]] = {}
            for entry in raw_files:
                if not isinstance(entry, dict):
                    raise ReleaseToolError("发布 ZIP 内清单文件条目无效。")
                recorded_relative = entry.get("path")
                recorded_size = entry.get("size")
                recorded_digest = entry.get("sha256")
                if (
                    not isinstance(recorded_relative, str)
                    or not isinstance(recorded_size, int)
                    or isinstance(recorded_size, bool)
                    or recorded_size < 0
                    or not _valid_digest(recorded_digest)
                    or recorded_relative in recorded
                ):
                    raise ReleaseToolError("发布 ZIP 内清单文件条目无效。")
                recorded[recorded_relative] = (
                    recorded_size,
                    cast(str, recorded_digest),
                )
            expected_relatives = set(recorded) | {"release-manifest.json"}
            if set(relative_names) != expected_relatives:
                raise ReleaseToolError("发布 ZIP 归档文件集合与清单不一致。")
            for relative, (expected_size, expected_digest) in recorded.items():
                payload = bundle.read(f"{expected_prefix}{relative}")
                if len(payload) != expected_size:
                    raise ReleaseToolError(f"发布 ZIP 文件大小与清单不一致：{relative}")
                if hashlib.sha256(payload).hexdigest() != expected_digest:
                    raise ReleaseToolError(f"发布 ZIP 文件 SHA-256 不一致：{relative}")
    except zipfile.BadZipFile as error:
        raise ReleaseToolError(f"发布 ZIP 无法打开：{error}") from error


def write_zip_sha256(archive: Path, checksum_file: Path) -> Path:
    if not archive.is_file() or _is_reparse_point(archive):
        raise ReleaseToolError("无法为不存在或不安全的 ZIP 写入 SHA-256。")
    if (
        not checksum_file.is_absolute()
        or checksum_file.parent != archive.parent
        or checksum_file.name != f"{archive.name}.sha256"
    ):
        raise ReleaseToolError("ZIP SHA-256 文件必须与 ZIP 同目录且名称匹配。")
    content = f"{sha256_file(archive)}  {archive.name}\n"
    _write_text_atomic(checksum_file, content, encoding="ascii")
    return checksum_file


def verify_zip_sha256(archive: Path, checksum_file: Path) -> None:
    try:
        recorded = checksum_file.read_text(encoding="ascii")
    except OSError as error:
        raise ReleaseToolError(f"无法读取 ZIP SHA-256 文件：{error}") from error
    expected = f"{sha256_file(archive)}  {archive.name}\n"
    if recorded != expected:
        raise ReleaseToolError("ZIP SHA-256 文件与归档实际 SHA-256 不一致。")


def publish_releases(
    repository_root: Path,
    staged_releases: Sequence[StagedRelease],
    versions: ReleaseVersions,
) -> tuple[Path, ...]:
    """Atomically replace all six outputs for both runtime modes."""

    if len(staged_releases) != len(ReleaseMode):
        raise ReleaseToolError("发布事务必须恰好包含完整版和轻量版。")
    by_mode = {staged.mode: staged for staged in staged_releases}
    if set(by_mode) != set(ReleaseMode) or len(by_mode) != len(staged_releases):
        raise ReleaseToolError("发布事务必须各包含一份 fixed 和 evergreen。")

    root = repository_root.resolve(strict=True)
    managed_root = validate_managed_target(
        root,
        root / "build" / "release",
        versions,
    )
    if not managed_root.is_dir():
        raise ReleaseToolError("发布暂存根 build/release 不存在。")

    ordered = tuple(by_mode[mode] for mode in ReleaseMode)
    staged_paths: list[Path] = []
    final_paths: list[Path] = []
    for staged in ordered:
        release_name = versions.name_for(staged.mode)
        sources = (staged.directory, staged.archive, staged.checksum)
        expected_names = (
            release_name,
            f"{release_name}.zip",
            f"{release_name}.zip.sha256",
        )
        for source, expected_name in zip(sources, expected_names, strict=True):
            if not source.is_absolute() or source.name != expected_name:
                raise ReleaseToolError("暂存发布目标的绝对路径或文件名无效。")
            _require_descendant(source, managed_root)
            if _is_reparse_point(source):
                raise ReleaseToolError(
                    f"暂存发布目标不能是重解析点或链接：{source}"
                )
        verify_release_tree(staged.directory, versions, staged.mode)
        verify_release_zip(staged.archive, versions, staged.mode)
        verify_zip_sha256(staged.archive, staged.checksum)
        staged_paths.extend(sources)
        for name in expected_names:
            final_paths.append(
                validate_managed_target(root, root / "dist" / name, versions)
            )

    for final in final_paths:
        if _is_reparse_point(final):
            raise ReleaseToolError(f"现有发布目标不能是重解析点或链接：{final}")
    dist_root = root / "dist"
    dist_root.mkdir(parents=True, exist_ok=True)
    token = uuid4().hex
    backups: list[tuple[Path, Path]] = []
    published: list[Path] = []
    try:
        for final in final_paths:
            if final.exists():
                backup = final.with_name(f".{final.name}.backup-{token}")
                if backup.exists() or backup.is_symlink():
                    raise ReleaseToolError(f"发布备份目标意外存在：{backup}")
                os.replace(final, backup)
                backups.append((final, backup))
        for source, final in zip(staged_paths, final_paths, strict=True):
            os.replace(source, final)
            published.append(final)
    except (OSError, ReleaseToolError) as error:
        rollback_errors: list[str] = []
        for final in reversed(published):
            try:
                _remove_exact_published_target(final, dist_root, versions)
            except (OSError, ReleaseToolError) as rollback_error:
                rollback_errors.append(str(rollback_error))
        for final, backup in reversed(backups):
            try:
                if backup.exists():
                    os.replace(backup, final)
            except OSError as rollback_error:
                rollback_errors.append(str(rollback_error))
        detail = f"发布替换失败：{error}"
        if rollback_errors:
            detail += f"；回滚错误：{' | '.join(rollback_errors)}"
        raise ReleaseToolError(detail) from error
    for _final, backup in backups:
        _remove_exact_backup(backup, dist_root)
    return tuple(final_paths)


def prepare_build_root(
    repository_root: Path,
    versions: ReleaseVersions,
) -> Path:
    root = repository_root.resolve(strict=True)
    build_root = validate_managed_target(
        root,
        root / "build" / "release",
        versions,
    )
    if build_root.exists():
        if _is_reparse_point(build_root) or not build_root.is_dir():
            raise ReleaseToolError("build/release 必须是普通目录，不能是链接。")
        shutil.rmtree(build_root)
    build_root.mkdir(parents=True)
    return build_root


def collect_release_metadata(
    repository_root: Path,
    config: WebViewArchiveConfig,
) -> ReleaseMetadata:
    root = repository_root.resolve(strict=True)
    versions = ReleaseVersions.load(root)
    git_commit = _capture_command(("git", "rev-parse", "HEAD"), root)
    if re.fullmatch(r"[0-9a-f]{40}", git_commit) is None:
        raise ReleaseToolError(f"Git 提交号无效：{git_commit}")
    git_dirty = bool(
        _capture_command(
            ("git", "status", "--porcelain", "--untracked-files=normal"),
            root,
            allow_empty=True,
        )
    )
    node_version = _capture_command(("node", "--version"), root).removeprefix("v")
    npm_version = _capture_command(("npm.cmd", "--version"), root)
    database_schema_version = _python_integer_constant(
        root / "src" / "gameshelf" / "db" / "migrator.py",
        "LATEST_SCHEMA_VERSION",
    )
    try:
        engine_document = yaml.safe_load(
            (root / "resources" / "rules" / "engines.yaml").read_text(
                encoding="utf-8"
            )
        )
    except (OSError, yaml.YAMLError) as error:
        raise ReleaseToolError(f"无法读取引擎规则版本：{error}") from error
    if not isinstance(engine_document, dict):
        raise ReleaseToolError("引擎规则文件必须是映射。")
    engine_rules_version = engine_document.get("version")
    if not isinstance(engine_rules_version, str) or not engine_rules_version:
        raise ReleaseToolError("引擎规则版本无效。")
    try:
        ludusavi_loaded = json.loads(
            (
                root
                / "resources"
                / "manifests"
                / "ludusavi"
                / "manifest-meta.json"
            ).read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as error:
        raise ReleaseToolError(f"无法读取 Ludusavi 元数据：{error}") from error
    if not isinstance(ludusavi_loaded, dict):
        raise ReleaseToolError("Ludusavi 元数据必须是 JSON 对象。")
    ludusavi_sha256 = ludusavi_loaded.get("sha256")
    ludusavi_commit = ludusavi_loaded.get("upstreamCommit")
    if not _valid_digest(ludusavi_sha256):
        raise ReleaseToolError("Ludusavi 元数据 SHA-256 无效。")
    if not isinstance(ludusavi_commit, str) or re.fullmatch(
        r"[0-9a-f]{40}", ludusavi_commit
    ) is None:
        raise ReleaseToolError("Ludusavi 上游提交号无效。")
    return ReleaseMetadata(
        app_version=versions.version,
        build_utc=datetime.now(UTC).isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        ),
        git_commit=git_commit,
        git_dirty=git_dirty,
        python_version=platform.python_version(),
        node_version=node_version,
        npm_version=npm_version,
        pyinstaller_version=importlib.metadata.version("pyinstaller"),
        pywebview_version=importlib.metadata.version("pywebview"),
        database_schema_version=database_schema_version,
        engine_rules_version=engine_rules_version,
        ludusavi_sha256=cast(str, ludusavi_sha256),
        ludusavi_upstream_commit=ludusavi_commit,
        webview2_version=config.version,
        webview2_archive_sha256=config.sha256,
    )


def _project_version(path: Path) -> str:
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
        version = document["project"]["version"]
    except (OSError, tomllib.TOMLDecodeError, KeyError, TypeError) as error:
        raise ReleaseToolError(f"无法读取 pyproject.toml 版本：{error}") from error
    if not isinstance(version, str):
        raise ReleaseToolError("pyproject.toml 的项目版本必须是字符串。")
    return version


def _python_integer_constant(path: Path, name: str) -> int:
    try:
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as error:
        raise ReleaseToolError(f"无法读取 Python 常量 {name}：{error}") from error
    for statement in module.body:
        if not isinstance(statement, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == name
            for target in statement.targets
        ):
            continue
        value = ast.literal_eval(statement.value)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    raise ReleaseToolError(f"Python 文件未定义整数常量 {name}。")


def _capture_command(
    command: Sequence[str],
    cwd: Path,
    *,
    allow_empty: bool = False,
) -> str:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
            shell=False,
        )
    except OSError as error:
        raise ReleaseToolError(f"无法执行发布环境命令 {command[0]}：{error}") from error
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "未知错误"
        raise ReleaseToolError(f"发布环境命令失败 {command[0]}：{detail}")
    output = result.stdout.strip()
    if not output and not allow_empty:
        raise ReleaseToolError(f"发布环境命令没有输出：{command[0]}")
    return output


def _package_version(path: Path) -> str:
    try:
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as error:
        raise ReleaseToolError(f"无法读取 Python 包版本：{error}") from error
    for statement in module.body:
        if not isinstance(statement, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "__version__"
            for target in statement.targets
        ):
            continue
        value = ast.literal_eval(statement.value)
        if isinstance(value, str):
            return value
    raise ReleaseToolError("Python 包未定义字符串 __version__。")


def _frontend_version(path: Path) -> str:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        version = document["version"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise ReleaseToolError(f"无法读取前端版本：{error}") from error
    if not isinstance(version, str):
        raise ReleaseToolError("前端版本必须是字符串。")
    return version


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def _controlled_webview_config(repository_root: Path) -> WebViewArchiveConfig:
    config_path = repository_root / "release" / "webview2-runtime.json"
    if _is_reparse_point(config_path) or not config_path.is_file():
        raise ReleaseToolError(f"缺少受控 WebView2 配置：{config_path}")
    return WebViewArchiveConfig.load(config_path)


def _controlled_bootstrapper_config(
    repository_root: Path,
) -> WebViewBootstrapperConfig:
    config_path = repository_root / "release" / "webview2-bootstrapper.json"
    if _is_reparse_point(config_path) or not config_path.is_file():
        raise ReleaseToolError(f"缺少受控 WebView2 Bootstrapper 配置：{config_path}")
    return WebViewBootstrapperConfig.load(config_path)


def _windows_system_tool(name: str) -> Path:
    system_root = os.environ.get("SYSTEMROOT")
    if not system_root:
        raise ReleaseToolError("无法确定 Windows 系统目录。")
    tool = Path(system_root) / "System32" / name
    if not tool.is_file() or _is_reparse_point(tool):
        raise ReleaseToolError(f"找不到 Windows 系统工具：{tool}")
    return tool


def _require_descendant(path: Path, parent: Path) -> None:
    try:
        relative = path.relative_to(parent)
    except ValueError as error:
        raise ReleaseToolError(f"暂存发布目标不在 build/release 内：{path}") from error
    if not relative.parts:
        raise ReleaseToolError("暂存发布目标不能等于 build/release 根目录。")
    current = path
    while current != parent:
        if _is_reparse_point(current):
            raise ReleaseToolError(f"暂存发布目标不能经过重解析点或链接：{current}")
        current = current.parent


def _remove_exact_backup(backup: Path, dist_root: Path) -> None:
    if (
        backup.parent != dist_root
        or not backup.name.startswith(".")
        or ".backup-" not in backup.name
    ):
        raise ReleaseToolError(f"拒绝清理非受控发布备份：{backup}")
    if _is_reparse_point(backup):
        raise ReleaseToolError(f"拒绝清理重解析点发布备份：{backup}")
    if backup.is_dir():
        shutil.rmtree(backup)
    else:
        backup.unlink(missing_ok=True)


def _remove_exact_published_target(
    target: Path,
    dist_root: Path,
    versions: ReleaseVersions,
) -> None:
    validated = validate_managed_target(dist_root.parent, target, versions)
    if validated.parent != dist_root or _is_reparse_point(validated):
        raise ReleaseToolError(f"拒绝清理非受控或重解析点发布目标：{validated}")
    if validated.is_dir():
        shutil.rmtree(validated)
    else:
        validated.unlink(missing_ok=True)


def _validate_release_layout(
    release_root: Path,
    versions: ReleaseVersions,
    mode: ReleaseMode,
    *,
    require_manifest: bool,
) -> None:
    if not release_root.is_absolute() or not release_root.is_dir():
        raise ReleaseToolError("发布根目录必须是已存在的绝对路径目录。")
    expected_release_name = versions.name_for(mode)
    if release_root.name != expected_release_name:
        raise ReleaseToolError(
            f"发布根目录名称必须为当前版本和模式：{expected_release_name}"
        )
    if _is_reparse_point(release_root):
        raise ReleaseToolError("发布根目录不能是重解析点或链接。")
    top_level = {child.name: child for child in release_root.iterdir()}
    required = {
        "GameShelf.exe",
        "_internal",
        "README.txt",
        "LICENSE",
        "THIRD_PARTY_NOTICES.md",
    }
    required.add("runtime" if mode is ReleaseMode.FIXED else "prerequisites")
    if require_manifest:
        required.add("release-manifest.json")
    missing = sorted(required - set(top_level))
    if missing:
        raise ReleaseToolError(f"发布目录缺少必需内容：{', '.join(missing)}")
    allowed = required | ({"release-manifest.json"} if not require_manifest else set())
    unexpected = sorted(set(top_level) - allowed)
    if "data" in unexpected:
        raise ReleaseToolError("发布目录不能包含 data。")
    if unexpected:
        raise ReleaseToolError(f"发布目录包含意外顶层内容：{', '.join(unexpected)}")
    if not top_level["GameShelf.exe"].is_file():
        raise ReleaseToolError("GameShelf.exe 必须是普通文件。")
    mode_directory = "runtime" if mode is ReleaseMode.FIXED else "prerequisites"
    if not top_level["_internal"].is_dir() or not top_level[mode_directory].is_dir():
        raise ReleaseToolError(f"_internal 和 {mode_directory} 必须是目录。")
    critical_files = [
        "_internal/resources/ui/index.html",
        "_internal/resources/rules/engines.yaml",
        "_internal/resources/manifests/ludusavi/manifest.yaml",
        "_internal/resources/manifests/ludusavi/manifest-meta.json",
        "_internal/resources/manifests/ludusavi/manifest-index.sqlite",
        "_internal/gameshelf/db/migrations/0001_initial.sql",
        "_internal/gameshelf/db/migrations/0002_initial.sql",
        "_internal/gameshelf/db/migrations/0003_initial.sql",
        "_internal/gameshelf/db/migrations/0004_initial.sql",
    ]
    critical_files.append(
        "runtime/msedgewebview2.exe"
        if mode is ReleaseMode.FIXED
        else "prerequisites/MicrosoftEdgeWebview2Setup.exe"
    )
    for relative in critical_files:
        if not release_root.joinpath(*relative.split("/")).is_file():
            raise ReleaseToolError(f"发布目录缺少关键文件：{relative}")
    _reject_reparse_descendants(release_root)


def _release_payload_files(release_root: Path) -> tuple[tuple[str, Path], ...]:
    entries: list[tuple[str, Path]] = []
    pending = [release_root]
    while pending:
        directory = pending.pop()
        for child in directory.iterdir():
            if _is_reparse_point(child):
                raise ReleaseToolError(f"发布目录不能包含重解析点或链接：{child}")
            relative = child.relative_to(release_root).as_posix()
            if any(part.casefold() == "data" for part in child.relative_to(release_root).parts):
                raise ReleaseToolError(f"发布目录不能包含 data：{relative}")
            if child.suffix.casefold() == ".cab":
                raise ReleaseToolError(f"发布目录不能包含输入 CAB：{relative}")
            if child.is_dir():
                pending.append(child)
            elif child.is_file() and relative != "release-manifest.json":
                entries.append((relative, child))
            elif not child.is_file():
                raise ReleaseToolError(f"发布目录包含不支持的文件类型：{relative}")
    return tuple(sorted(entries, key=lambda entry: entry[0]))


def _write_json_atomic(destination: Path, payload: object) -> None:
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)


def _write_text_atomic(destination: Path, content: str, *, encoding: str) -> None:
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding=encoding, newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)


def _valid_digest(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _reject_reparse_descendants(root: Path) -> None:
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            children = tuple(directory.iterdir())
        except OSError as error:
            raise ReleaseToolError(f"无法检查 WebView2 解包目录：{error}") from error
        for child in children:
            if _is_reparse_point(child):
                raise ReleaseToolError(
                    f"WebView2 解包内容不能包含重解析点或链接：{child}"
                )
            if child.is_dir():
                pending.append(child)


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction) and is_junction():
        return True
    try:
        attributes = path.stat(follow_symlinks=False).st_file_attributes
    except (AttributeError, OSError):
        return False
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GameShelf 离线发布工具。")
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify = subparsers.add_parser("verify-context")
    verify.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    verify.add_argument("--webview-archive", type=Path, required=True)
    verify.add_argument("--webview-bootstrapper", type=Path, required=True)
    prepare = subparsers.add_parser("prepare-build-root")
    prepare.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    extract = subparsers.add_parser("extract-runtime")
    extract.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    extract.add_argument("--webview-archive", type=Path, required=True)
    extract.add_argument("--destination", type=Path, required=True)
    manifest = subparsers.add_parser("write-manifest")
    manifest.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    manifest.add_argument("--release-directory", type=Path, required=True)
    manifest.add_argument(
        "--runtime-mode",
        choices=tuple(mode.value for mode in ReleaseMode),
        required=True,
    )
    verify_release = subparsers.add_parser("verify-release")
    verify_release.add_argument(
        "--repository-root", type=Path, default=REPOSITORY_ROOT
    )
    verify_release.add_argument("--release-directory", type=Path, required=True)
    verify_release.add_argument(
        "--runtime-mode",
        choices=tuple(mode.value for mode in ReleaseMode),
        required=True,
    )
    archive = subparsers.add_parser("build-archive")
    archive.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    archive.add_argument("--release-directory", type=Path, required=True)
    archive.add_argument("--archive", type=Path, required=True)
    archive.add_argument("--checksum", type=Path, required=True)
    archive.add_argument(
        "--runtime-mode",
        choices=tuple(mode.value for mode in ReleaseMode),
        required=True,
    )
    publish = subparsers.add_parser("publish")
    publish.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    for mode in ReleaseMode:
        prefix = f"--{mode.value}"
        publish.add_argument(f"{prefix}-release-directory", type=Path, required=True)
        publish.add_argument(f"{prefix}-archive", type=Path, required=True)
        publish.add_argument(f"{prefix}-checksum", type=Path, required=True)
    arguments = parser.parse_args(argv)
    root = arguments.repository_root.resolve(strict=True)
    versions = ReleaseVersions.load(root)
    if arguments.command == "verify-context":
        config = _controlled_webview_config(root)
        bootstrapper_config = _controlled_bootstrapper_config(root)
        validate_webview_archive(arguments.webview_archive, config)
        validate_webview_bootstrapper(
            arguments.webview_bootstrapper,
            bootstrapper_config,
        )
        print(
            json.dumps(
                {
                    "version": versions.version,
                    "fixedReleaseName": versions.name_for(ReleaseMode.FIXED),
                    "evergreenReleaseName": versions.name_for(
                        ReleaseMode.EVERGREEN
                    ),
                    "webview2Version": config.version,
                    "webview2ArchiveSha256": config.sha256,
                    "webview2BootstrapperFileVersion": (
                        bootstrapper_config.file_version
                    ),
                    "webview2BootstrapperSha256": bootstrapper_config.sha256,
                },
                ensure_ascii=False,
            )
        )
        return 0
    if arguments.command == "prepare-build-root":
        print(prepare_build_root(root, versions))
        return 0
    build_root = validate_managed_target(
        root,
        root / "build" / "release",
        versions,
    )
    if arguments.command == "extract-runtime":
        config = _controlled_webview_config(root)
        validate_webview_archive(arguments.webview_archive, config)
        extracted = extract_webview2_cab(
            arguments.webview_archive,
            arguments.destination,
            _windows_system_tool("expand.exe"),
            release_root=build_root,
        )
        print(normalize_webview_runtime(extracted))
        return 0
    if arguments.command == "write-manifest":
        _require_descendant(arguments.release_directory, build_root)
        config = _controlled_webview_config(root)
        metadata = collect_release_metadata(root, config)
        mode = ReleaseMode(arguments.runtime_mode)
        manifest_bootstrapper_config = (
            _controlled_bootstrapper_config(root)
            if mode is ReleaseMode.EVERGREEN
            else None
        )
        print(
            write_release_manifest(
                arguments.release_directory,
                metadata,
                mode,
                bootstrapper_config=manifest_bootstrapper_config,
            )
        )
        return 0
    if arguments.command == "verify-release":
        _require_descendant(arguments.release_directory, build_root)
        verify_release_tree(
            arguments.release_directory,
            versions,
            ReleaseMode(arguments.runtime_mode),
        )
        print(arguments.release_directory)
        return 0
    if arguments.command == "build-archive":
        for path in (
            arguments.release_directory,
            arguments.archive,
            arguments.checksum,
        ):
            _require_descendant(path, build_root)
        mode = ReleaseMode(arguments.runtime_mode)
        create_release_zip(
            arguments.release_directory,
            arguments.archive,
            versions,
            mode,
        )
        verify_release_zip(arguments.archive, versions, mode)
        write_zip_sha256(arguments.archive, arguments.checksum)
        verify_zip_sha256(arguments.archive, arguments.checksum)
        print(arguments.archive)
        return 0
    if arguments.command == "publish":
        staged_releases = tuple(
            StagedRelease(
                mode=mode,
                directory=getattr(arguments, f"{mode.value}_release_directory"),
                archive=getattr(arguments, f"{mode.value}_archive"),
                checksum=getattr(arguments, f"{mode.value}_checksum"),
            )
            for mode in ReleaseMode
        )
        published = publish_releases(
            root,
            staged_releases,
            versions,
        )
        print(json.dumps([str(path) for path in published], ensure_ascii=False))
        return 0
    raise ReleaseToolError(f"不支持的发布命令：{arguments.command}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ReleaseToolError as error:
        print(f"发布失败：{error}", file=sys.stderr)
        raise SystemExit(2) from error
