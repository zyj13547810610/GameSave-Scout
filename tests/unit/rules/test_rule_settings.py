import json
from pathlib import Path

import pytest

from gamesave_scout.rules.settings import RuleSettings, RuleSettingsStore

KNOWN_IDS = frozenset({"builtin:unity", "builtin:unreal_save_games"})


def test_missing_settings_returns_defaults_without_creating_file(tmp_path: Path) -> None:
    path = tmp_path / "rules" / "settings.json"
    result = RuleSettingsStore(path).load(KNOWN_IDS)

    assert result.settings == RuleSettings()
    assert result.diagnostics == ()
    assert not path.exists()


def test_settings_save_uses_exact_versioned_json_shape(tmp_path: Path) -> None:
    path = tmp_path / "rules" / "settings.json"
    store = RuleSettingsStore(path)
    settings = RuleSettings(
        disabled_builtin_rule_ids=frozenset(
            {"builtin:unreal_save_games", "builtin:unity"}
        )
    )

    store.save(settings)

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "version": 1,
        "disabledBuiltinRuleIds": [
            "builtin:unity",
            "builtin:unreal_save_games",
        ],
    }
    assert path.read_bytes().endswith(b"\n")


@pytest.mark.parametrize(
    "raw",
    (
        {"version": 1, "disabledBuiltinRuleIds": [], "unknown": True},
        {"version": 1, "disabledBuiltinRuleIds": ["builtin:unity", "builtin:unity"]},
        {"version": 1, "disabledBuiltinRuleIds": ["user:mine"]},
        {"version": 1, "disabledBuiltinRuleIds": ["builtin:missing"]},
        {"version": "1", "disabledBuiltinRuleIds": []},
        {"version": 1, "disabledBuiltinRuleIds": "builtin:unity"},
    ),
)
def test_invalid_settings_report_diagnostic_and_fall_back_without_rewrite(
    tmp_path: Path,
    raw: object,
) -> None:
    path = tmp_path / "rules" / "settings.json"
    path.parent.mkdir(parents=True)
    original = json.dumps(raw, ensure_ascii=False).encode("utf-8")
    path.write_bytes(original)

    result = RuleSettingsStore(path).load(KNOWN_IDS)

    assert result.settings == RuleSettings()
    assert len(result.diagnostics) == 1
    assert result.diagnostics[0].severity == "warning"
    assert result.diagnostics[0].code == "invalid_rule_settings"
    assert result.diagnostics[0].source_name == "settings.json"
    assert path.read_bytes() == original


def test_broken_json_does_not_block_other_rule_directory_reads(tmp_path: Path) -> None:
    path = tmp_path / "rules" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text("{", encoding="utf-8")

    result = RuleSettingsStore(path).load(KNOWN_IDS)

    assert result.settings.disabled_builtin_rule_ids == frozenset()
    assert result.diagnostics[0].code == "invalid_rule_settings"
