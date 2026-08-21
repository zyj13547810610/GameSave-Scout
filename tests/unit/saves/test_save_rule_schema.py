from __future__ import annotations

from pathlib import Path

import pytest

from gameshelf.saves.rule_schema import SaveRuleSchemaError, load_save_rules


def test_loads_strict_game_and_engine_save_rules(tmp_path: Path) -> None:
    rules = _load(
        tmp_path,
        """\
version: 2026.08.21-1
rules:
  - id: exact_game
    type: save_game
    status: formal
    priority: 10
    enabled: true
    references: [https://example.com/game-save]
    titles: [Exact Game, 精确游戏]
    product_ids: [steam:12345]
    locations:
      - kind: directory
        path: <winDocuments>\\My Games\\Exact Game
        category: save
        confidence: 0.95
  - id: godot_user_data
    type: save_engine
    status: formal
    priority: 0
    enabled: true
    references: [https://example.com/godot]
    engine_ids: [godot]
    locations:
      - kind: directory
        path: <winAppData>\\Godot\\app_userdata\\{project_name}
        category: save
        confidence: 0.9
""",
    )

    assert [rule.metadata.qualified_id for rule in rules] == [
        "builtin:exact_game",
        "builtin:godot_user_data",
    ]
    assert rules[0].titles == ("Exact Game", "精确游戏")
    assert rules[0].product_ids == ("steam:12345",)
    assert rules[1].engine_ids == ("godot",)
    assert rules[1].locations[0].metadata_fields == ("project_name",)


@pytest.mark.parametrize(
    ("target", "replacement", "message"),
    [
        ("<winAppData>\\Safe", "<winAppData>\\D:\\escape", "相对"),
        ("<winAppData>\\Safe", "<winAppData>\\..\\escape", "离开"),
        ("<winAppData>\\Safe", "<unknown>\\Save", "令牌"),
        ("<winAppData>\\Safe", "<winAppData>\\{game_title}", "占位符"),
        (
            "<winAppData>\\Safe",
            "<winAppData>\\prefix-{project_name}",
            "完整路径段",
        ),
        ("engine_ids: [godot]", "engine_ids: []", "engine_ids"),
        (
            "engine_ids: [godot]",
            "engine_ids: [godot]\n    command: calc.exe",
            "unknown key",
        ),
        (
            "engine_ids: [godot]",
            "engine_ids: [godot]\n    sql: SELECT 1",
            "unknown key",
        ),
    ],
)
def test_rejects_unsafe_engine_rule_shapes(
    tmp_path: Path,
    target: str,
    replacement: str,
    message: str,
) -> None:
    content = """\
version: test
rules:
  - id: unsafe
    type: save_engine
    status: experimental
    priority: 0
    enabled: true
    references: []
    engine_ids: [godot]
    locations:
      - kind: directory
        path: <winAppData>\\Safe
        category: save
        confidence: 0.5
""".replace(target, replacement)

    with pytest.raises(SaveRuleSchemaError, match=message):
        _load(tmp_path, content)


@pytest.mark.parametrize(
    ("selector", "message"),
    [
        ("titles: []", "titles"),
        ("titles: ['']", "非空"),
        ("titles: [Game]\n    product_ids: [unknown:1]", "产品编号"),
        ("titles: [Game]\n    engine_ids: [godot]", "unknown key"),
    ],
)
def test_rejects_invalid_game_selectors(
    tmp_path: Path,
    selector: str,
    message: str,
) -> None:
    content = f"""\
version: test
rules:
  - id: game_rule
    type: save_game
    status: experimental
    priority: 0
    enabled: true
    references: []
    {selector}
    locations:
      - kind: directory
        path: <winDocuments>\\Game
        category: save
        confidence: 0.5
"""

    with pytest.raises(SaveRuleSchemaError, match=message):
        _load(tmp_path, content)


def test_rejects_invalid_registry_root_and_duplicate_qualified_id(tmp_path: Path) -> None:
    invalid_registry = """\
version: test
rules:
  - id: registry_rule
    type: save_engine
    status: experimental
    priority: 0
    enabled: true
    references: []
    engine_ids: [unity]
    locations:
      - kind: registry
        path: HKEY_CLASSES_ROOT\\Software\\Game
        category: config
        confidence: 0.5
"""
    duplicate = """\
version: test
rules:
  - &rule
    id: duplicate
    type: save_engine
    status: experimental
    priority: 0
    enabled: true
    references: []
    engine_ids: [godot]
    locations: [{kind: directory, path: '<winAppData>\\Game', category: save, confidence: 0.5}]
  - *rule
"""

    with pytest.raises(SaveRuleSchemaError, match="注册表根"):
        _load(tmp_path, invalid_registry)
    with pytest.raises(SaveRuleSchemaError, match="duplicate"):
        _load(tmp_path, duplicate)


def test_enforces_bounded_catalog_and_selector_sizes(tmp_path: Path) -> None:
    too_many_rules = "\n".join(
        f"""\
  - id: rule_{index}
    type: save_engine
    status: experimental
    priority: 0
    enabled: true
    references: []
    engine_ids: [godot]
    locations: [{{kind: directory, path: '<winAppData>\\Game', category: save, confidence: 0.5}}]"""
        for index in range(257)
    )
    too_many_titles = ", ".join(f"Game {index}" for index in range(65))

    with pytest.raises(SaveRuleSchemaError, match="最多 256"):
        _load(tmp_path, f"version: test\nrules:\n{too_many_rules}\n")
    with pytest.raises(SaveRuleSchemaError, match="最多 64"):
        _load(
            tmp_path,
            f"""\
version: test
rules:
  - id: too_many_titles
    type: save_game
    status: experimental
    priority: 0
    enabled: true
    references: []
    titles: [{too_many_titles}]
    locations: [{{kind: directory, path: '<winAppData>\\Game', category: save, confidence: 0.5}}]
""",
        )


def _load(tmp_path: Path, content: str):
    path = tmp_path / "saves.yaml"
    path.write_text(content, encoding="utf-8")
    return load_save_rules(path)
