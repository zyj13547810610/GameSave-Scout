from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from io import BytesIO, StringIO
from pathlib import Path

import pytest

import gameshelf.saves.ludusavi_provider as provider_module
from gameshelf.saves.ludusavi_index_builder import build_ludusavi_index
from gameshelf.saves.ludusavi_parser import parse_manifest
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
    with service.index_session() as index:
        assert index.load_games({1})[1].canonical_name == "Alice"
    assert fake_http.calls == []


def test_metadata_uses_integrity_check_without_parsing_installed_manifest(
    provider: tuple[LudusaviProvider, FakeHttp],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _ = provider
    service.ensure_initial_snapshot()

    def fail_if_parsed(_content: bytes) -> None:
        raise AssertionError("metadata status must not parse the manifest")

    monkeypatch.setattr(provider_module, "_validate_manifest_bytes", fail_if_parsed)

    metadata = service.metadata()

    assert metadata.sha256 == hashlib.sha256(OLD_MANIFEST).hexdigest()


def test_metadata_validates_index_without_parsing_or_rebuilding(
    provider: tuple[LudusaviProvider, FakeHttp],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _ = provider
    service.ensure_initial_snapshot()

    def fail_parse(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("状态查询不得解析 YAML")

    def fail_build(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("状态查询不得重建索引")

    monkeypatch.setattr(provider_module, "parse_manifest", fail_parse)
    monkeypatch.setattr(provider_module, "build_ludusavi_index", fail_build)

    metadata = service.metadata()

    assert metadata.sha256 == hashlib.sha256(OLD_MANIFEST).hexdigest()


def test_metadata_reports_missing_index_without_rebuilding(
    provider: tuple[LudusaviProvider, FakeHttp],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _ = provider
    service.ensure_initial_snapshot()
    service.active_index.unlink()

    def fail_build(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("状态查询不得重建索引")

    monkeypatch.setattr(provider_module, "build_ludusavi_index", fail_build)

    with pytest.raises(SnapshotUpdateError, match="索引"):
        service.metadata()

    assert not service.active_index.exists()


def test_index_session_rebuilds_missing_active_index_once(
    provider: tuple[LudusaviProvider, FakeHttp],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _ = provider
    service.ensure_initial_snapshot()
    service.active_index.unlink()
    (service.resource_dir / "manifest-index.sqlite").unlink()
    real_build = provider_module.build_ludusavi_index
    calls = 0

    def counted_build(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return real_build(*args, **kwargs)

    monkeypatch.setattr(provider_module, "build_ludusavi_index", counted_build)

    with service.index_session() as first:
        first_digest = first.metadata.manifest_sha256
    with service.index_session() as second:
        second_digest = second.metadata.manifest_sha256

    assert first_digest == second_digest == hashlib.sha256(OLD_MANIFEST).hexdigest()
    assert calls == 1


def test_index_session_rebuilds_old_index_format_on_demand(
    provider: tuple[LudusaviProvider, FakeHttp],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _ = provider
    service.ensure_initial_snapshot()
    connection = sqlite3.connect(service.active_index)
    try:
        connection.execute("PRAGMA user_version = 1")
        connection.commit()
    finally:
        connection.close()
    (service.resource_dir / "manifest-index.sqlite").unlink()
    real_build = provider_module.build_ludusavi_index
    builds = 0

    def counted_build(*args: object, **kwargs: object) -> object:
        nonlocal builds
        builds += 1
        return real_build(*args, **kwargs)

    monkeypatch.setattr(provider_module, "build_ludusavi_index", counted_build)

    with service.index_session() as index:
        assert index.metadata.schema_version == 2
        assert index.metadata.path_rule_count == 0

    assert builds == 1


def test_concurrent_index_sessions_rebuild_once(
    provider: tuple[LudusaviProvider, FakeHttp],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _ = provider
    service.ensure_initial_snapshot()
    service.active_index.unlink()
    (service.resource_dir / "manifest-index.sqlite").unlink()
    real_build = provider_module.build_ludusavi_index
    calls = 0

    def counted_build(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return real_build(*args, **kwargs)

    def read_digest(_item: int) -> str:
        with service.index_session() as index:
            return index.metadata.manifest_sha256

    monkeypatch.setattr(provider_module, "build_ludusavi_index", counted_build)

    with ThreadPoolExecutor(max_workers=2) as executor:
        digests = tuple(executor.map(read_digest, range(2)))

    assert digests == (hashlib.sha256(OLD_MANIFEST).hexdigest(),) * 2
    assert calls == 1


def test_index_session_copies_matching_resource_index_without_parsing(
    provider: tuple[LudusaviProvider, FakeHttp],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _ = provider
    service.ensure_initial_snapshot()
    service.active_index.unlink()

    def fail_parse(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("同摘要内置索引可用时不得解析 YAML")

    def fail_build(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("同摘要内置索引可用时不得重建索引")

    monkeypatch.setattr(provider_module, "parse_manifest", fail_parse)
    monkeypatch.setattr(provider_module, "build_ludusavi_index", fail_build)

    with service.index_session() as index:
        assert index.metadata.manifest_sha256 == hashlib.sha256(
            OLD_MANIFEST
        ).hexdigest()

    assert service.active_index.is_file()


def test_index_session_recovers_damaged_source_before_opening_index(
    provider: tuple[LudusaviProvider, FakeHttp],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _ = provider
    service.ensure_initial_snapshot()
    backup = service._backup_active_pair()
    assert backup is not None
    service.active_manifest.write_bytes(b"broken")

    def fail_build(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("不得从摘要损坏的 YAML 构建索引")

    monkeypatch.setattr(provider_module, "build_ludusavi_index", fail_build)

    with service.index_session() as index:
        assert index.load_games({1})[1].canonical_name == "Alice"

    assert service.active_manifest.read_bytes() == OLD_MANIFEST


def test_index_digest_mismatch_rebuilds_current_source_without_restoring_resource(
    provider: tuple[LudusaviProvider, FakeHttp],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, fake_http = provider
    service.ensure_initial_snapshot()
    fake_http.respond(200, NEW_MANIFEST)
    assert service.update_explicitly().status == "updated"
    service.active_index.write_bytes(
        (service.resource_dir / "manifest-index.sqlite").read_bytes()
    )
    real_build = provider_module.build_ludusavi_index
    builds = 0

    def counted_build(*args: object, **kwargs: object) -> object:
        nonlocal builds
        builds += 1
        return real_build(*args, **kwargs)

    def fail_restore() -> bool:
        raise AssertionError("仅索引损坏时不得恢复较旧源快照")

    monkeypatch.setattr(provider_module, "build_ludusavi_index", counted_build)
    monkeypatch.setattr(service, "_restore_latest_valid_backup", fail_restore)

    with service.index_session() as index:
        assert index.metadata.manifest_sha256 == hashlib.sha256(
            NEW_MANIFEST
        ).hexdigest()

    assert service.active_manifest.read_bytes() == NEW_MANIFEST
    assert builds == 1


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
        service.active_index.read_bytes(),
    )
    before_mtimes = (
        service.active_manifest.stat().st_mtime_ns,
        service.active_metadata.stat().st_mtime_ns,
        service.active_index.stat().st_mtime_ns,
    )
    fake_http.respond(304, b"")

    assert service.update_explicitly().status == "not_modified"
    assert (
        service.active_manifest.read_bytes(),
        service.active_metadata.read_bytes(),
        service.active_index.read_bytes(),
    ) == before_bytes
    assert (
        service.active_manifest.stat().st_mtime_ns,
        service.active_metadata.stat().st_mtime_ns,
        service.active_index.stat().st_mtime_ns,
    ) == before_mtimes


def test_successful_update_replaces_manifest_metadata_and_index(
    provider: tuple[LudusaviProvider, FakeHttp],
) -> None:
    service, fake_http = provider
    service.ensure_initial_snapshot()
    old_index_digest = _sha256(service.active_index)
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
    assert _sha256(service.active_index) != old_index_digest
    with service.index_session() as index:
        assert index.metadata.manifest_sha256 == hashlib.sha256(
            NEW_MANIFEST
        ).hexdigest()
    assert len(list(service.previous_dir.glob("*.yaml"))) == 1
    assert len(list(service.previous_dir.glob("*.sqlite"))) == 1


def test_index_build_failure_preserves_active_bundle(
    provider: tuple[LudusaviProvider, FakeHttp],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, fake_http = provider
    service.ensure_initial_snapshot()
    before = _bundle_bytes(service)
    fake_http.respond(200, NEW_MANIFEST)

    def fail_build(*_args: object, **_kwargs: object) -> object:
        raise OSError("disk full")

    monkeypatch.setattr(provider_module, "build_ludusavi_index", fail_build)

    result = service.update_explicitly()

    assert result.status == "failed"
    assert _bundle_bytes(service) == before


def test_invalid_active_pair_restores_latest_valid_backup(
    provider: tuple[LudusaviProvider, FakeHttp],
) -> None:
    service, fake_http = provider
    service.ensure_initial_snapshot()
    backup = service._backup_active_pair()
    assert backup is not None
    backup_index = backup.manifest.with_suffix(".sqlite")
    assert backup_index.is_file()
    service.active_manifest.write_bytes(b"broken")

    with service.index_session() as index:
        loaded = index.load_games({1})

    assert loaded[1].canonical_name == "Alice"
    assert service.active_manifest.read_bytes() == OLD_MANIFEST
    assert service.active_index.read_bytes() == backup_index.read_bytes()
    assert fake_http.calls == []


def test_legacy_two_file_backup_restores_without_stale_index(
    provider: tuple[LudusaviProvider, FakeHttp],
) -> None:
    service, _ = provider
    service.ensure_initial_snapshot()
    backup = service._backup_active_pair()
    assert backup is not None
    backup.manifest.with_suffix(".sqlite").unlink()
    service.active_manifest.write_bytes(b"broken")

    service.ensure_initial_snapshot()

    assert service.active_manifest.read_bytes() == OLD_MANIFEST
    assert not service.active_index.exists()


def test_metadata_recovers_hash_mismatched_active_pair(
    provider: tuple[LudusaviProvider, FakeHttp],
) -> None:
    service, _ = provider
    service.ensure_initial_snapshot()
    backup = service._backup_active_pair()
    assert backup is not None
    service.active_manifest.write_bytes(b"broken")

    metadata = service.metadata()

    assert metadata.sha256 == hashlib.sha256(OLD_MANIFEST).hexdigest()
    assert service.active_manifest.read_bytes() == OLD_MANIFEST


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
    assert len(list(service.previous_dir.glob("*.sqlite"))) == 2


def test_update_reports_stages_and_rechecks_download_hash(
    provider: tuple[LudusaviProvider, FakeHttp],
) -> None:
    service, fake_http = provider
    service.ensure_initial_snapshot()
    fake_http.respond(200, NEW_MANIFEST, headers={"ETag": '"new"'})
    stages: list[str] = []

    result = service.update_explicitly(stages.append)

    assert result.status == "updated"
    assert stages == [
        "connecting",
        "downloading",
        "validating",
        "indexing",
        "replacing",
    ]
    assert result.metadata is not None
    assert _sha256(service.active_manifest) == result.metadata.sha256


def test_update_parses_downloaded_yaml_once(
    provider: tuple[LudusaviProvider, FakeHttp],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, fake_http = provider
    service.ensure_initial_snapshot()
    fake_http.respond(200, NEW_MANIFEST)
    real_parse = provider_module.parse_manifest
    calls = 0

    def counted_parse(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return real_parse(*args, **kwargs)

    monkeypatch.setattr(provider_module, "parse_manifest", counted_parse)

    assert service.update_explicitly().status == "updated"
    assert calls == 1


def test_update_without_existing_snapshot_can_create_first_valid_pair(
    tmp_path: Path,
) -> None:
    service, fake_http = _provider_with_resource(tmp_path, b"broken", OLD_MANIFEST)
    fake_http.respond(200, NEW_MANIFEST, headers={"ETag": '"new"'})

    result = service.update_explicitly()

    assert result.status == "updated"
    assert "If-None-Match" not in fake_http.calls[0][1]
    with service.index_session() as index:
        assert index.load_games({1})[1].canonical_name == "Bob"


def test_metadata_replace_failure_restores_old_pair(
    provider: tuple[LudusaviProvider, FakeHttp],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, fake_http = provider
    service.ensure_initial_snapshot()
    before_manifest = service.active_manifest.read_bytes()
    before_metadata = service.active_metadata.read_bytes()
    before_index = service.active_index.read_bytes()
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
    assert service.active_index.read_bytes() == before_index


def test_index_replace_failure_restores_old_bundle(
    provider: tuple[LudusaviProvider, FakeHttp],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, fake_http = provider
    service.ensure_initial_snapshot()
    before = _bundle_bytes(service)
    fake_http.respond(200, NEW_MANIFEST)
    original_replace = os.replace
    failed = False

    def fail_first_new_index(source: Path, destination: Path) -> None:
        nonlocal failed
        if destination == service.active_index and not failed:
            failed = True
            raise OSError("index disk failure")
        original_replace(source, destination)

    monkeypatch.setattr(provider_module.os, "replace", fail_first_new_index)

    result = service.update_explicitly()

    assert result.status == "failed"
    assert _bundle_bytes(service) == before


def test_backup_failure_preserves_active_pair_and_reports_backup_stage(
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

    def fail_backup(*_args: object, **_kwargs: object) -> None:
        raise OSError("backup disk failure")

    monkeypatch.setattr(provider_module.shutil, "copy2", fail_backup)

    result = service.update_explicitly()

    assert result.status == "failed"
    assert "备份当前清单失败" in result.message
    assert (
        service.active_manifest.read_bytes(),
        service.active_metadata.read_bytes(),
    ) == before


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


def _bundle_bytes(service: LudusaviProvider) -> tuple[bytes, bytes, bytes]:
    return (
        service.active_manifest.read_bytes(),
        service.active_metadata.read_bytes(),
        service.active_index.read_bytes(),
    )
