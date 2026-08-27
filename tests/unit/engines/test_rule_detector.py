from pathlib import Path

import pytest
import yaml

from gamesave_scout.engines.base import DetectionContext
from gamesave_scout.engines.rule_detector import RuleDetector
from gamesave_scout.engines.rule_schema import (
    RuleSchemaError,
    load_engine_rules,
    parse_engine_rule_document,
)
from gamesave_scout.rules.serialization import serialize_rule_document


def test_rule_requires_all_and_scores_any_evidence(tmp_path: Path) -> None:
    game = tmp_path / "game"
    (game / "data" / "system").mkdir(parents=True)
    (game / "data" / "system" / "Config.tjs").write_text(
        ";projectID = sample\n;System.title = Sample", encoding="utf-8"
    )
    (game / "tyrano").mkdir()
    (game / "tyrano" / "tyrano.js").write_text("TYRANO", encoding="utf-8")
    rule = load_engine_rules(_write_rules(tmp_path, valid_rule()))[0]

    match = RuleDetector(rule).inspect(DetectionContext(game, None))

    assert match is not None
    assert match.engine_id == "tyrano"
    assert match.confidence >= 0.9
    assert match.evidence[0].detail == "发现路径：data/system/Config.tjs"


def test_missing_required_evidence_never_matches(tmp_path: Path) -> None:
    game = tmp_path / "game"
    game.mkdir()
    rule = load_engine_rules(_write_rules(tmp_path, valid_rule()))[0]

    assert RuleDetector(rule).inspect(DetectionContext(game, None)) is None


def test_any_evidence_variants_share_one_confidence_slot(tmp_path: Path) -> None:
    game = tmp_path / "game"
    game.mkdir()
    (game / "data.arc").write_bytes(b"SECOND")
    rule = load_engine_rules(
        _write_rules(
            tmp_path,
            """- id: alternatives
  label: Alternative headers
  status: experimental
  references:
    - https://example.com/alternatives
  threshold: 0.80
  any:
    - op: magic_at
      path: data.arc
      value: FIRST
      weight: 1.0
    - op: magic_at
      path: data.arc
      value: SECOND
      weight: 1.0
""",
        )
    )[0]

    match = RuleDetector(rule).inspect(DetectionContext(game, None))

    assert match is not None
    assert match.confidence == 1.0


def test_rule_exposes_shared_metadata_without_changing_engine_id(tmp_path: Path) -> None:
    rule = load_engine_rules(_write_rules(tmp_path, valid_rule()))[0]

    assert rule.engine_id == "tyrano"
    assert rule.metadata.qualified_id == "builtin:tyrano"
    assert rule.experimental is False
    assert rule.version == "test-1"
    assert rule.metadata.priority == 20
    assert rule.metadata.enabled is True
    assert rule.metadata.references == ("https://tyranoscript.com/",)


def test_pure_parser_uses_caller_source_and_preserves_notes() -> None:
    rule = parse_engine_rule_document(
        {
            "version": "1",
            "rules": [
                {
                    "id": "user_engine",
                    "label": "用户引擎",
                    "type": "engine",
                    "notes": "合成夹具验证",
                    "all": [
                        {"op": "path_exists", "path": "game.dat", "weight": 1}
                    ],
                }
            ],
        },
        source="user",
        require_single=True,
    )[0]

    assert rule.metadata.qualified_id == "user:user_engine"
    assert rule.metadata.status == "experimental"
    assert rule.notes == "合成夹具验证"
    assert rule.category is None


def test_user_engine_category_is_preserved_by_parser_and_serializer() -> None:
    rule = parse_engine_rule_document(
        {
            "version": "1",
            "rules": [
                {
                    "id": "user_engine",
                    "label": "用户引擎",
                    "type": "engine",
                    "category": "visual_novel_doujin",
                    "all": [
                        {"op": "path_exists", "path": "game.dat", "weight": 1}
                    ],
                }
            ],
        },
        source="user",
        require_single=True,
    )[0]

    serialized = yaml.safe_load(serialize_rule_document(rule))

    assert rule.category == "visual_novel_doujin"
    assert serialized["rules"][0]["category"] == "visual_novel_doujin"


@pytest.mark.parametrize("category", ["anime", [], {}])
def test_unknown_engine_category_is_rejected(category: object) -> None:
    with pytest.raises(RuleSchemaError, match="category"):
        parse_engine_rule_document(
            {
                "version": "1",
                "rules": [
                    {
                        "id": "user_engine",
                        "label": "用户引擎",
                        "type": "engine",
                        "category": category,
                        "all": [
                            {"op": "path_exists", "path": "game.dat", "weight": 1}
                        ],
                    }
                ],
            },
            source="user",
            require_single=True,
        )


def test_unknown_rule_key_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "rules.yaml"
    path.write_text(
        "version: '1'\nrules:\n- id: x\n  surprise: true\n", encoding="utf-8"
    )
    with pytest.raises(RuleSchemaError, match="surprise"):
        load_engine_rules(path)


def test_legacy_experimental_key_is_rejected_after_metadata_upgrade(
    tmp_path: Path,
) -> None:
    content = valid_rule().replace("status: formal", "experimental: false")

    with pytest.raises(RuleSchemaError, match="experimental"):
        load_engine_rules(_write_rules(tmp_path, content))


def test_duplicate_builtin_rule_ids_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(RuleSchemaError, match="builtin:tyrano"):
        load_engine_rules(_write_rules(tmp_path, f"{valid_rule()}{valid_rule()}"))


def test_rule_paths_cannot_escape_game_root(tmp_path: Path) -> None:
    content = valid_rule().replace("data/system/Config.tjs", "../outside")
    with pytest.raises(RuleSchemaError, match="relative"):
        load_engine_rules(_write_rules(tmp_path, content))


def test_magic_from_end_matches_only_the_exact_bounded_position(tmp_path: Path) -> None:
    game = tmp_path / "game"
    game.mkdir()
    archive = game / "data.pack"
    archive.write_bytes(b"payloadFilePackVer3.0" + b"\0" * 14)
    rule = load_engine_rules(_write_rules(tmp_path, suffix_rule()))[0]

    match = RuleDetector(rule).inspect(DetectionContext(game, None))

    assert match is not None
    archive.write_bytes(b"payloadFilePackVer3.0" + b"\0" * 13)
    assert RuleDetector(rule).inspect(DetectionContext(game, None)) is None


def test_magic_from_end_rejects_an_unbounded_offset(tmp_path: Path) -> None:
    with pytest.raises(RuleSchemaError, match="offset"):
        load_engine_rules(_write_rules(tmp_path, suffix_rule(offset=65_537)))


def _write_rules(tmp_path: Path, rule: str) -> Path:
    path = tmp_path / "rules.yaml"
    path.write_text(f"version: 'test-1'\nrules:\n{rule}", encoding="utf-8")
    return path


def valid_rule() -> str:
    return """- id: tyrano
  label: TyranoScript
  variant: TyranoBuilder/TyranoScript
  status: formal
  priority: 20
  enabled: true
  references:
    - https://tyranoscript.com/
  threshold: 0.70
  all:
    - op: path_exists
      path: data/system/Config.tjs
      weight: 0.45
  any:
    - op: path_exists
      path: tyrano/tyrano.js
      weight: 0.45
    - op: text_contains
      path: data/system/Config.tjs
      value: projectID
      weight: 0.25
  negative:
    - op: path_exists
      path: Editor.exe
      weight: -0.10
"""


def suffix_rule(*, offset: int = 28) -> str:
    return f"""- id: qlie
  label: QLIE
  status: formal
  references:
    - https://github.com/morkt/GARbro
  threshold: 0.70
  all:
    - op: magic_from_end
      path: data.pack
      value: FilePackVer3.0
      offset: {offset}
      weight: 1.0
"""
