from __future__ import annotations

import pytest

from gamesave_scout.rules.validation import (
    RuleMetadataError,
    build_rule_metadata,
    parse_rule_references,
    validate_rule_id,
)


def test_builtin_metadata_keeps_compatibility_id_and_exposes_qualified_id() -> None:
    metadata = build_rule_metadata(
        rule_id="qlie",
        rule_type="engine",
        source="builtin",
        status="experimental",
        version="2026.08.21-1",
        references=("https://github.com/morkt/GARbro",),
        priority=10,
        enabled=True,
    )

    assert metadata.rule_id == "qlie"
    assert metadata.namespace == "builtin"
    assert metadata.source == "builtin"
    assert metadata.qualified_id == "builtin:qlie"
    assert metadata.verification_label == "实验"
    assert metadata.references == ("https://github.com/morkt/GARbro",)


@pytest.mark.parametrize(
    ("source", "status", "expected"),
    [
        ("builtin", "formal", "正式"),
        ("builtin", "experimental", "实验"),
        ("user", "formal", "已验证"),
        ("user", "experimental", "实验"),
    ],
)
def test_verification_label_maps_source_and_status_for_ui(
    source: str,
    status: str,
    expected: str,
) -> None:
    metadata = build_rule_metadata(
        rule_id="rule",
        rule_type="engine",
        source=source,
        status=status,
        version="1",
        references=(),
        priority=0,
        enabled=True,
    )

    assert metadata.verification_label == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        "Builtin:qlie",
        "builtin:qlie",
        "QLIE",
        "qlie-engine",
        "../qlie",
        "qlie/engine",
        "qlie\\engine",
        "qlie\nengine",
        "q" * 81,
    ],
)
def test_rule_id_rejects_values_that_are_not_safe_compatibility_ids(value: str) -> None:
    with pytest.raises(RuleMetadataError, match="规则 ID"):
        validate_rule_id(value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("rule_type", "archive"),
        ("source", "official"),
        ("status", "stable"),
        ("version", ""),
        ("priority", -1001),
        ("priority", 1001),
        ("priority", True),
        ("enabled", 1),
    ],
)
def test_metadata_rejects_unknown_enums_and_out_of_range_values(
    field: str,
    value: object,
) -> None:
    values: dict[str, object] = {
        "rule_id": "godot",
        "rule_type": "save_engine",
        "source": "builtin",
        "status": "formal",
        "version": "2026.08.21-1",
        "references": (),
        "priority": 0,
        "enabled": True,
    }
    values[field] = value

    with pytest.raises(RuleMetadataError):
        build_rule_metadata(**values)


def test_reference_parser_accepts_only_unique_non_empty_https_urls() -> None:
    assert parse_rule_references(
        [
            "https://example.com/rule",
            "https://example.com/rule",
            "https://example.com/format",
        ]
    ) == (
        "https://example.com/rule",
        "https://example.com/format",
    )

    for invalid in (
        ["http://example.com/rule"],
        ["file:///D:/rule.txt"],
        [""],
        [123],
        "https://example.com/not-a-list",
    ):
        with pytest.raises(RuleMetadataError, match="公开依据"):
            parse_rule_references(invalid)
