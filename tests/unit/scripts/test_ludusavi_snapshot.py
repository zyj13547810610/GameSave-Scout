from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from gamesave_scout.saves.ludusavi_index import LudusaviIndex
from scripts.update_ludusavi_snapshot import rebuild_index_from_snapshot

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_bundled_ludusavi_manifest_matches_metadata_and_is_lf() -> None:
    directory = REPOSITORY_ROOT / "resources" / "rules" / "ludusavi"
    manifest = (directory / "manifest.yaml").read_bytes()
    metadata = json.loads(
        (directory / "manifest-meta.json").read_text(encoding="utf-8")
    )

    assert b"\r\n" not in manifest
    assert hashlib.sha256(manifest).hexdigest() == metadata["sha256"]


def test_gitattributes_forces_bundled_manifest_to_lf() -> None:
    attributes = (REPOSITORY_ROOT / ".gitattributes").read_text(encoding="utf-8")

    assert (
        "resources/rules/ludusavi/manifest.yaml text eol=lf"
        in attributes.splitlines()
    )


def test_bundled_ludusavi_index_matches_manifest_metadata() -> None:
    directory = REPOSITORY_ROOT / "resources" / "rules" / "ludusavi"
    metadata = json.loads(
        (directory / "manifest-meta.json").read_text(encoding="utf-8")
    )

    index = LudusaviIndex.open(
        directory / "manifest-index.sqlite",
        manifest_sha256=metadata["sha256"],
    )

    assert index.metadata.schema_version == 2
    assert index.metadata.game_count > 50_000
    assert index.metadata.name_count > index.metadata.game_count
    assert index.metadata.path_rule_count > 0
    expedition_matches = index.find_path_rules(
        "<winLocalAppData>",
        r"Sandfall\Saved\SaveGames\7656119\slot.sav",
        "file",
    )
    assert expedition_matches[0].canonical_name == "Clair Obscur: Expedition 33"


def test_gitattributes_marks_bundled_index_as_binary() -> None:
    attributes = (REPOSITORY_ROOT / ".gitattributes").read_text(encoding="utf-8")

    assert (
        "resources/rules/ludusavi/manifest-index.sqlite binary"
        in attributes.splitlines()
    )


def test_rebuild_index_from_snapshot_changes_only_index(tmp_path: Path) -> None:
    directory = tmp_path / "ludusavi"
    directory.mkdir()
    manifest = b"Alice:\n  files:\n    <base>/save: {tags: [save]}\n"
    digest = hashlib.sha256(manifest).hexdigest()
    metadata = json.dumps({"sha256": digest}).encode()
    license_bytes = b"license"
    (directory / "manifest.yaml").write_bytes(manifest)
    (directory / "manifest-meta.json").write_bytes(metadata)
    (directory / "LICENSE").write_bytes(license_bytes)

    result = rebuild_index_from_snapshot(directory)

    assert result == directory / "manifest-index.sqlite"
    assert (directory / "manifest.yaml").read_bytes() == manifest
    assert (directory / "manifest-meta.json").read_bytes() == metadata
    assert (directory / "LICENSE").read_bytes() == license_bytes
    index = LudusaviIndex.open(result, manifest_sha256=digest)
    assert index.load_games({1})[1].canonical_name == "Alice"
    assert index.metadata.path_rule_count == 0


def test_rebuild_index_rejects_manifest_digest_mismatch(tmp_path: Path) -> None:
    directory = tmp_path / "ludusavi"
    directory.mkdir()
    (directory / "manifest.yaml").write_bytes(b"Alice: {}\n")
    (directory / "manifest-meta.json").write_text(
        json.dumps({"sha256": "0" * 64}),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="SHA-256"):
        rebuild_index_from_snapshot(directory)

    assert not (directory / "manifest-index.sqlite").exists()
