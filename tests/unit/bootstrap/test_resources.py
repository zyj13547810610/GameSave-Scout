import sys
from pathlib import Path

import pytest

from gameshelf.bootstrap.resources import ResourcePaths


def test_source_runtime_resolves_repository_resources_without_using_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    resources = ResourcePaths.for_runtime(frozen=False)

    assert resources.root == Path(__file__).resolve().parents[3] / "resources"
    assert resources.status().ok is True


def test_frozen_runtime_resolves_resources_from_meipass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_root = tmp_path / "_internal"
    resource_root = bundle_root / "resources"
    _create_required_resources(resource_root)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle_root), raising=False)

    resources = ResourcePaths.for_runtime(frozen=True)

    assert resources.root == resource_root.resolve(strict=False)
    assert resources.ui_dir == resource_root / "ui"
    assert resources.engine_rules_file == resource_root / "rules" / "engines.yaml"
    assert resources.save_rules_file == resource_root / "rules" / "saves.yaml"
    assert resources.ludusavi_dir == resource_root / "manifests" / "ludusavi"
    assert resources.status().ok is True


def test_status_reports_each_missing_required_resource(tmp_path: Path) -> None:
    bundle_root = tmp_path / "_internal"

    status = ResourcePaths.for_runtime(
        frozen=True,
        bundle_root=bundle_root,
    ).status()

    assert status.ok is False
    assert status.missing == (
        "ui/index.html",
        "rules/engines.yaml",
        "rules/saves.yaml",
        "manifests/ludusavi",
    )


def test_explicit_source_and_bundle_roots_do_not_leak_between_calls(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    bundle_root = tmp_path / "bundle"
    _create_required_resources(source_root / "resources")
    _create_required_resources(bundle_root / "resources")

    source_resources = ResourcePaths.for_runtime(
        frozen=False,
        source_root=source_root,
    )
    bundle_resources = ResourcePaths.for_runtime(
        frozen=True,
        bundle_root=bundle_root,
    )
    source_resources_again = ResourcePaths.for_runtime(
        frozen=False,
        source_root=source_root,
    )

    assert source_resources.root == source_root.resolve(strict=False) / "resources"
    assert bundle_resources.root == bundle_root.resolve(strict=False) / "resources"
    assert source_resources_again == source_resources
    assert source_resources.status().ok is True
    assert bundle_resources.status().ok is True


def _create_required_resources(resource_root: Path) -> None:
    (resource_root / "ui").mkdir(parents=True)
    (resource_root / "ui" / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (resource_root / "rules").mkdir()
    (resource_root / "rules" / "engines.yaml").write_text("version: test", encoding="utf-8")
    (resource_root / "rules" / "saves.yaml").write_text(
        "version: test\nrules: []\n", encoding="utf-8"
    )
    (resource_root / "manifests" / "ludusavi").mkdir(parents=True)
