import json
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
    assert resources.builtin_engine_rules_file == (
        resource_root / "rules" / "builtin" / "engines.yaml"
    )
    assert resources.builtin_save_rules_file == (
        resource_root / "rules" / "builtin" / "saves.yaml"
    )
    assert resources.rule_schemas_dir == resource_root / "rules" / "schemas"
    assert resources.ludusavi_dir == resource_root / "rules" / "ludusavi"
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
        "rules/builtin/engines.yaml",
        "rules/builtin/saves.yaml",
        "rules/schemas/engines.schema.json",
        "rules/schemas/saves.schema.json",
        "rules/schemas/README.md",
        "rules/ludusavi/manifest.yaml",
        "rules/ludusavi/manifest-meta.json",
        "rules/ludusavi/manifest-index.sqlite",
        "rules/ludusavi/LICENSE",
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


def test_published_rule_schemas_describe_all_supported_safe_choices() -> None:
    resources = ResourcePaths.for_runtime(frozen=False)
    engine_schema = json.loads(
        resources.rule_schemas_dir.joinpath("engines.schema.json").read_text(
            encoding="utf-8"
        )
    )
    save_schema = json.loads(
        resources.rule_schemas_dir.joinpath("saves.schema.json").read_text(
            encoding="utf-8"
        )
    )

    assert engine_schema["$schema"].endswith("draft/2020-12/schema")
    assert engine_schema["additionalProperties"] is False
    assert set(engine_schema["$defs"]["evidence"]["properties"]["op"]["enum"]) == {
        "path_exists",
        "glob_exists",
        "glob_magic_at",
        "magic_at",
        "magic_from_end",
        "edge_contains",
        "text_contains",
        "pe_field_contains",
    }
    assert save_schema["$schema"].endswith("draft/2020-12/schema")
    assert save_schema["additionalProperties"] is False
    location_schema = save_schema["$defs"]["location"]
    assert set(location_schema["properties"]["kind"]["enum"]) == {
        "directory",
        "file",
        "glob",
        "registry",
    }
    assert set(location_schema["properties"]["category"]["enum"]) == {
        "save",
        "config",
        "other",
    }
    assert set(location_schema["x-gameshelf-filesystem-tokens"]) == {
        "<game>",
        "<home>",
        "<winAppData>",
        "<winLocalAppData>",
        "<winLocalAppDataLow>",
        "<winDocuments>",
        "<winSavedGames>",
        "<winProgramData>",
        "<winPublic>",
        "<winDir>",
    }
    assert set(location_schema["x-gameshelf-metadata-fields"]) == {
        "company_name",
        "product_name",
        "project_name",
    }
    assert location_schema["x-gameshelf-registry-roots"] == [
        "HKEY_CURRENT_USER",
        "HKEY_LOCAL_MACHINE",
    ]


def _create_required_resources(resource_root: Path) -> None:
    (resource_root / "ui").mkdir(parents=True)
    (resource_root / "ui" / "index.html").write_text("<!doctype html>", encoding="utf-8")
    builtin = resource_root / "rules" / "builtin"
    builtin.mkdir(parents=True)
    (builtin / "engines.yaml").write_text("version: test", encoding="utf-8")
    (builtin / "saves.yaml").write_text(
        "version: test\nrules: []\n", encoding="utf-8"
    )
    schemas = resource_root / "rules" / "schemas"
    schemas.mkdir()
    (schemas / "engines.schema.json").write_text("{}", encoding="utf-8")
    (schemas / "saves.schema.json").write_text("{}", encoding="utf-8")
    (schemas / "README.md").write_text("schema", encoding="utf-8")
    ludusavi = resource_root / "rules" / "ludusavi"
    ludusavi.mkdir()
    (ludusavi / "manifest.yaml").write_text("{}", encoding="utf-8")
    (ludusavi / "manifest-meta.json").write_text("{}", encoding="utf-8")
    (ludusavi / "manifest-index.sqlite").write_bytes(b"sqlite")
    (ludusavi / "LICENSE").write_text("license", encoding="utf-8")
