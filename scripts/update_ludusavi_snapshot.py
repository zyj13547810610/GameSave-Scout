"""维护者命令：下载并固定一份经过校验的 Ludusavi 清单资源。"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.request
from argparse import ArgumentParser
from collections.abc import Sequence
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from uuid import uuid4

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from gameshelf.saves.ludusavi_index import LudusaviIndex  # noqa: E402
from gameshelf.saves.ludusavi_index_builder import build_ludusavi_index  # noqa: E402
from gameshelf.saves.ludusavi_parser import parse_manifest  # noqa: E402

MANIFEST_URL = (
    "https://raw.githubusercontent.com/mtkennerly/"
    "ludusavi-manifest/master/data/manifest.yaml"
)
LICENSE_URL = (
    "https://raw.githubusercontent.com/mtkennerly/ludusavi-manifest/master/LICENSE"
)
COMMITS_URL = (
    "https://api.github.com/repos/mtkennerly/ludusavi-manifest/commits"
    "?path=data/manifest.yaml&per_page=1"
)
MAX_BYTES = 64 * 1024 * 1024
TIMEOUT_SECONDS = 30.0
USER_AGENT = "GameShelf snapshot maintainer/0.1"


def main(argv: Sequence[str] | None = None) -> int:
    parser = ArgumentParser(description="维护 GameShelf 内置 Ludusavi 快照。")
    parser.add_argument(
        "--rebuild-index-only",
        action="store_true",
        help="仅从当前已固定清单重新生成 SQLite 索引，不访问网络。",
    )
    arguments = parser.parse_args(argv)
    destination = REPOSITORY_ROOT / "resources" / "manifests" / "ludusavi"
    if arguments.rebuild_index_only:
        index = rebuild_index_from_snapshot(destination)
        print(f"已重建 Ludusavi 索引：{index}")
        return 0
    return update_snapshot(destination)


def update_snapshot(destination: Path) -> int:
    manifest_bytes, etag = _download(MANIFEST_URL, MAX_BYTES)
    digest = hashlib.sha256(manifest_bytes).hexdigest()
    manifest = parse_manifest(
        StringIO(manifest_bytes.decode("utf-8")),
        skip_invalid_paths=True,
    )
    license_text, _ = _download(LICENSE_URL, 1024 * 1024)
    commit_payload, _ = _download(COMMITS_URL, 1024 * 1024)
    commit_data = json.loads(commit_payload.decode("utf-8"))
    if (
        not isinstance(commit_data, list)
        or not commit_data
        or not isinstance(commit_data[0], dict)
    ):
        raise RuntimeError("GitHub commits API 未返回上游提交。")
    commit = commit_data[0].get("sha")
    if not isinstance(commit, str) or len(commit) != 40:
        raise RuntimeError("GitHub commits API 返回的 SHA 无效。")

    destination.mkdir(parents=True, exist_ok=True)
    metadata = {
        "etag": etag,
        "sha256": digest,
        "downloadedAt": datetime.now(UTC).isoformat(timespec="seconds"),
        "sourceUrl": MANIFEST_URL,
        "upstreamCommit": commit,
    }
    metadata_bytes = (
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    manifest_temporary = _temporary_path(destination, "manifest", ".tmp.yaml")
    metadata_temporary = _temporary_path(destination, "metadata", ".tmp.json")
    license_temporary = _temporary_path(destination, "license", ".tmp")
    index_temporary = _temporary_path(destination, "index", ".tmp.sqlite")
    temporaries = (
        manifest_temporary,
        metadata_temporary,
        license_temporary,
        index_temporary,
    )
    try:
        _write_new_file(manifest_temporary, manifest_bytes)
        _write_new_file(metadata_temporary, metadata_bytes)
        _write_new_file(license_temporary, license_text)
        build_ludusavi_index(
            index_temporary,
            manifest,
            manifest_sha256=digest,
        )
        LudusaviIndex.open(index_temporary, manifest_sha256=digest)
        if _sha256_file(manifest_temporary) != digest:
            raise RuntimeError("临时 Ludusavi 清单的 SHA-256 校验失败。")
        for source, target in (
            (manifest_temporary, destination / "manifest.yaml"),
            (metadata_temporary, destination / "manifest-meta.json"),
            (license_temporary, destination / "LICENSE"),
            (index_temporary, destination / "manifest-index.sqlite"),
        ):
            os.replace(source, target)
    finally:
        for temporary in temporaries:
            temporary.unlink(missing_ok=True)
    print(f"已更新 Ludusavi 快照：{commit} ({digest})")
    return 0


def rebuild_index_from_snapshot(directory: Path) -> Path:
    manifest_path = directory / "manifest.yaml"
    metadata_path = directory / "manifest-meta.json"
    manifest_bytes = manifest_path.read_bytes()
    expected_digest = _snapshot_digest(metadata_path)
    actual_digest = hashlib.sha256(manifest_bytes).hexdigest()
    if actual_digest != expected_digest:
        raise RuntimeError("Ludusavi 清单的 SHA-256 与元数据不一致。")
    manifest = parse_manifest(
        StringIO(manifest_bytes.decode("utf-8")),
        skip_invalid_paths=True,
    )
    destination = directory / "manifest-index.sqlite"
    temporary = _temporary_path(directory, "index", ".tmp.sqlite")
    try:
        build_ludusavi_index(
            temporary,
            manifest,
            manifest_sha256=expected_digest,
        )
        LudusaviIndex.open(temporary, manifest_sha256=expected_digest)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def _download(url: str, limit: int) -> tuple[bytes, str | None]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        if response.status != 200:
            raise RuntimeError(f"下载失败，HTTP {response.status}: {url}")
        declared = response.getheader("Content-Length")
        if declared is not None and int(declared) > limit:
            raise RuntimeError(f"下载内容超过限制：{url}")
        chunks: list[bytes] = []
        total = 0
        while chunk := response.read(1024 * 1024):
            total += len(chunk)
            if total > limit:
                raise RuntimeError(f"下载内容超过限制：{url}")
            chunks.append(chunk)
        return b"".join(chunks), response.getheader("ETag")


def _snapshot_digest(path: Path) -> str:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise RuntimeError("Ludusavi 元数据必须是 JSON 对象。")
    digest = loaded.get("sha256")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise RuntimeError("Ludusavi 元数据中的 SHA-256 无效。")
    return digest


def _temporary_path(directory: Path, label: str, suffix: str) -> Path:
    return directory / f".{label}.{uuid4().hex}{suffix}"


def _write_new_file(destination: Path, content: bytes) -> None:
    with destination.open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
