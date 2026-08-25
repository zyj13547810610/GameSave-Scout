from __future__ import annotations

import hashlib
import json
import os
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from io import BytesIO, StringIO
from pathlib import Path

import pytest

import gamesave_scout.saves.ludusavi_provider as provider_module
from gamesave_scout.saves.ludusavi_index import InvalidLudusaviIndex, LudusaviIndex
from gamesave_scout.saves.ludusavi_index_builder import build_ludusavi_index
from gamesave_scout.saves.ludusavi_parser import parse_manifest
from gamesave_scout.saves.ludusavi_provider import LudusaviProvider, SnapshotUpdateError

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


def test_status_uses_bundled_snapshot_without_copying_active_files(
    provider: tuple[LudusaviProvider, FakeHttp],
) -> None:
    service, fake_http = provider
    service.active_dir.mkdir(parents=True, exist_ok=True)

    status = service.status()

    assert status.available is True
    assert status.source == "bundled"
    assert status.metadata is not None
    assert status.bundled_sha256 == hashlib.sha256(OLD_MANIFEST).hexdigest()
    assert list(service.active_dir.iterdir()) == []
    assert fake_http.calls == []


def test_bundled_crlf_checkout_is_validated_without_copying(
    tmp_path: Path,
) -> None:
    service, _ = _provider_with_resource(
        tmp_path,
        OLD_MANIFEST.replace(b"\n", b"\r\n"),
        OLD_MANIFEST,
    )

    service.ensure_initial_snapshot()

    assert service.status().source == "bundled"
    assert list(service.active_dir.iterdir()) == []


def test_status_does_not_parse_yaml_rebuild_or_use_network(
    provider: tuple[LudusaviProvider, FakeHttp],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, fake_http = provider

    def fail(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("状态查询不得解析 YAML、重建索引或访问网络")

    monkeypatch.setattr(provider_module, "parse_manifest", fail)
    monkeypatch.setattr(provider_module, "build_ludusavi_index", fail)

    assert service.status().source == "bundled"
    assert fake_http.calls == []


def test_status_prefers_valid_active_and_falls_back_without_modifying_damage(
    provider: tuple[LudusaviProvider, FakeHttp],
) -> None:
    service, _ = provider
    _install_bundled_as_active(service)

    assert service.status().source == "active"
    service.active_index.write_bytes(b"broken")

    status = service.status()

    assert status.source == "bundled"
    assert service.active_index.read_bytes() == b"broken"


@pytest.mark.parametrize("damaged", ["manifest.yaml", "manifest-meta.json"])
def test_invalid_active_source_falls_back_without_repairing(
    provider: tuple[LudusaviProvider, FakeHttp],
    damaged: str,
) -> None:
    service, _ = provider
    _install_bundled_as_active(service)
    target = service.active_dir / damaged
    target.write_bytes(b"broken")

    assert service.status().source == "bundled"
    assert target.read_bytes() == b"broken"


def test_status_is_unavailable_when_active_and_bundled_are_both_invalid(
    provider: tuple[LudusaviProvider, FakeHttp],
) -> None:
    service, _ = provider
    _install_bundled_as_active(service)
    service.active_manifest.write_bytes(b"broken")
    (service.resource_dir / "manifest-index.sqlite").write_bytes(b"broken")

    status = service.status()

    assert status.available is False
    assert status.source is None
    assert status.metadata is None
    assert status.unavailable_reason


def test_index_session_reads_bundled_without_creating_active_files(
    provider: tuple[LudusaviProvider, FakeHttp],
) -> None:
    service, _ = provider

    with service.index_session() as index:
        assert index.load_games({1})[1].canonical_name == "Alice"

    assert list(service.active_dir.iterdir()) == []


def test_index_session_rebuilds_only_damaged_active_index_once(
    provider: tuple[LudusaviProvider, FakeHttp],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _ = provider
    _install_bundled_as_active(service)
    service.active_index.write_bytes(b"broken")
    real_build = provider_module.build_ludusavi_index
    calls = 0

    def counted_build(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return real_build(*args, **kwargs)

    monkeypatch.setattr(provider_module, "build_ludusavi_index", counted_build)

    with service.index_session() as first:
        first.probe()
    with service.index_session() as second:
        second.probe()

    assert calls == 1
    assert service.status().source == "active"


def test_concurrent_active_index_sessions_rebuild_once(
    provider: tuple[LudusaviProvider, FakeHttp],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _ = provider
    _install_bundled_as_active(service)
    service.active_index.write_bytes(b"broken")
    real_build = provider_module.build_ludusavi_index
    calls = 0

    def counted_build(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return real_build(*args, **kwargs)

    def digest(_index: int) -> str:
        with service.index_session() as index:
            return index.metadata.manifest_sha256

    monkeypatch.setattr(provider_module, "build_ludusavi_index", counted_build)
    with ThreadPoolExecutor(max_workers=2) as executor:
        digests = tuple(executor.map(digest, range(2)))

    assert digests == (hashlib.sha256(OLD_MANIFEST).hexdigest(),) * 2
    assert calls == 1


def test_failed_active_index_rebuild_uses_bundled_unchanged(
    provider: tuple[LudusaviProvider, FakeHttp],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _ = provider
    _install_bundled_as_active(service)
    service.active_index.write_bytes(b"broken")

    def fail(*_args: object, **_kwargs: object) -> object:
        raise OSError("disk full")

    monkeypatch.setattr(provider_module, "build_ludusavi_index", fail)

    with service.index_session() as index:
        assert index.load_games({1})[1].canonical_name == "Alice"

    assert service.active_index.read_bytes() == b"broken"


def test_restore_bundled_removes_only_active_triplet_and_is_idempotent(
    provider: tuple[LudusaviProvider, FakeHttp],
) -> None:
    service, _ = provider
    _install_bundled_as_active(service)
    unrelated = service.active_dir / "keep.txt"
    unrelated.write_text("keep", encoding="utf-8")

    first = service.restore_bundled()
    second = service.restore_bundled()

    assert first.source == second.source == "bundled"
    assert unrelated.read_text(encoding="utf-8") == "keep"
    assert not any(path.exists() for path in _active_paths(service))


def test_restore_rejects_invalid_bundled_without_touching_active(
    provider: tuple[LudusaviProvider, FakeHttp],
) -> None:
    service, _ = provider
    _install_bundled_as_active(service)
    before = _bundle_bytes(service)
    (service.resource_dir / "manifest-index.sqlite").write_bytes(b"broken")

    with pytest.raises(SnapshotUpdateError, match="索引"):
        service.restore_bundled()

    assert _bundle_bytes(service) == before


def test_restore_delete_failure_restores_active_triplet(
    provider: tuple[LudusaviProvider, FakeHttp],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _ = provider
    _install_bundled_as_active(service)
    before = _bundle_bytes(service)
    original_unlink = Path.unlink
    failed = False

    def fail_metadata_once(path: Path, *args: object, **kwargs: object) -> None:
        nonlocal failed
        if path == service.active_metadata and not failed:
            failed = True
            raise OSError("locked")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_metadata_once)

    with pytest.raises(SnapshotUpdateError, match="活动文件已恢复"):
        service.restore_bundled()

    assert _bundle_bytes(service) == before


def test_update_reports_cold_probe_and_parses_download_once(
    provider: tuple[LudusaviProvider, FakeHttp],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, fake_http = provider
    fake_http.respond(200, NEW_MANIFEST, headers={"ETag": '"new"'})
    stages: list[str] = []
    real_parse = provider_module.parse_manifest
    parses = 0

    def counted_parse(*args: object, **kwargs: object) -> object:
        nonlocal parses
        parses += 1
        return real_parse(*args, **kwargs)

    monkeypatch.setattr(provider_module, "parse_manifest", counted_parse)

    result = service.update_explicitly(stages.append)

    assert result.status == "updated"
    assert stages == [
        "connecting",
        "downloading",
        "validating",
        "indexing",
        "probing",
        "replacing",
    ]
    assert parses == 1
    assert service.status().source == "active"
    assert service.active_manifest.read_bytes() == NEW_MANIFEST


def test_probe_failure_preserves_original_active_snapshot(
    provider: tuple[LudusaviProvider, FakeHttp],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, fake_http = provider
    _install_bundled_as_active(service)
    before = _bundle_bytes(service)
    fake_http.respond(200, NEW_MANIFEST)

    def fail_probe(_index: LudusaviIndex) -> None:
        raise InvalidLudusaviIndex("probe failed")

    monkeypatch.setattr(LudusaviIndex, "probe", fail_probe)

    result = service.update_explicitly()

    assert result.status == "failed"
    assert _bundle_bytes(service) == before


@pytest.mark.parametrize("failed_target", ["manifest", "metadata", "index"])
def test_each_replace_failure_restores_original_active_snapshot(
    provider: tuple[LudusaviProvider, FakeHttp],
    monkeypatch: pytest.MonkeyPatch,
    failed_target: str,
) -> None:
    service, fake_http = provider
    _install_bundled_as_active(service)
    before = _bundle_bytes(service)
    fake_http.respond(200, NEW_MANIFEST)
    destination = {
        "manifest": service.active_manifest,
        "metadata": service.active_metadata,
        "index": service.active_index,
    }[failed_target]
    original_replace = os.replace
    failed = False

    def fail_once(source: Path, target: Path) -> None:
        nonlocal failed
        if target == destination and not failed:
            failed = True
            raise OSError("replace failed")
        original_replace(source, target)

    monkeypatch.setattr(provider_module.os, "replace", fail_once)

    result = service.update_explicitly()

    assert result.status == "failed"
    assert _bundle_bytes(service) == before


def test_update_uses_selected_etag_and_304_does_not_create_active(
    provider: tuple[LudusaviProvider, FakeHttp],
) -> None:
    service, fake_http = provider
    fake_http.respond(304, b"")

    result = service.update_explicitly()

    assert result.status == "not_modified"
    assert fake_http.calls[0][1]["If-None-Match"] == '"old"'
    assert fake_http.calls[0][2] == 30.0
    assert list(service.active_dir.iterdir()) == []


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
def test_invalid_responses_preserve_active_snapshot(
    provider: tuple[LudusaviProvider, FakeHttp],
    status: int,
    body: bytes,
    headers: dict[str, str],
    expected_status: str,
) -> None:
    service, fake_http = provider
    _install_bundled_as_active(service)
    before = _bundle_bytes(service)
    fake_http.respond(status, body, headers)

    result = service.update_explicitly()

    assert result.status == expected_status
    assert _bundle_bytes(service) == before


def test_stream_limit_and_download_hash_failure_preserve_active(
    provider: tuple[LudusaviProvider, FakeHttp],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, fake_http = provider
    _install_bundled_as_active(service)
    before = _bundle_bytes(service)
    monkeypatch.setattr(provider_module, "MAX_DOWNLOAD_BYTES", 8)
    fake_http.respond(200, b"Alice: {}")

    assert service.update_explicitly().status == "invalid"
    assert _bundle_bytes(service) == before

    monkeypatch.setattr(provider_module, "MAX_DOWNLOAD_BYTES", 64 * 1024 * 1024)
    fake_http.respond(200, NEW_MANIFEST)
    real_sha = provider_module._sha256_file

    def wrong_hash(path: Path) -> str:
        if path.name.startswith("ludusavi-download-"):
            return "0" * 64
        return real_sha(path)

    monkeypatch.setattr(provider_module, "_sha256_file", wrong_hash)
    assert service.update_explicitly().status == "invalid"
    assert _bundle_bytes(service) == before


def test_network_and_index_build_failures_preserve_active(
    provider: tuple[LudusaviProvider, FakeHttp],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, fake_http = provider
    _install_bundled_as_active(service)
    before = _bundle_bytes(service)

    def offline(*_args: object) -> FakeResponse:
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(service, "_http_open", offline)
    assert service.update_explicitly().status == "failed"
    assert _bundle_bytes(service) == before

    monkeypatch.setattr(service, "_http_open", fake_http.open)
    fake_http.respond(200, NEW_MANIFEST)

    def fail_build(*_args: object, **_kwargs: object) -> object:
        raise OSError("disk full")

    monkeypatch.setattr(provider_module, "build_ludusavi_index", fail_build)
    assert service.update_explicitly().status == "failed"
    assert _bundle_bytes(service) == before


def test_update_rejects_non_https_url(tmp_path: Path) -> None:
    with pytest.raises(SnapshotUpdateError, match="HTTPS"):
        LudusaviProvider(
            resource_dir=tmp_path,
            active_dir=tmp_path / "active",
            temp_dir=tmp_path / "temp",
            update_url="http://example.com/manifest.yaml",
        )


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
    manifest = parse_manifest(
        StringIO(expected_bytes.decode("utf-8")),
        skip_invalid_paths=True,
    )
    build_ludusavi_index(
        resources / "manifest-index.sqlite",
        manifest,
        manifest_sha256=hashlib.sha256(expected_bytes).hexdigest(),
    )
    fake_http = FakeHttp()
    return (
        LudusaviProvider(
            resource_dir=resources,
            active_dir=tmp_path / "data" / "rules" / "ludusavi",
            temp_dir=tmp_path / "data" / "temp",
            http_open=fake_http.open,
        ),
        fake_http,
    )


def _install_bundled_as_active(service: LudusaviProvider) -> None:
    service.active_dir.mkdir(parents=True, exist_ok=True)
    for name in ("manifest.yaml", "manifest-meta.json", "manifest-index.sqlite"):
        (service.active_dir / name).write_bytes((service.resource_dir / name).read_bytes())


def _active_paths(service: LudusaviProvider) -> tuple[Path, Path, Path]:
    return service.active_manifest, service.active_metadata, service.active_index


def _bundle_bytes(service: LudusaviProvider) -> tuple[bytes, bytes, bytes]:
    return (
        service.active_manifest.read_bytes(),
        service.active_metadata.read_bytes(),
        service.active_index.read_bytes(),
    )
