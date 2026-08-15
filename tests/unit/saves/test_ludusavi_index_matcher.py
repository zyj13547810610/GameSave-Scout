from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import replace
from io import StringIO
from pathlib import Path

import pytest

import gameshelf.saves.ludusavi_index_matcher as index_matcher_module
from gameshelf.library.models import Game
from gameshelf.platform.windows.known_folders import KnownFolders
from gameshelf.saves.ludusavi_index import LudusaviIndex
from gameshelf.saves.ludusavi_index_builder import build_ludusavi_index
from gameshelf.saves.ludusavi_index_matcher import IndexedLudusaviMatcher
from gameshelf.saves.ludusavi_models import ManifestGame
from gameshelf.saves.ludusavi_parser import parse_manifest
from gameshelf.saves.templates import PathTemplateResolver

BASE_GAME = Game(
    id="game-1",
    scan_root_id="root-1",
    relative_dir="Other",
    install_path_key=r"d:\games\other",
    title="Unknown",
    detected_title=None,
    status="installed",
    detected_engine_id=None,
    detected_engine_variant=None,
    engine_id=None,
    engine_variant=None,
    engine_is_manual=False,
    engine_confidence=None,
    engine_evidence=(),
    engine_rules_version=None,
    main_exe_relpath="Unrelated.exe",
    main_exe_is_manual=False,
    working_dir_relpath=None,
    launch_args=(),
    environment={},
    exe_arch="unknown",
    cover_original_relpath=None,
    cover_thumb_relpath=None,
    cover_revision=0,
    last_launched_at=None,
    missing_since=None,
)


@pytest.fixture
def indexed_matcher(tmp_path: Path) -> IndexedLudusaviMatcher:
    manifest = parse_manifest(
        StringIO(
            """
Alice Story:
  files:
    <base>/save: {tags: [save]}
  installDir:
    AliceGame: {}
    Shared: {}
Alice Story Remastered:
  files:
    <base>/other-save: {tags: [save]}
  installDir:
    Shared: {}
ボブ:
  alias: Alice Story
"""
        )
    )
    path = tmp_path / "manifest-index.sqlite"
    build_ludusavi_index(path, manifest, manifest_sha256="c" * 64)
    return IndexedLudusaviMatcher(
        LudusaviIndex.open(path, manifest_sha256="c" * 64),
        _resolver(tmp_path),
    )


def test_exact_match_does_not_run_fuzzy_search(
    indexed_matcher: IndexedLudusaviMatcher,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_fuzzy(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("精确命中后不得执行模糊匹配")

    monkeypatch.setattr(index_matcher_module.process, "extract", fail_fuzzy)

    matches = indexed_matcher.find(
        _game(title="Alice Story"),
        Path(r"D:\Games\Other"),
    )

    assert [item.canonical_name for item in matches] == ["Alice Story"]
    assert matches[0].confirmed is True
    assert matches[0].confidence == 1.0


def test_fuzzy_search_runs_only_when_all_exact_signals_miss(
    indexed_matcher: IndexedLudusaviMatcher,
) -> None:
    matches = indexed_matcher.find(
        _game(title="Alice Stor"),
        Path(r"D:\Games\Other"),
    )

    assert [item.canonical_name for item in matches] == ["Alice Story"]
    assert matches[0].confirmed is False
    assert 0.86 <= matches[0].confidence < 1.0
    assert matches[0].evidence == ("名称相似：Alice Stor ↔ Alice Story",)


@pytest.mark.parametrize(
    ("title", "install_dir", "expected_evidence"),
    [
        ("Unknown", Path(r"D:\Games\AliceGame"), "安装目录精确匹配：AliceGame"),
        ("ボブ", Path(r"D:\Games\Other"), "显示标题精确匹配：ボブ"),
    ],
)
def test_exact_install_directory_and_alias_keep_original_evidence(
    indexed_matcher: IndexedLudusaviMatcher,
    title: str,
    install_dir: Path,
    expected_evidence: str,
) -> None:
    matches = indexed_matcher.find(_game(title=title), install_dir)

    assert [item.canonical_name for item in matches] == ["Alice Story"]
    assert matches[0].evidence == (expected_evidence,)


def test_shared_exact_name_keeps_all_canonical_games(
    indexed_matcher: IndexedLudusaviMatcher,
) -> None:
    matches = indexed_matcher.find(
        _game(title="Unknown"),
        Path(r"D:\Games\Shared"),
    )

    assert {item.canonical_name for item in matches} == {
        "Alice Story",
        "Alice Story Remastered",
    }
    assert all(item.confirmed for item in matches)


def test_indexed_matcher_loads_only_matched_game_rules(
    indexed_matcher: IndexedLudusaviMatcher,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested: list[set[int]] = []
    real_load_games = LudusaviIndex.load_games

    def recording_load_games(
        self: LudusaviIndex,
        game_ids: Collection[int],
    ) -> Mapping[int, ManifestGame]:
        requested.append(set(game_ids))
        return real_load_games(self, game_ids)

    monkeypatch.setattr(LudusaviIndex, "load_games", recording_load_games)

    matches = indexed_matcher.find(
        _game(title="Alice Story"),
        Path(r"D:\Games\Alice"),
    )

    assert matches[0].locations[0].display_path.endswith(r"Alice\save")
    assert requested == [{1}]


def test_indexed_matcher_returns_empty_without_loading_rules(
    indexed_matcher: IndexedLudusaviMatcher,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_load(
        _self: LudusaviIndex,
        _game_ids: Collection[int],
    ) -> Mapping[int, ManifestGame]:
        raise AssertionError("无名称命中时不得加载游戏规则")

    monkeypatch.setattr(LudusaviIndex, "load_games", fail_load)

    assert indexed_matcher.find(
        _game(title="Completely Different"),
        Path(r"D:\Games\Other"),
    ) == ()


def _game(*, title: str, main_exe_relpath: str = "Unrelated.exe") -> Game:
    return replace(BASE_GAME, title=title, main_exe_relpath=main_exe_relpath)


def _resolver(tmp_path: Path) -> PathTemplateResolver:
    home = tmp_path / "Profile"
    return PathTemplateResolver(
        KnownFolders(
            home=home,
            app_data=home / "AppData" / "Roaming",
            local_app_data=home / "AppData" / "Local",
            local_app_data_low=home / "AppData" / "LocalLow",
            documents=home / "Documents",
            saved_games=home / "Saved Games",
            program_data=tmp_path / "ProgramData",
            public=tmp_path / "Public",
            windows=tmp_path / "Windows",
        )
    )
