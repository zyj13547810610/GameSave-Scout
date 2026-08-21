from __future__ import annotations

import logging
from pathlib import Path

from gameshelf.library.models import Game
from gameshelf.platform.windows.known_folders import KnownFolders
from gameshelf.saves.builtin_rules import BuiltinSaveRuleProvider
from gameshelf.saves.rule_schema import load_save_rules
from gameshelf.saves.templates import PathTemplateResolver


def test_game_specific_rule_uses_version_free_exact_title_and_not_fuzzy(
    tmp_path: Path,
) -> None:
    provider = _provider(
        tmp_path,
        """\
version: test
rules:
  - id: exact_game
    type: save_game
    status: formal
    priority: 0
    enabled: true
    references: [https://example.com/save]
    titles: [千恋＊万花, Senren Banka]
    locations:
      - kind: directory
        path: <winDocuments>\\My Games\\Senren Banka
        category: save
        confidence: 0.95
""",
    )

    exact = provider.suggest_game_specific(
        _game(title="千恋＊万花", version="v1.0"), tmp_path / "Game", {}
    )
    fuzzy = provider.suggest_game_specific(
        _game(title="千恋万花 Complete"), tmp_path / "Game", {}
    )

    assert len(exact) == 1
    assert exact[0].path_template == r"<winDocuments>\My Games\Senren Banka"
    assert exact[0].source == "engine"
    assert exact[0].source_evidence[0].source == "builtin"
    assert "builtin:exact_game" in exact[0].source_evidence[0].detail
    assert "formal" in exact[0].source_evidence[0].detail
    assert "https://example.com/save" in exact[0].source_evidence[0].detail
    assert fuzzy == ()


def test_engine_rule_expands_only_safe_metadata_segments(tmp_path: Path) -> None:
    provider = _provider(
        tmp_path,
        """\
version: test
rules:
  - id: godot_user_data
    type: save_engine
    status: formal
    priority: 0
    enabled: true
    references: [https://docs.godotengine.org/en/stable/tutorials/io/data_paths.html]
    engine_ids: [godot]
    locations:
      - kind: directory
        path: <winAppData>\\Godot\\app_userdata\\{project_name}
        category: save
        confidence: 0.9
""",
    )

    suggestions = provider.suggest_engine(
        _game(engine_id="godot"),
        tmp_path / "Game",
        {"project_name": "Project 作品"},
    )

    assert len(suggestions) == 1
    assert suggestions[0].path_template == (
        r"<winAppData>\Godot\app_userdata\Project 作品"
    )
    assert suggestions[0].display_path.endswith(
        r"AppData\Roaming\Godot\app_userdata\Project 作品"
    )
    assert suggestions[0].category == "save"


def test_missing_or_unsafe_metadata_skips_location_with_diagnostic(
    tmp_path: Path,
    caplog,
) -> None:
    provider = _provider(
        tmp_path,
        """\
version: test
rules:
  - id: godot_user_data
    type: save_engine
    status: experimental
    priority: 0
    enabled: true
    references: []
    engine_ids: [godot]
    locations:
      - kind: directory
        path: <winAppData>\\Godot\\app_userdata\\{project_name}
        category: save
        confidence: 0.6
""",
    )

    with caplog.at_level(logging.WARNING):
        missing = provider.suggest_engine(
            _game(engine_id="godot"), tmp_path / "Game", {}
        )
        unsafe = provider.suggest_engine(
            _game(engine_id="godot"),
            tmp_path / "Game",
            {"project_name": "../escape"},
        )

    assert missing == ()
    assert unsafe == ()
    assert "builtin:godot_user_data" in caplog.text
    assert "project_name" in caplog.text


def test_disabled_and_unrelated_engine_rules_do_not_produce_suggestions(
    tmp_path: Path,
) -> None:
    provider = _provider(
        tmp_path,
        """\
version: test
rules:
  - id: disabled_godot
    type: save_engine
    status: experimental
    priority: 0
    enabled: false
    references: []
    engine_ids: [godot]
    locations: [{kind: directory, path: '<winAppData>\\Godot', category: other, confidence: 0.4}]
""",
    )

    assert provider.suggest_engine(_game(engine_id="godot"), tmp_path, {}) == ()
    assert provider.suggest_engine(_game(engine_id="unity"), tmp_path, {}) == ()


def test_bundled_catalog_contains_only_publicly_supported_generic_templates() -> None:
    rules = load_save_rules(Path("resources/rules/saves.yaml"))

    assert {rule.metadata.rule_id for rule in rules} == {
        "godot_user_data",
        "unity_user_data",
        "unreal_save_games",
    }
    assert all(rule.metadata.status == "formal" for rule in rules)
    assert all(rule.metadata.references for rule in rules)


def _provider(tmp_path: Path, yaml_text: str) -> BuiltinSaveRuleProvider:
    path = tmp_path / "saves.yaml"
    path.write_text(yaml_text, encoding="utf-8")
    rules = load_save_rules(path)
    home = tmp_path / "Profile"
    folders = KnownFolders(
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
    return BuiltinSaveRuleProvider(rules, PathTemplateResolver(folders))


def _game(
    *,
    title: str = "Game",
    version: str | None = None,
    engine_id: str = "godot",
) -> Game:
    return Game(
        id="game-1",
        scan_root_id="root-1",
        relative_dir="Game",
        install_path_key=r"d:\games\game",
        title=title,
        detected_title=title,
        status="installed",
        detected_engine_id=engine_id,
        detected_engine_variant=None,
        engine_id=engine_id,
        engine_variant=None,
        engine_is_manual=False,
        engine_confidence=0.96,
        engine_evidence=(),
        engine_rules_version="test",
        main_exe_relpath="Game.exe",
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
        version=version,
    )
