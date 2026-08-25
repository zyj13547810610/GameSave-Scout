from __future__ import annotations

import sqlite3
from io import StringIO
from pathlib import Path

import pytest

from gamesave_scout.saves.ludusavi_index import InvalidLudusaviIndex, LudusaviIndex
from gamesave_scout.saves.ludusavi_index_builder import build_ludusavi_index
from gamesave_scout.saves.ludusavi_parser import parse_manifest

MANIFEST_SHA256 = "a" * 64
FIXTURE_YAML = """
Alice Story:
  files:
    <base>/save: {tags: [save]}
  installDir:
    AliceGame: {}
Bob:
  alias: Alice Story
"""


def test_index_flattens_aliases_and_round_trips_windows_rules(tmp_path: Path) -> None:
    manifest = parse_manifest(
        StringIO(
            """
"Clair Obscur: Expedition 33":
  files:
    <winLocalAppData>/Sandfall/Saved/SaveGames/<storeUserId>/*.sav:
      tags: [save]
      when: [{os: windows, store: steam}]
  installDir:
    Expedition 33: {}
コイカツ！ / Koikatsu Party:
  alias: "Clair Obscur: Expedition 33"
"""
        )
    )
    path = tmp_path / "manifest-index.sqlite"

    metadata = build_ludusavi_index(
        path,
        manifest,
        manifest_sha256=MANIFEST_SHA256,
    )
    index = LudusaviIndex.open(path, manifest_sha256=MANIFEST_SHA256)

    assert metadata.schema_version == 2
    assert metadata.manifest_sha256 == MANIFEST_SHA256
    assert metadata.game_count == 1
    assert metadata.name_count == 3
    assert [item.display_name for item in index.load_names()] == [
        "Clair Obscur: Expedition 33",
        "Expedition 33",
        "コイカツ！ / Koikatsu Party",
    ]
    games = index.load_games({1})
    assert games[1].canonical_name == "Clair Obscur: Expedition 33"
    assert games[1].install_dirs == ("Expedition 33",)
    assert games[1].files[0].tags == frozenset({"save"})
    assert games[1].files[0].conditions[0].store == "steam"


def test_index_builds_windows_path_reverse_lookup(tmp_path: Path) -> None:
    manifest = parse_manifest(
        StringIO(
            r'''
Summer Pockets:
  files:
    <winAppData>/RenPy/SummerPocket-*/**/*.save: {tags: [save]}
    <winAppData>/*/SummerPocket/config.json: {tags: [config]}
  registry:
    HKEY_CURRENT_USER/Software/Key/SummerPockets: {tags: [save]}
Summer Pockets REFLECTION BLUE:
  alias: Summer Pockets
Shared Alpha:
  files:
    <winDocuments>/Shared/save.dat: {tags: [save]}
Shared Beta:
  files:
    <winDocuments>/Shared/save.dat: {tags: [save]}
Unsupported Context:
  files:
    <base>/save: {tags: [save]}
    <xdgData>/game/save: {tags: [save]}
  registry:
    HKEY_CLASSES_ROOT/Software/Game: {tags: [save]}
'''
        )
    )
    path = tmp_path / "manifest-index.sqlite"

    metadata = build_ludusavi_index(
        path,
        manifest,
        manifest_sha256=MANIFEST_SHA256,
    )
    index = LudusaviIndex.open(path, manifest_sha256=MANIFEST_SHA256)

    assert metadata.path_rule_count == 5
    matches = index.find_path_rules(
        "<winAppData>",
        r"RenPy\SummerPocket-123\save01.save",
        "file",
    )
    assert [item.canonical_name for item in matches] == ["Summer Pockets"]
    assert matches[0].specificity > 0
    assert matches[0].first_segment_key == "renpy"
    assert matches[0].tags == frozenset({"save"})

    shared = index.find_path_rules(
        "<winDocuments>",
        r"Shared\save.dat",
        "file",
    )
    assert [item.canonical_name for item in shared] == [
        "Shared Alpha",
        "Shared Beta",
    ]
    assert [item.canonical_name for item in index.load_literal_path_rules(
        {"<winDocuments>"}
    )] == ["Shared Alpha", "Shared Beta"]

    registry = index.find_path_rules(
        "HKCU",
        r"Software\Key\SummerPockets",
        "registry",
    )
    assert [item.canonical_name for item in registry] == ["Summer Pockets"]
    assert index.find_path_rules(
        "<winAppData>",
        r"Studio\SummerPocket\config.json",
        "file",
    )[0].first_segment_key == ""


def test_index_rejects_wrong_manifest_digest(tmp_path: Path) -> None:
    path = _build_fixture_index(tmp_path, MANIFEST_SHA256)

    with pytest.raises(InvalidLudusaviIndex, match="摘要"):
        LudusaviIndex.open(path, manifest_sha256="b" * 64)


def test_index_rejects_corrupt_sqlite(tmp_path: Path) -> None:
    path = tmp_path / "manifest-index.sqlite"
    path.write_bytes(b"not sqlite")

    with pytest.raises(InvalidLudusaviIndex, match="SQLite"):
        LudusaviIndex.open(path, manifest_sha256=MANIFEST_SHA256)


def test_index_rejects_boolean_game_id(tmp_path: Path) -> None:
    path = _build_fixture_index(tmp_path, MANIFEST_SHA256)
    index = LudusaviIndex.open(path, manifest_sha256=MANIFEST_SHA256)

    with pytest.raises(InvalidLudusaviIndex, match="游戏 ID"):
        index.load_games({True})


def test_index_build_is_deterministic_at_the_logical_row_level(tmp_path: Path) -> None:
    first = _build_fixture_index(tmp_path / "first", MANIFEST_SHA256)
    second = _build_fixture_index(tmp_path / "second", MANIFEST_SHA256)

    assert _dump_rows(first) == _dump_rows(second)


def test_index_builder_releases_file_for_atomic_replace(tmp_path: Path) -> None:
    path = _build_fixture_index(tmp_path, MANIFEST_SHA256)
    replacement = tmp_path / "validated-index.sqlite"

    path.replace(replacement)

    assert replacement.is_file()


def test_index_reader_releases_file_for_atomic_replace(tmp_path: Path) -> None:
    path = _build_fixture_index(tmp_path, MANIFEST_SHA256)
    replacement = tmp_path / "read-index.sqlite"

    LudusaviIndex.open(path, manifest_sha256=MANIFEST_SHA256)
    path.replace(replacement)

    assert replacement.is_file()


def test_index_probe_reads_one_name_and_its_game_locations(tmp_path: Path) -> None:
    path = _build_fixture_index(tmp_path, MANIFEST_SHA256)
    index = LudusaviIndex.open(path, manifest_sha256=MANIFEST_SHA256)

    index.probe()

    replacement = tmp_path / "probed-index.sqlite"
    path.replace(replacement)
    assert replacement.is_file()


def test_index_probe_rejects_name_pointing_to_missing_game(tmp_path: Path) -> None:
    path = _build_fixture_index(tmp_path, MANIFEST_SHA256)
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE names SET game_id = 999")
        connection.commit()
    index = LudusaviIndex.open(path, manifest_sha256=MANIFEST_SHA256)

    with pytest.raises(InvalidLudusaviIndex, match="游戏条目"):
        index.probe()


def _build_fixture_index(directory: Path, manifest_sha256: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "manifest-index.sqlite"
    build_ludusavi_index(
        path,
        parse_manifest(StringIO(FIXTURE_YAML)),
        manifest_sha256=manifest_sha256,
    )
    return path


def _dump_rows(path: Path) -> tuple[tuple[object, ...], ...]:
    queries = (
        ("index_metadata", "SELECT key, value FROM index_metadata ORDER BY key"),
        ("games", "SELECT id, canonical_name FROM games ORDER BY id"),
        (
            "names",
            "SELECT game_id, candidate_order, source, display_name, normalized_name "
            "FROM names ORDER BY game_id, candidate_order",
        ),
        (
            "locations",
            "SELECT game_id, location_order, kind, path, tags_json, conditions_json "
            "FROM locations ORDER BY game_id, location_order",
        ),
        (
            "path_rules",
            "SELECT game_id, location_order, kind, root_token, relative_pattern, "
            "first_segment_key, specificity, tags_json, conditions_json "
            "FROM path_rules ORDER BY game_id, location_order",
        ),
    )
    with sqlite3.connect(path) as connection:
        return tuple(
            (table, *row)
            for table, query in queries
            for row in connection.execute(query)
        )
