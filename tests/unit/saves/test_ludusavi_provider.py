from __future__ import annotations

import hashlib
import json
import os
import urllib.error
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

import pytest

import gameshelf.saves.ludusavi_provider as provider_module
from gameshelf.saves.ludusavi_provider import LudusaviProvider, SnapshotUpdateError

OLD_MANIFEST = (
    b"Alice:\n  files:\n    <base>/save: {tags: [save]}\n"
    b"    PCGamingWiki note: {tags: [save]}\n"
)
NEW_MANIFEST = b"Bob:\n  files:\n    <winAppData>/Bob: {tags: [save]}\n"


@dataclass
class FakeResponse:
    status: int
    body: bytes
    headers: dict[str, str]
    stream: BytesIO = field(init=False)

    def __post_init__(self) -> None:
        self.stream = BytesIO(self.body)

    def read(self, size: int = -1) -> bytes:
        return self.stream.read(size)

    def getheader(self, name: str, default: str | None = None) -> str | None:
        return self.headers.get(name, default)

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


@dataclass
class FakeHttp:
    responses: list[FakeResponse] = field(default_factory=list)
    calls: list[tuple[str, dict[str, str], float]] = field(default_factory=list)

    def respond(
        self,
        status: int,
        body: bytes,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.responses.append(FakeResponse(status, body, headers or {}))

    def open(self, url: str, headers: dict[str, str], timeout: float) -> FakeResponse:
        self.calls.append((url, headers, timeout))
        return self.responses.pop(0)


@pytest.fixture
def provider(tmp_path: Path) -> tuple[LudusaviProvider, FakeHttp]:
    return _provider_with_resource(tmp_path, OLD_MANIFEST, OLD_MANIFEST)


def _provider_with_resource(
    tmp_path: Path,
    resource_bytes: bytes,
    expected_bytes: bytes,
) -> tuple[LudusaviProvider, FakeHttp]:
    resources = tmp_path / "resources" / "ludusavi"
    resources.mkdir(parents=True)
    (resources / "manifest.yaml").write_bytes(resource_bytes)
    (resources / "manifest-meta.json").write_text(
        json.dumps(
            {
                "etag": '"old"',
                "sha256": hashlib.sha256(expected_bytes).hexdigest(),
                "downloadedAt": "2026-08-12T00:00:00+00:00",
                "sourceUrl": LudusaviProvider.UPDATE_URL,
                "upstreamCommit": "abc123",
            }
        ),
        encoding="utf-8",
    )
    (resources / "LICENSE").write_text("MIT", encoding="utf-8")
    fake_http = FakeHttp()
    return (
        LudusaviProvider(
            resource_dir=resources,
            active_dir=tmp_path / "data" / "manifests" / "ludusavi",
            temp_dir=tmp_path / "data" / "temp",
            http_open=fake_http.open,
        ),
        fake_http,
    )


def test_initial_snapshot_repairs_only_crlf_difference(tmp_path: Path) -> None:
    expected = OLD_MANIFEST
    service, fake_http = _provider_with_resource(
        tmp_path,
        expected.replace(b"\n", b"\r\n"),
        expected,
    )

    service.ensure_initial_snapshot()

    assert service.active_manifest.read_bytes() == expected
    assert service.metadata().sha256 == hashlib.sha256(expected).hexdigest()
    assert fake_http.calls == []


def test_initial_snapshot_rejects_non_newline_content_change(tmp_path: Path) -> None:
    service, _ = _provider_with_resource(
        tmp_path,
        OLD_MANIFEST + b"tampered",
        OLD_MANIFEST,
    )

    with pytest.raises(SnapshotUpdateError, match="SHA-256"):
        service.ensure_initial_snapshot()


def test_initial_snapshot_copies_resource_without_network(
    provider: tuple[LudusaviProvider, FakeHttp],
) -> None:
    service, fake_http = provider

    service.ensure_initial_snapshot()

    assert service.active_manifest.read_bytes() == OLD_MANIFEST
    assert service.load().games["Alice"].canonical_name == "Alice"
    assert fake_http.calls == []


def test_explicit_update_uses_etag_and_keeps_old_file_on_invalid_yaml(
    provider: tuple[LudusaviProvider, FakeHttp],
) -> None:
    service, fake_http = provider
    service.ensure_initial_snapshot()
    old_hash = _sha256(service.active_manifest)
    fake_http.respond(200, b"not: [valid", headers={"ETag": '"new"'})

    result = service.update_explicitly()

    assert result.status == "invalid"
    assert _sha256(service.active_manifest) == old_hash
    assert fake_http.calls[0][1]["If-None-Match"] == '"old"'
    assert fake_http.calls[0][2] == 30.0


def test_not_modified_does_not_rewrite_snapshot(
    provider: tuple[LudusaviProvider, FakeHttp],
) -> None:
    service, fake_http = provider
    service.ensure_initial_snapshot()
    before_bytes = (
        service.active_manifest.read_bytes(),
        service.active_metadata.read_bytes(),
    )
    before_mtimes = (
        service.active_manifest.stat().st_mtime_ns,
        service.active_metadata.stat().st_mtime_ns,
    )
    fake_http.respond(304, b"")

    assert service.update_explicitly().status == "not_modified"
    assert (
        service.active_manifest.read_bytes(),
        service.active_metadata.read_bytes(),
    ) == before_bytes
    assert (
        service.active_manifest.stat().st_mtime_ns,
        service.active_metadata.stat().st_mtime_ns,
    ) == before_mtimes


def test_successful_update_atomically_replaces_manifest_and_metadata(
    provider: tuple[LudusaviProvider, FakeHttp],
) -> None:
    service, fake_http = provider
    service.ensure_initial_snapshot()
    fake_http.respond(
        200,
        NEW_MANIFEST,
        headers={"ETag": '"new"', "Content-Length": str(len(NEW_MANIFEST))},
    )

    result = service.update_explicitly()

    assert result.status == "updated"
    assert service.active_manifest.read_bytes() == NEW_MANIFEST
    assert service.metadata().etag == '"new"'
    assert service.metadata().sha256 == hashlib.sha256(NEW_MANIFEST).hexdigest()
    assert len(list(service.previous_dir.glob("*.yaml"))) == 1


def test_invalid_active_pair_restores_latest_valid_backup(
    provider: tuple[LudusaviProvider, FakeHttp],
) -> None:
    service, fake_http = provider
    service.ensure_initial_snapshot()
    backup = service._backup_active_pair()
    assert backup is not None
    service.active_manifest.write_bytes(b"broken")

    loaded = service.load()

    assert loaded.games["Alice"].canonical_name == "Alice"
    assert service.active_manifest.read_bytes() == OLD_MANIFEST
    assert fake_http.calls == []


def test_partial_active_pair_is_not_used(
    provider: tuple[LudusaviProvider, FakeHttp],
) -> None:
    service, _ = provider
    service.ensure_initial_snapshot()
    service.active_metadata.unlink()

    service.ensure_initial_snapshot()

    assert service.active_manifest.read_bytes() == OLD_MANIFEST
    assert service.active_metadata.is_file()


def test_backup_pairs_are_pruned_together(
    provider: tuple[LudusaviProvider, FakeHttp],
) -> None:
    service, _ = provider
    service.ensure_initial_snapshot()
    for _ in range(3):
        assert service._backup_active_pair() is not None

    service._prune_previous()

    assert len(list(service.previous_dir.glob("*.yaml"))) == 2
    assert len(list(service.previous_dir.glob("*.json"))) == 2


def test_update_reports_stages_and_rechecks_download_hash(
    provider: tuple[LudusaviProvider, FakeHttp],
) -> None:
    service, fake_http = provider
    service.ensure_initial_snapshot()
    fake_http.respond(200, NEW_MANIFEST, headers={"ETag": '"new"'})
    stages: list[str] = []

    result = service.update_explicitly(stages.append)

    assert result.status == "updated"
    assert stages == ["connecting", "downloading", "validating", "replacing"]
    assert result.metadata is not None
    assert _sha256(service.active_manifest) == result.metadata.sha256


def test_update_without_existing_snapshot_can_create_first_valid_pair(
    tmp_path: Path,
) -> None:
    service, fake_http = _provider_with_resource(tmp_path, b"broken", OLD_MANIFEST)
    fake_http.respond(200, NEW_MANIFEST, headers={"ETag": '"new"'})

    result = service.update_explicitly()

    assert result.status == "updated"
    assert "If-None-Match" not in fake_http.calls[0][1]
    assert service.load().games["Bob"].canonical_name == "Bob"


def test_metadata_replace_failure_restores_old_pair(
    provider: tuple[LudusaviProvider, FakeHttp],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, fake_http = provider
    service.ensure_initial_snapshot()
    before_manifest = service.active_manifest.read_bytes()
    before_metadata = service.active_metadata.read_bytes()
    fake_http.respond(200, NEW_MANIFEST)
    original_replace = os.replace
    failed = False

    def fail_first_new_metadata(source: Path, destination: Path) -> None:
        nonlocal failed
        if destination == service.active_metadata and not failed:
            failed = True
            raise OSError("metadata disk failure")
        original_replace(source, destination)

    monkeypatch.setattr(
        "gameshelf.saves.ludusavi_provider.os.replace",
        fail_first_new_metadata,
    )

    result = service.update_explicitly()

    assert result.status == "failed"
    assert service.active_manifest.read_bytes() == before_manifest
    assert service.active_metadata.read_bytes() == before_metadata


@pytest.mark.parametrize(
    ("status", "body", "headers", "expected_status"),
    [
        (500, b"", {}, "failed"),
        (200, b"\xff\xfe", {}, "invalid"),
        (200, b"not: [valid", {}, "invalid"),
        (
            200,
            b"",
            {"Content-Length": str(provider_module.MAX_DOWNLOAD_BYTES + 1)},
            "invalid",
        ),
    ],
)
def test_invalid_responses_preserve_active_pair(
    provider: tuple[LudusaviProvider, FakeHttp],
    status: int,
    body: bytes,
    headers: dict[str, str],
    expected_status: str,
) -> None:
    service, fake_http = provider
    service.ensure_initial_snapshot()
    before = (
        service.active_manifest.read_bytes(),
        service.active_metadata.read_bytes(),
    )
    fake_http.respond(status, body, headers)

    result = service.update_explicitly()

    assert result.status == expected_status
    assert (
        service.active_manifest.read_bytes(),
        service.active_metadata.read_bytes(),
    ) == before


def test_stream_larger_than_limit_preserves_active_pair(
    provider: tuple[LudusaviProvider, FakeHttp],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, fake_http = provider
    service.ensure_initial_snapshot()
    before = (
        service.active_manifest.read_bytes(),
        service.active_metadata.read_bytes(),
    )
    monkeypatch.setattr(provider_module, "MAX_DOWNLOAD_BYTES", 8)
    fake_http.respond(200, b"Alice: {}")

    result = service.update_explicitly()

    assert result.status == "invalid"
    assert (
        service.active_manifest.read_bytes(),
        service.active_metadata.read_bytes(),
    ) == before


def test_network_failure_preserves_active_pair(
    provider: tuple[LudusaviProvider, FakeHttp],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, fake_http = provider
    service.ensure_initial_snapshot()
    before = (
        service.active_manifest.read_bytes(),
        service.active_metadata.read_bytes(),
    )

    def offline(*_args: object) -> FakeResponse:
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(service, "_http_open", offline)

    result = service.update_explicitly()

    assert result.status == "failed"
    assert "无法下载" in result.message
    assert (
        service.active_manifest.read_bytes(),
        service.active_metadata.read_bytes(),
    ) == before
    assert fake_http.calls == []


def test_download_hash_recheck_failure_preserves_active_pair(
    provider: tuple[LudusaviProvider, FakeHttp],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, fake_http = provider
    service.ensure_initial_snapshot()
    before = (
        service.active_manifest.read_bytes(),
        service.active_metadata.read_bytes(),
    )
    fake_http.respond(200, NEW_MANIFEST)
    real_sha256_file = provider_module._sha256_file

    def wrong_download_hash(path: Path) -> str:
        if path.name.startswith("ludusavi-download-"):
            return "0" * 64
        return real_sha256_file(path)

    monkeypatch.setattr(provider_module, "_sha256_file", wrong_download_hash)

    result = service.update_explicitly()

    assert result.status == "invalid"
    assert (
        service.active_manifest.read_bytes(),
        service.active_metadata.read_bytes(),
    ) == before
    assert list(service.previous_dir.glob("manifest-*.yaml")) == []


def test_update_rejects_non_https_url_and_oversize_response(
    provider: tuple[LudusaviProvider, FakeHttp],
    tmp_path: Path,
) -> None:
    service, fake_http = provider
    fake_http.respond(200, b"", headers={"Content-Length": str(64 * 1024 * 1024 + 1)})

    assert service.update_explicitly().status == "invalid"
    with pytest.raises(SnapshotUpdateError, match="HTTPS"):
        LudusaviProvider(
            resource_dir=tmp_path,
            active_dir=tmp_path / "active",
            temp_dir=tmp_path / "temp",
            update_url="http://example.com/manifest.yaml",
        )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
