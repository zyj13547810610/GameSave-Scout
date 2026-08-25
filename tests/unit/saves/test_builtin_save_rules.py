from __future__ import annotations

import logging
from pathlib import Path

from gameshelf.library.models import Game
from gameshelf.platform.windows.known_folders import KnownFolders
from gameshelf.saves.builtin_rules import SaveRuleProvider
from gameshelf.saves.rule_schema import load_save_rules, parse_save_rule_document
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
    label: 精确游戏存档
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
    label: Godot 用户数据
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


def test_provider_propagates_location_existing_policy(tmp_path: Path) -> None:
    provider = _provider(
        tmp_path,
        """\
version: test
rules:
  - id: existing_policy
    label: 存在性策略
    type: save_engine
    status: formal
    references: [https://example.com/save]
    engine_ids: [godot]
    locations:
      - kind: directory
        path: <winDocuments>\\Predicted
        category: save
        confidence: 0.8
      - kind: directory
        path: <winDocuments>\\Existing
        category: save
        confidence: 0.9
        require_existing: true
""",
    )

    relaxed, strict = provider.suggest_engine(
        _game(engine_id="godot"),
        tmp_path / "Game",
        {},
    )

    assert relaxed.require_existing is False
    assert strict.require_existing is True


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
    label: Godot 用户数据
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
    label: 已禁用 Godot 规则
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


def test_bundled_catalog_contains_publicly_supported_generic_templates() -> None:
    rules = load_save_rules(Path("resources/rules/builtin/saves.yaml"))
    rules_by_id = {rule.metadata.rule_id: rule for rule in rules}

    assert set(rules_by_id) == {
        "godot_user_data",
        "unity_user_data",
        "unreal_save_games",
        "renpy_save_directory",
        "rpg_maker_2k_saves",
        "rpg_maker_xp_saves",
        "rpg_maker_vx_saves",
        "rpg_maker_vx_ace_saves",
        "rpg_maker_mv_saves",
        "rpg_maker_mz_saves",
        "nscripter_saves",
    }
    assert all(rule.metadata.status == "formal" for rule in rules)
    assert all(rule.metadata.references for rule in rules)
    assert {rule.metadata.version for rule in rules} == {"2026.08.25-1"}

    expected_locations = {
        "renpy_save_directory": (
            ("directory", r"<winAppData>\RenPy\{renpy_save_directory}", 0.96, False),
        ),
        "rpg_maker_2k_saves": (
            ("glob", r"<game>\Save*.lsd", 0.96, True),
        ),
        "rpg_maker_xp_saves": (
            ("glob", r"<game>\Save*.rxdata", 0.96, True),
        ),
        "rpg_maker_vx_saves": (
            ("glob", r"<game>\Save*.rvdata", 0.96, True),
        ),
        "rpg_maker_vx_ace_saves": (
            ("glob", r"<game>\Save*.rvdata2", 0.96, True),
        ),
        "rpg_maker_mv_saves": (
            ("glob", r"<game>\save\*.rpgsave", 0.96, True),
            ("glob", r"<game>\www\save\*.rpgsave", 0.96, True),
        ),
        "rpg_maker_mz_saves": (
            ("glob", r"<game>\save\*.rmmzsave", 0.96, True),
            ("glob", r"<game>\www\save\*.rmmzsave", 0.96, True),
        ),
        "nscripter_saves": (
            ("glob", r"<game>\save*.dat", 0.94, True),
            ("file", r"<game>\envdata", 0.92, True),
            ("file", r"<game>\kidoku.dat", 0.92, True),
        ),
    }
    for rule_id, expected in expected_locations.items():
        assert tuple(
            (
                location.kind,
                location.path_template,
                location.confidence,
                location.require_existing,
            )
            for location in rules_by_id[rule_id].locations
        ) == expected


def test_provider_orders_user_and_game_rules_first_and_hashes_full_content(
    tmp_path: Path,
) -> None:
    builtin_game = parse_save_rule_document(
        _document("builtin_game", "内置游戏规则", "save_game", priority=100),
        source="builtin",
        require_single=True,
    )[0]
    user_engine = parse_save_rule_document(
        _document("user_engine", "用户引擎规则", "save_engine", priority=-100),
        source="user",
        require_single=True,
    )[0]
    user_game = parse_save_rule_document(
        _document("user_game", "用户游戏规则", "save_game", priority=-100),
        source="user",
        require_single=True,
    )[0]
    resolver = _resolver(tmp_path)

    provider = SaveRuleProvider(
        (builtin_game, user_engine, user_game),
        resolver,
    )
    changed = SaveRuleProvider(
        (
            builtin_game,
            user_engine,
            parse_save_rule_document(
                _document(
                    "user_game",
                    "用户游戏规则",
                    "save_game",
                    priority=-100,
                    confidence=0.7,
                ),
                source="user",
                require_single=True,
            )[0],
        ),
        resolver,
    )

    assert [rule.metadata.qualified_id for rule in provider.rules] == [
        "user:user_game",
        "user:user_engine",
        "builtin:builtin_game",
    ]
    assert provider.rules_version
    assert provider.rules_version != changed.rules_version


def test_user_rule_keeps_database_source_and_reports_real_evidence_source(
    tmp_path: Path,
) -> None:
    rule = parse_save_rule_document(
        _document("user_game", "用户游戏规则", "save_game", priority=0),
        source="user",
        require_single=True,
    )[0]
    provider = SaveRuleProvider((rule,), _resolver(tmp_path))

    suggestion = provider.suggest_game_specific(
        _game(title="Game"),
        tmp_path / "Game",
        {},
    )[0]

    assert suggestion.source == "engine"
    assert suggestion.source_evidence[0].source == "user"
    assert "user:user_game" in suggestion.source_evidence[0].detail


def _provider(tmp_path: Path, yaml_text: str) -> SaveRuleProvider:
    path = tmp_path / "saves.yaml"
    path.write_text(yaml_text, encoding="utf-8")
    rules = load_save_rules(path)
    return SaveRuleProvider(rules, _resolver(tmp_path))


def _resolver(tmp_path: Path) -> PathTemplateResolver:
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
    return PathTemplateResolver(folders)


def _document(
    rule_id: str,
    label: str,
    rule_type: str,
    *,
    priority: int,
    confidence: float = 0.5,
) -> dict[str, object]:
    selector = (
        {"titles": ["Game"]}
        if rule_type == "save_game"
        else {"engine_ids": ["godot"]}
    )
    return {
        "version": "same-version",
        "rules": [
            {
                "id": rule_id,
                "label": label,
                "type": rule_type,
                "priority": priority,
                "references": ["https://example.com/rule"],
                "locations": [
                    {
                        "kind": "directory",
                        "path": "<winDocuments>\\Game",
                        "category": "save",
                        "confidence": confidence,
                    }
                ],
                **selector,
            }
        ],
    }


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
