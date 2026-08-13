from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_bundled_ludusavi_manifest_matches_metadata_and_is_lf() -> None:
    directory = REPOSITORY_ROOT / "resources" / "manifests" / "ludusavi"
    manifest = (directory / "manifest.yaml").read_bytes()
    metadata = json.loads(
        (directory / "manifest-meta.json").read_text(encoding="utf-8")
    )

    assert b"\r\n" not in manifest
    assert hashlib.sha256(manifest).hexdigest() == metadata["sha256"]


def test_gitattributes_forces_bundled_manifest_to_lf() -> None:
    attributes = (REPOSITORY_ROOT / ".gitattributes").read_text(encoding="utf-8")

    assert (
        "resources/manifests/ludusavi/manifest.yaml text eol=lf"
        in attributes.splitlines()
    )
