from __future__ import annotations

import hashlib
import json
import os
import subprocess
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

import scripts.release_tools as release_tools_module
from scripts.release_tools import (
    ReleaseMetadata,
    ReleaseToolError,
    ReleaseVersions,
    WebViewArchiveConfig,
    build_release_manifest,
    create_release_zip,
    extract_webview2_cab,
    normalize_webview_runtime,
    publish_release,
    sha256_file,
    validate_managed_target,
    validate_webview_archive,
    verify_release_tree,
    verify_release_zip,
    verify_zip_sha256,
    write_release_manifest,
    write_zip_sha256,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_repository_versions_are_consistent() -> None:
    versions = ReleaseVersions.load(REPOSITORY_ROOT)

    assert versions.version == "0.1.0"


def test_release_versions_reject_mismatched_project_files(tmp_path: Path) -> None:
    _write_versions(tmp_path, project="1.2.3", package="1.2.4", frontend="1.2.3")

    with pytest.raises(ReleaseToolError, match="版本不一致"):
        ReleaseVersions.load(tmp_path)


def test_webview_archive_config_accepts_only_controlled_schema(tmp_path: Path) -> None:
    config_file = tmp_path / "webview2-runtime.json"
    config_file.write_text(
        json.dumps(_valid_config()),
        encoding="utf-8",
    )

    config = WebViewArchiveConfig.load(config_file)

    assert config.version == "139.0.3405.125"
    assert config.architecture == "x64"
    assert config.archive_file_name == "Microsoft.WebView2.FixedVersionRuntime.x64.cab"

    invalid = _valid_config()
    invalid["downloadUrl"] = "https://example.invalid/runtime.cab"
    config_file.write_text(json.dumps(invalid), encoding="utf-8")
    with pytest.raises(ReleaseToolError, match="未知字段"):
        WebViewArchiveConfig.load(config_file)


def test_webview_archive_config_rejects_wrong_architecture_and_digest(
    tmp_path: Path,
) -> None:
    config_file = tmp_path / "webview2-runtime.json"
    invalid = _valid_config()
    invalid["architecture"] = "arm64"
    config_file.write_text(json.dumps(invalid), encoding="utf-8")

    with pytest.raises(ReleaseToolError, match="x64"):
        WebViewArchiveConfig.load(config_file)

    invalid = _valid_config()
    invalid["sha256"] = "ABC"
    config_file.write_text(json.dumps(invalid), encoding="utf-8")
    with pytest.raises(ReleaseToolError, match="SHA-256"):
        WebViewArchiveConfig.load(config_file)


def test_validate_webview_archive_requires_absolute_matching_regular_file(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "Microsoft.WebView2.FixedVersionRuntime.x64.cab"
    archive.write_bytes(b"controlled cab")
    digest = hashlib.sha256(b"controlled cab").hexdigest()
    config = WebViewArchiveConfig(
        format_version=1,
        version="139.0.3405.125",
        architecture="x64",
        archive_file_name=archive.name,
        sha256=digest,
        source_url="https://developer.microsoft.com/microsoft-edge/webview2/",
    )

    assert validate_webview_archive(archive, config) == archive

    with pytest.raises(ReleaseToolError, match="绝对路径"):
        validate_webview_archive(Path(archive.name), config)
    wrong_name = tmp_path / "renamed.cab"
    wrong_name.write_bytes(archive.read_bytes())
    with pytest.raises(ReleaseToolError, match="文件名"):
        validate_webview_archive(wrong_name, config)
    directory = tmp_path / "directory.cab"
    directory.mkdir()
    with pytest.raises(ReleaseToolError, match="普通文件"):
        validate_webview_archive(
            directory,
            replace(config, archive_file_name=directory.name),
        )
    with pytest.raises(ReleaseToolError, match="SHA-256"):
        validate_webview_archive(archive, replace(config, sha256="0" * 64))


def test_sha256_file_hashes_large_files_in_binary_mode(tmp_path: Path) -> None:
    payload = b"GameShelf\x00" * 200_000
    archive = tmp_path / "large.cab"
    archive.write_bytes(payload)

    assert sha256_file(archive) == hashlib.sha256(payload).hexdigest()


def test_validate_managed_target_accepts_only_current_release_outputs(
    tmp_path: Path,
) -> None:
    versions = ReleaseVersions("0.1.0")
    allowed = (
        tmp_path / "build" / "release",
        tmp_path / "dist" / "GameShelf-0.1.0-win-x64",
        tmp_path / "dist" / "GameShelf-0.1.0-win-x64.zip",
        tmp_path / "dist" / "GameShelf-0.1.0-win-x64.zip.sha256",
    )

    assert tuple(
        validate_managed_target(tmp_path, target, versions) for target in allowed
    ) == allowed

    for rejected in (
        tmp_path,
        tmp_path.parent,
        tmp_path / "build",
        tmp_path / "dist",
        tmp_path / "dist" / "GameShelf-old-win-x64",
    ):
        with pytest.raises(ReleaseToolError, match="受控发布目标"):
            validate_managed_target(tmp_path, rejected, versions)


def test_validate_managed_target_rejects_relative_and_reparse_paths(
    tmp_path: Path,
) -> None:
    versions = ReleaseVersions("0.1.0")
    with pytest.raises(ReleaseToolError, match="绝对路径"):
        validate_managed_target(tmp_path, Path("build/release"), versions)

    outside = tmp_path / "outside"
    outside.mkdir()
    build = tmp_path / "build"
    try:
        build.symlink_to(outside, target_is_directory=True)
    except OSError:
        result = subprocess.run(
            [
                "cmd.exe",
                "/d",
                "/c",
                "mklink",
                "/J",
                str(build),
                str(outside),
            ],
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
            shell=False,
        )
        if result.returncode != 0:
            pytest.skip("当前 Windows 配置不允许创建目录链接或联接")

    with pytest.raises(ReleaseToolError, match="重解析|链接"):
        validate_managed_target(tmp_path, build / "release", versions)


def test_extracts_real_cab_with_runtime_at_archive_root(tmp_path: Path) -> None:
    archive = _create_cab(
        tmp_path / "direct-cab",
        {
            "msedgewebview2.exe": b"browser",
            "LICENSE.txt": b"runtime license",
        },
    )
    release_root = tmp_path / "build" / "release"
    release_root.mkdir(parents=True)
    destination = release_root / "webview2-extracted"

    extract_webview2_cab(
        archive,
        destination,
        _system_tool("expand.exe"),
        release_root=release_root,
    )
    runtime_root = normalize_webview_runtime(destination)

    assert runtime_root == destination
    assert (runtime_root / "msedgewebview2.exe").read_bytes() == b"browser"


def test_extracts_real_cab_with_single_wrapper_and_preserves_notices(
    tmp_path: Path,
) -> None:
    archive = _create_cab(
        tmp_path / "wrapped-cab",
        {
            "FixedRuntime/msedgewebview2.exe": b"browser",
            "FixedRuntime/LICENSE.txt": b"runtime license",
            "FixedRuntime/NOTICE.txt": b"runtime notice",
        },
    )
    release_root = tmp_path / "build" / "release"
    release_root.mkdir(parents=True)
    destination = release_root / "webview2-extracted"

    extract_webview2_cab(
        archive,
        destination,
        _system_tool("expand.exe"),
        release_root=release_root,
    )
    runtime_root = normalize_webview_runtime(destination)

    assert runtime_root == destination / "FixedRuntime"
    assert (runtime_root / "msedgewebview2.exe").read_bytes() == b"browser"
    assert (runtime_root / "LICENSE.txt").read_bytes() == b"runtime license"
    assert (runtime_root / "NOTICE.txt").read_bytes() == b"runtime notice"


def test_normalize_runtime_rejects_missing_and_ambiguous_roots(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing"
    missing.mkdir()
    with pytest.raises(ReleaseToolError, match="msedgewebview2.exe"):
        normalize_webview_runtime(missing)

    ambiguous = tmp_path / "ambiguous"
    for name in ("first", "second"):
        candidate = ambiguous / name
        candidate.mkdir(parents=True)
        (candidate / "msedgewebview2.exe").write_bytes(b"browser")
    with pytest.raises(ReleaseToolError, match="多个|唯一"):
        normalize_webview_runtime(ambiguous)


def test_normalize_runtime_rejects_reparse_points(tmp_path: Path) -> None:
    extracted = tmp_path / "extracted"
    extracted.mkdir()
    (extracted / "msedgewebview2.exe").write_bytes(b"browser")
    outside = tmp_path / "outside"
    outside.mkdir()
    linked = extracted / "linked"
    _create_directory_link(linked, outside)

    with pytest.raises(ReleaseToolError, match="重解析|链接"):
        normalize_webview_runtime(extracted)


def test_extract_rejects_destination_outside_release_root(tmp_path: Path) -> None:
    archive = _create_cab(
        tmp_path / "cab",
        {"msedgewebview2.exe": b"browser"},
    )
    release_root = tmp_path / "build" / "release"
    release_root.mkdir(parents=True)
    outside = tmp_path / "outside"

    with pytest.raises(ReleaseToolError, match="build/release|受控"):
        extract_webview2_cab(
            archive,
            outside,
            _system_tool("expand.exe"),
            release_root=release_root,
        )

    assert not outside.exists()


def test_release_manifest_records_environment_and_every_payload_file(
    tmp_path: Path,
) -> None:
    release_root = _minimal_release_tree(tmp_path)
    metadata = _release_metadata()

    manifest_file = write_release_manifest(release_root, metadata)
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))

    assert manifest["formatVersion"] == 1
    assert manifest["appVersion"] == "0.1.0"
    assert manifest["buildUtc"] == "2026-08-16T00:00:00Z"
    assert manifest["gitCommit"] == "a" * 40
    assert manifest["gitDirty"] is True
    assert manifest["platform"] == "windows-x64"
    assert manifest["pythonVersion"] == "3.12.13"
    assert manifest["nodeVersion"] == "24.19.0"
    assert manifest["npmVersion"] == "11.17.0"
    assert manifest["pyinstallerVersion"] == "6.22.1"
    assert manifest["pywebviewVersion"] == "6.2.1"
    assert manifest["databaseSchemaVersion"] == 1
    assert manifest["engineRulesVersion"] == "2026.08.13-2"
    assert manifest["ludusaviSha256"] == "b" * 64
    assert manifest["ludusaviUpstreamCommit"] == "c" * 40
    assert manifest["webview2Version"] == "139.0.3405.125"
    assert manifest["webview2ArchiveSha256"] == "d" * 64
    assert manifest["fixedRuntime"] is True
    assert manifest["signed"] is False
    paths = [entry["path"] for entry in manifest["files"]]
    assert paths == sorted(paths)
    assert paths == [
        "GameShelf.exe",
        "LICENSE",
        "README.txt",
        "THIRD_PARTY_NOTICES.md",
        "_internal/gameshelf/db/migrations/0001_initial.sql",
        "_internal/resources/manifests/ludusavi/manifest-index.sqlite",
        "_internal/resources/manifests/ludusavi/manifest-meta.json",
        "_internal/resources/manifests/ludusavi/manifest.yaml",
        "_internal/resources/rules/engines.yaml",
        "_internal/resources/ui/index.html",
        "runtime/LICENSE.txt",
        "runtime/msedgewebview2.exe",
    ]
    executable = next(
        entry for entry in manifest["files"] if entry["path"] == "GameShelf.exe"
    )
    assert executable == {
        "path": "GameShelf.exe",
        "size": len(b"frozen exe"),
        "sha256": hashlib.sha256(b"frozen exe").hexdigest(),
    }
    verify_release_tree(release_root, ReleaseVersions("0.1.0"))


def test_build_release_manifest_rejects_data_unexpected_files_and_links(
    tmp_path: Path,
) -> None:
    release_root = _minimal_release_tree(tmp_path)
    (release_root / "data").mkdir()
    with pytest.raises(ReleaseToolError, match="data"):
        build_release_manifest(release_root, _release_metadata())

    (release_root / "data").rmdir()
    (release_root / "unexpected.txt").write_text("unexpected", encoding="utf-8")
    with pytest.raises(ReleaseToolError, match="顶层|意外"):
        build_release_manifest(release_root, _release_metadata())

    (release_root / "unexpected.txt").unlink()
    outside = tmp_path / "outside"
    outside.mkdir()
    _create_directory_link(release_root / "runtime" / "linked", outside)
    with pytest.raises(ReleaseToolError, match="重解析|链接"):
        build_release_manifest(release_root, _release_metadata())


def test_verify_release_tree_detects_payload_changes(tmp_path: Path) -> None:
    release_root = _minimal_release_tree(tmp_path)
    write_release_manifest(release_root, _release_metadata())
    (release_root / "GameShelf.exe").write_bytes(b"tampered")

    with pytest.raises(ReleaseToolError, match="SHA-256|大小"):
        verify_release_tree(release_root, ReleaseVersions("0.1.0"))


def test_release_zip_has_one_root_and_matches_manifest(tmp_path: Path) -> None:
    release_root = _minimal_release_tree(tmp_path)
    versions = ReleaseVersions("0.1.0")
    write_release_manifest(release_root, _release_metadata())
    archive = tmp_path / f"{versions.release_name}.zip"
    checksum = tmp_path / f"{versions.release_name}.zip.sha256"

    create_release_zip(release_root, archive, versions)
    verify_release_zip(archive, versions)
    write_zip_sha256(archive, checksum)
    verify_zip_sha256(archive, checksum)

    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
    assert names == sorted(names)
    assert all(name.startswith(f"{versions.release_name}/") for name in names)
    assert not any("/data/" in f"/{name}/" for name in names)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    assert checksum.read_text(encoding="ascii") == f"{digest}  {archive.name}\n"


def test_verify_release_zip_rejects_extra_root_and_checksum_mismatch(
    tmp_path: Path,
) -> None:
    release_root = _minimal_release_tree(tmp_path)
    versions = ReleaseVersions("0.1.0")
    write_release_manifest(release_root, _release_metadata())
    archive = tmp_path / f"{versions.release_name}.zip"
    checksum = tmp_path / f"{versions.release_name}.zip.sha256"
    create_release_zip(release_root, archive, versions)
    write_zip_sha256(archive, checksum)

    with zipfile.ZipFile(archive, "a") as bundle:
        bundle.writestr("other-root/unexpected.txt", "unexpected")

    with pytest.raises(ReleaseToolError, match="根目录|归档"):
        verify_release_zip(archive, versions)
    with pytest.raises(ReleaseToolError, match="SHA-256"):
        verify_zip_sha256(archive, checksum)


def test_publish_release_replaces_only_current_version_outputs(tmp_path: Path) -> None:
    versions = ReleaseVersions("0.1.0")
    staged_directory, staged_zip, staged_checksum = _staged_release(tmp_path, versions)
    dist = tmp_path / "dist"
    final_directory = dist / versions.release_name
    final_directory.mkdir(parents=True)
    (final_directory / "old.txt").write_text("old directory", encoding="utf-8")
    final_zip = dist / f"{versions.release_name}.zip"
    final_checksum = dist / f"{versions.release_name}.zip.sha256"
    final_zip.write_bytes(b"old zip")
    final_checksum.write_text("old checksum", encoding="ascii")

    published = publish_release(
        tmp_path,
        staged_directory,
        staged_zip,
        staged_checksum,
        versions,
    )

    assert published == (final_directory, final_zip, final_checksum)
    verify_release_tree(final_directory, versions)
    verify_release_zip(final_zip, versions)
    verify_zip_sha256(final_zip, final_checksum)
    assert not staged_directory.exists()
    assert not staged_zip.exists()
    assert not staged_checksum.exists()
    assert not list(dist.glob(".*.backup-*"))


def test_publish_release_rolls_back_all_outputs_when_second_move_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    versions = ReleaseVersions("0.1.0")
    staged_directory, staged_zip, staged_checksum = _staged_release(tmp_path, versions)
    dist = tmp_path / "dist"
    final_directory = dist / versions.release_name
    final_directory.mkdir(parents=True)
    old_marker = final_directory / "old.txt"
    old_marker.write_text("old directory", encoding="utf-8")
    final_zip = dist / f"{versions.release_name}.zip"
    final_checksum = dist / f"{versions.release_name}.zip.sha256"
    final_zip.write_bytes(b"old zip")
    final_checksum.write_text("old checksum", encoding="ascii")
    real_replace = os.replace

    def fail_second_move(source: Path, destination: Path) -> None:
        if Path(source) == staged_zip and Path(destination) == final_zip:
            raise PermissionError("simulated publish failure")
        real_replace(source, destination)

    monkeypatch.setattr(release_tools_module.os, "replace", fail_second_move)

    with pytest.raises(ReleaseToolError, match="simulated publish failure"):
        publish_release(
            tmp_path,
            staged_directory,
            staged_zip,
            staged_checksum,
            versions,
        )

    assert old_marker.read_text(encoding="utf-8") == "old directory"
    assert final_zip.read_bytes() == b"old zip"
    assert final_checksum.read_text(encoding="ascii") == "old checksum"
    assert staged_directory.exists()
    assert staged_zip.exists()
    assert staged_checksum.exists()
    assert not list(dist.glob(".*.backup-*"))


def _write_versions(
    root: Path,
    *,
    project: str,
    package: str,
    frontend: str,
) -> None:
    (root / "src" / "gameshelf").mkdir(parents=True)
    (root / "frontend").mkdir()
    (root / "pyproject.toml").write_text(
        f'[project]\nversion = "{project}"\n',
        encoding="utf-8",
    )
    (root / "src" / "gameshelf" / "__init__.py").write_text(
        f'__version__ = "{package}"\n',
        encoding="utf-8",
    )
    (root / "frontend" / "package.json").write_text(
        json.dumps({"version": frontend}),
        encoding="utf-8",
    )


def _valid_config() -> dict[str, object]:
    return {
        "formatVersion": 1,
        "version": "139.0.3405.125",
        "architecture": "x64",
        "archiveFileName": "Microsoft.WebView2.FixedVersionRuntime.x64.cab",
        "sha256": "0" * 64,
        "sourceUrl": "https://developer.microsoft.com/microsoft-edge/webview2/",
    }


def _system_tool(name: str) -> Path:
    tool = Path(os.environ["SYSTEMROOT"]) / "System32" / name
    assert tool.is_file()
    return tool


def _create_cab(directory: Path, entries: dict[str, bytes]) -> Path:
    directory.mkdir(parents=True)
    source_directory = directory / "source"
    output_directory = directory / "output"
    source_directory.mkdir()
    output_directory.mkdir()
    directives = [
        ".OPTION EXPLICIT",
        ".Set Cabinet=on",
        ".Set Compress=off",
        ".Set MaxDiskSize=0",
        ".Set CabinetNameTemplate=runtime.cab",
        f'.Set DiskDirectoryTemplate="{output_directory}"',
    ]
    for index, (archive_name, payload) in enumerate(entries.items()):
        source = source_directory / f"source-{index}.bin"
        source.write_bytes(payload)
        relative = Path(archive_name)
        destination_directory = str(relative.parent).replace("/", "\\")
        if destination_directory == ".":
            destination_directory = ""
        directives.append(f'.Set DestinationDir="{destination_directory}"')
        directives.append(f'"{source}" "{relative.name}"')
    directive_file = directory / "runtime.ddf"
    directive_file.write_text("\n".join(directives) + "\n", encoding="utf-8")
    result = subprocess.run(
        [str(_system_tool("makecab.exe")), "/F", str(directive_file)],
        cwd=directory,
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
        shell=False,
    )
    if result.returncode != 0:
        pytest.fail(f"makecab failed: {result.stdout}\n{result.stderr}")
    archive = output_directory / "runtime.cab"
    assert archive.is_file()
    return archive


def _create_directory_link(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
        return
    except OSError:
        result = subprocess.run(
            [
                "cmd.exe",
                "/d",
                "/c",
                "mklink",
                "/J",
                str(link),
                str(target),
            ],
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
            shell=False,
        )
        if result.returncode != 0:
            pytest.skip("当前 Windows 配置不允许创建目录链接或联接")


def _minimal_release_tree(tmp_path: Path) -> Path:
    root = tmp_path / "GameShelf-0.1.0-win-x64"
    (root / "_internal" / "resources" / "ui").mkdir(parents=True)
    (root / "_internal" / "resources" / "rules").mkdir()
    (root / "_internal" / "resources" / "manifests" / "ludusavi").mkdir(
        parents=True
    )
    (root / "_internal" / "gameshelf" / "db" / "migrations").mkdir(
        parents=True
    )
    (root / "runtime").mkdir()
    (root / "GameShelf.exe").write_bytes(b"frozen exe")
    (root / "_internal" / "resources" / "ui" / "index.html").write_text(
        "<!doctype html>",
        encoding="utf-8",
    )
    (root / "_internal" / "resources" / "rules" / "engines.yaml").write_text(
        'version: "2026.08.13-2"\nrules: []\n',
        encoding="utf-8",
    )
    ludusavi = root / "_internal" / "resources" / "manifests" / "ludusavi"
    (ludusavi / "manifest.yaml").write_text("{}\n", encoding="utf-8")
    (ludusavi / "manifest-meta.json").write_text("{}\n", encoding="utf-8")
    (ludusavi / "manifest-index.sqlite").write_bytes(b"sqlite")
    (root / "_internal" / "gameshelf" / "db" / "migrations" / "0001_initial.sql").write_text(
        "PRAGMA user_version = 1;\n",
        encoding="utf-8",
    )
    (root / "runtime" / "msedgewebview2.exe").write_bytes(b"webview runtime")
    (root / "runtime" / "LICENSE.txt").write_text(
        "runtime license",
        encoding="utf-8",
    )
    (root / "README.txt").write_text("readme", encoding="utf-8")
    (root / "LICENSE").write_text("MIT", encoding="utf-8")
    (root / "THIRD_PARTY_NOTICES.md").write_text("notices", encoding="utf-8")
    return root


def _release_metadata() -> ReleaseMetadata:
    return ReleaseMetadata(
        app_version="0.1.0",
        build_utc="2026-08-16T00:00:00Z",
        git_commit="a" * 40,
        git_dirty=True,
        python_version="3.12.13",
        node_version="24.19.0",
        npm_version="11.17.0",
        pyinstaller_version="6.22.1",
        pywebview_version="6.2.1",
        database_schema_version=1,
        engine_rules_version="2026.08.13-2",
        ludusavi_sha256="b" * 64,
        ludusavi_upstream_commit="c" * 40,
        webview2_version="139.0.3405.125",
        webview2_archive_sha256="d" * 64,
    )


def _staged_release(
    repository_root: Path,
    versions: ReleaseVersions,
) -> tuple[Path, Path, Path]:
    staging = repository_root / "build" / "release" / "staging"
    release_root = _minimal_release_tree(staging)
    write_release_manifest(release_root, _release_metadata())
    archive = staging / f"{versions.release_name}.zip"
    checksum = staging / f"{versions.release_name}.zip.sha256"
    create_release_zip(release_root, archive, versions)
    write_zip_sha256(archive, checksum)
    return release_root, archive, checksum
