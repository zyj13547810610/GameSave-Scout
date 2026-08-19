from __future__ import annotations

import hashlib
import json
from io import StringIO
from pathlib import Path

from gameshelf.saves.ludusavi_index_builder import build_ludusavi_index
from gameshelf.saves.ludusavi_parser import parse_manifest
from scripts.benchmark_ludusavi_index import benchmark_directory


def test_benchmark_reports_cold_and_warm_queries(tmp_path: Path) -> None:
    directory = _write_snapshot_with_index(tmp_path)

    result = benchmark_directory(directory)

    assert result.games == 2
    assert result.names >= 2
    assert result.path_rules == 1
    assert result.cold_seconds >= 0
    assert result.warm_seconds >= 0
    assert result.exact_matches == 1
    assert result.fuzzy_matches == 1


def _write_snapshot_with_index(tmp_path: Path) -> Path:
    directory = tmp_path / "ludusavi"
    directory.mkdir()
    content = b""""Clair Obscur: Expedition 33":
  files:
    <winLocalAppData>/Sandfall/Saved/SaveGames/*.sav: {tags: [save]}
  installDir:
    Expedition 33: {}
Alice Story:
  files:
    <base>/save: {tags: [save]}
"""
    digest = hashlib.sha256(content).hexdigest()
    (directory / "manifest.yaml").write_bytes(content)
    (directory / "manifest-meta.json").write_text(
        json.dumps(
            {
                "etag": None,
                "sha256": digest,
                "downloadedAt": "2026-08-14T00:00:00+00:00",
                "sourceUrl": "https://example.test/manifest.yaml",
                "upstreamCommit": None,
            }
        ),
        encoding="utf-8",
    )
    build_ludusavi_index(
        directory / "manifest-index.sqlite",
        parse_manifest(StringIO(content.decode("utf-8"))),
        manifest_sha256=digest,
    )
    return directory
