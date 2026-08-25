from __future__ import annotations

from dataclasses import replace

import pytest
import yaml

from gamesave_scout.engines.rule_schema import (
    RuleSchemaError,
    parse_engine_rule_document,
)
from gamesave_scout.rules.serialization import (
    serialize_rule_document,
    verification_fingerprint,
)
from gamesave_scout.saves.rule_schema import (
    SaveRuleSchemaError,
    parse_save_rule_document,
)

ENGINE_DRAFT = {
    "id": "sample_engine",
    "label": "示例引擎",
    "type": "engine",
    "priority": 8,
    "enabled": True,
    "notes": "本机只读验证",
    "references": ["https://example.com/engine"],
    "threshold": 0.8,
    "all": [
        {"op": "magic_at", "path": "data.arc", "value": "PACK", "weight": 1.0}
    ],
    "any": [],
    "negative": [],
}

GAME_SAVE_DRAFT = {
    "id": "senren_banka_save",
    "label": "千恋＊万花存档",
    "type": "save_game",
    "priority": 20,
    "enabled": True,
    "notes": "游戏专属规则",
    "references": [],
    "titles": ["千恋＊万花", "Senren Banka"],
    "product_ids": ["vndb:v19073"],
    "locations": [
        {
            "kind": "directory",
            "path": "<winDocuments>\\Yuzusoft\\SenrenBanka",
            "category": "save",
            "confidence": 0.95,
        }
    ],
}

ENGINE_SAVE_DRAFT = {
    "id": "sample_engine_save",
    "label": "示例引擎通用存档",
    "type": "save_engine",
    "priority": 10,
    "enabled": True,
    "references": [],
    "engine_ids": ["sample_engine"],
    "locations": [
        {
            "kind": "directory",
            "path": "<winLocalAppData>\\{product_name}\\Save",
            "category": "save",
            "confidence": 0.8,
        }
    ],
}


@pytest.mark.parametrize("kind", ["engine", "save_game", "save_engine"])
def test_three_rule_types_round_trip_through_stable_yaml(kind: str) -> None:
    if kind == "engine":
        rule = parse_engine_rule_document(
            {"version": "1", "rules": [ENGINE_DRAFT]},
            source="user",
            require_single=True,
        )[0]
        reparsed = parse_engine_rule_document
    else:
        draft = GAME_SAVE_DRAFT if kind == "save_game" else ENGINE_SAVE_DRAFT
        rule = parse_save_rule_document(
            {"version": "1", "rules": [draft]},
            source="user",
            require_single=True,
        )[0]
        reparsed = parse_save_rule_document

    serialized = serialize_rule_document(rule)
    loaded = yaml.safe_load(serialized)

    assert serialized.endswith(b"\n")
    assert b"\r\n" not in serialized
    assert list(loaded) == ["version", "rules"]
    assert "source" not in loaded["rules"][0]
    assert reparsed(
        loaded,
        source="user",
        require_single=True,
    )[0] == rule
    assert rule.metadata.source == "user"
    assert rule.metadata.status == "experimental"


@pytest.mark.parametrize("parser", [parse_engine_rule_document, parse_save_rule_document])
def test_user_rule_file_requires_exactly_one_rule(parser) -> None:
    for entries in ([], [GAME_SAVE_DRAFT, GAME_SAVE_DRAFT]):
        if parser is parse_engine_rule_document:
            entries = [] if not entries else [ENGINE_DRAFT, ENGINE_DRAFT]
        with pytest.raises((RuleSchemaError, SaveRuleSchemaError), match="一条"):
            parser(
                {"version": "1", "rules": entries},
                source="user",
                require_single=True,
            )


def test_yaml_cannot_self_report_rule_source() -> None:
    engine = {**ENGINE_DRAFT, "source": "builtin"}
    save = {**GAME_SAVE_DRAFT, "source": "builtin"}

    with pytest.raises(RuleSchemaError, match="source"):
        parse_engine_rule_document(
            {"version": "1", "rules": [engine]},
            source="user",
            require_single=True,
        )
    with pytest.raises(SaveRuleSchemaError, match="source"):
        parse_save_rule_document(
            {"version": "1", "rules": [save]},
            source="user",
            require_single=True,
        )


@pytest.mark.parametrize(
    "path",
    [
        "C:\\Games\\outside.dat",
        "../outside.dat",
        "\\\\server\\share\\outside.dat",
        "\\\\?\\C:\\outside.dat",
        "**/*.dat",
    ],
)
def test_user_engine_rule_rejects_unbounded_or_escaping_paths(path: str) -> None:
    draft = {
        **ENGINE_DRAFT,
        "all": [{"op": "glob_exists", "path": path, "weight": 1.0}],
    }

    with pytest.raises(RuleSchemaError, match="路径|relative|glob"):
        parse_engine_rule_document(
            {"version": "1", "rules": [draft]},
            source="user",
            require_single=True,
        )


def test_rule_parser_rejects_non_mapping_alias_result_and_executable_fields() -> None:
    with pytest.raises(SaveRuleSchemaError, match="mapping"):
        parse_save_rule_document(
            {"version": "1", "rules": [[GAME_SAVE_DRAFT]]},
            source="user",
            require_single=True,
        )
    for field in ("command", "script", "sql"):
        with pytest.raises(SaveRuleSchemaError, match=field):
            parse_save_rule_document(
                {"version": "1", "rules": [{**GAME_SAVE_DRAFT, field: "unsafe"}]},
                source="user",
                require_single=True,
            )


def test_user_save_rule_rejects_root_recursive_glob() -> None:
    draft = {
        **GAME_SAVE_DRAFT,
        "locations": [
            {
                "kind": "glob",
                "path": "<winDocuments>\\**\\*.sav",
                "category": "save",
                "confidence": 0.5,
            }
        ],
    }

    with pytest.raises(SaveRuleSchemaError, match="无界"):
        parse_save_rule_document(
            {"version": "1", "rules": [draft]},
            source="user",
            require_single=True,
        )


def test_verification_fingerprint_excludes_presentation_and_state_fields() -> None:
    rule = parse_engine_rule_document(
        {"version": "1", "rules": [ENGINE_DRAFT]},
        source="user",
        require_single=True,
    )[0]
    changed_metadata = replace(
        rule.metadata,
        status="formal",
        version="2",
        references=("https://example.com/changed",),
        priority=-5,
        enabled=False,
    )
    presentation_only = replace(
        rule,
        metadata=changed_metadata,
        label="新标签",
        notes="新说明",
    )

    assert verification_fingerprint(presentation_only) == verification_fingerprint(rule)
    assert verification_fingerprint(replace(rule, threshold=0.7)) != (
        verification_fingerprint(rule)
    )


def test_save_fingerprint_changes_with_selectors_or_locations() -> None:
    rule = parse_save_rule_document(
        {"version": "1", "rules": [GAME_SAVE_DRAFT]},
        source="user",
        require_single=True,
    )[0]

    assert verification_fingerprint(replace(rule, titles=("另一个游戏",))) != (
        verification_fingerprint(rule)
    )
    changed_location = replace(rule.locations[0], confidence=0.5)
    assert verification_fingerprint(replace(rule, locations=(changed_location,))) != (
        verification_fingerprint(rule)
    )


def test_save_location_serialization_only_writes_strict_existing_policy() -> None:
    draft = {
        **GAME_SAVE_DRAFT,
        "locations": [
            {**GAME_SAVE_DRAFT["locations"][0], "require_existing": True},
            {
                "kind": "directory",
                "path": "<winDocuments>\\Yuzusoft\\Predicted",
                "category": "save",
                "confidence": 0.75,
            },
        ],
    }
    rule = parse_save_rule_document(
        {"version": "1", "rules": [draft]},
        source="user",
        require_single=True,
    )[0]

    loaded = yaml.safe_load(serialize_rule_document(rule))
    locations = loaded["rules"][0]["locations"]

    assert locations[0]["require_existing"] is True
    assert "require_existing" not in locations[1]
