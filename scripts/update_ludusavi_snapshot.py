"""维护者命令：下载并固定一份经过校验的 Ludusavi 清单资源。"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.request
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from uuid import uuid4

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

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


def main() -> int:
    manifest, etag = _download(MANIFEST_URL, MAX_BYTES)
    parse_manifest(StringIO(manifest.decode("utf-8")), skip_invalid_paths=True)
    license_text, _ = _download(LICENSE_URL, 1024 * 1024)
    commit_payload, _ = _download(COMMITS_URL, 1024 * 1024)
    commit_data = json.loads(commit_payload.decode("utf-8"))
    if not isinstance(commit_data, list) or not commit_data:
        raise RuntimeError("GitHub commits API 未返回上游提交。")
    commit = commit_data[0].get("sha")
    if not isinstance(commit, str) or len(commit) != 40:
        raise RuntimeError("GitHub commits API 返回的 SHA 无效。")

    destination = REPOSITORY_ROOT / "resources" / "manifests" / "ludusavi"
    destination.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(manifest).hexdigest()
    metadata = {
        "etag": etag,
        "sha256": digest,
        "downloadedAt": datetime.now(UTC).isoformat(timespec="seconds"),
        "sourceUrl": MANIFEST_URL,
        "upstreamCommit": commit,
    }
    _atomic_write(destination / "manifest.yaml", manifest)
    _atomic_write(
        destination / "manifest-meta.json",
        (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    _atomic_write(destination / "LICENSE", license_text)
    print(f"已更新 Ludusavi 快照：{commit} ({digest})")
    return 0


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


def _atomic_write(destination: Path, content: bytes) -> None:
    temporary = destination.parent / f".{destination.name}.{uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
