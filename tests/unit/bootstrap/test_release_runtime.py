from __future__ import annotations

import json
from pathlib import Path

import pytest

from gameshelf.bootstrap.release_runtime import (
    ReleaseRuntimeConfig,
    ReleaseRuntimeError,
    RuntimeMode,
)


def test_source_release_runtime_does_not_read_manifest(tmp_path: Path) -> None:
    config = ReleaseRuntimeConfig.for_runtime(tmp_path, frozen=False)

    assert config == ReleaseRuntimeConfig(RuntimeMode.SOURCE)


def test_fixed_release_runtime_reads_manifest_without_bootstrapper(
    tmp_path: Path,
) -> None:
    _write_manifest(tmp_path, runtime_mode="fixed", fixed_runtime=True)

    config = ReleaseRuntimeConfig.for_runtime(tmp_path, frozen=True)

    assert config.mode is RuntimeMode.FIXED
    assert config.bootstrapper_path is None
    assert config.bootstrapper_sha256 is None


def test_evergreen_release_runtime_reads_controlled_bootstrapper(
    tmp_path: Path,
) -> None:
    _write_manifest(tmp_path, runtime_mode="evergreen", fixed_runtime=False)

    config = ReleaseRuntimeConfig.for_runtime(tmp_path, frozen=True)

    assert config.mode is RuntimeMode.EVERGREEN
    assert config.bootstrapper_path == (
        tmp_path / "prerequisites" / "MicrosoftEdgeWebview2Setup.exe"
    )
    assert config.bootstrapper_sha256 == "a" * 64


def test_frozen_release_runtime_requires_manifest(tmp_path: Path) -> None:
    with pytest.raises(ReleaseRuntimeError, match="发布清单不存在"):
        ReleaseRuntimeConfig.for_runtime(tmp_path, frozen=True)


def test_frozen_release_runtime_rejects_invalid_json(tmp_path: Path) -> None:
    (tmp_path / "release-manifest.json").write_text("not-json", encoding="utf-8")

    with pytest.raises(ReleaseRuntimeError, match="JSON"):
        ReleaseRuntimeConfig.for_runtime(tmp_path, frozen=True)


@pytest.mark.parametrize("format_version", [1, 3, "2", None])
def test_release_runtime_requires_format_version_two(
    tmp_path: Path,
    format_version: object,
) -> None:
    _write_manifest(
        tmp_path,
        runtime_mode="fixed",
        fixed_runtime=True,
        format_version=format_version,
    )

    with pytest.raises(ReleaseRuntimeError, match="formatVersion.*2"):
        ReleaseRuntimeConfig.for_runtime(tmp_path, frozen=True)


def test_release_runtime_rejects_unknown_mode(tmp_path: Path) -> None:
    _write_manifest(tmp_path, runtime_mode="portable", fixed_runtime=True)

    with pytest.raises(ReleaseRuntimeError, match="runtimeMode"):
        ReleaseRuntimeConfig.for_runtime(tmp_path, frozen=True)


@pytest.mark.parametrize(
    ("runtime_mode", "fixed_runtime"),
    [("fixed", False), ("evergreen", True)],
)
def test_release_runtime_rejects_mode_and_fixed_runtime_conflict(
    tmp_path: Path,
    runtime_mode: str,
    fixed_runtime: bool,
) -> None:
    _write_manifest(
        tmp_path,
        runtime_mode=runtime_mode,
        fixed_runtime=fixed_runtime,
    )

    with pytest.raises(ReleaseRuntimeError, match="fixedRuntime.*runtimeMode"):
        ReleaseRuntimeConfig.for_runtime(tmp_path, frozen=True)


def test_evergreen_release_runtime_requires_bootstrapper_digest(
    tmp_path: Path,
) -> None:
    _write_manifest(
        tmp_path,
        runtime_mode="evergreen",
        fixed_runtime=False,
        webview2_bootstrapper_sha256=None,
    )

    with pytest.raises(ReleaseRuntimeError, match="Bootstrapper SHA-256"):
        ReleaseRuntimeConfig.for_runtime(tmp_path, frozen=True)


@pytest.mark.parametrize(
    "digest",
    ["a" * 63, "a" * 65, "A" * 64, "g" * 64, 123],
)
def test_evergreen_release_runtime_rejects_invalid_bootstrapper_digest(
    tmp_path: Path,
    digest: object,
) -> None:
    _write_manifest(
        tmp_path,
        runtime_mode="evergreen",
        fixed_runtime=False,
        webview2_bootstrapper_sha256=digest,
    )

    with pytest.raises(ReleaseRuntimeError, match="Bootstrapper SHA-256"):
        ReleaseRuntimeConfig.for_runtime(tmp_path, frozen=True)


def _write_manifest(
    root: Path,
    *,
    runtime_mode: str,
    fixed_runtime: bool,
    webview2_bootstrapper_sha256: object = "a" * 64,
    format_version: object = 2,
) -> None:
    (root / "release-manifest.json").write_text(
        json.dumps(
            {
                "formatVersion": format_version,
                "runtimeMode": runtime_mode,
                "fixedRuntime": fixed_runtime,
                "webview2BootstrapperSha256": webview2_bootstrapper_sha256,
            }
        ),
        encoding="utf-8",
    )
