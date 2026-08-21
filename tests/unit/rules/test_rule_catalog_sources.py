from pathlib import Path

from gameshelf.engines.rule_schema import load_engine_rules


def test_every_formal_builtin_engine_rule_has_public_references() -> None:
    rules = load_engine_rules(Path("resources/rules/engines.yaml"))

    missing = tuple(
        rule.metadata.qualified_id
        for rule in rules
        if not rule.experimental and not rule.metadata.references
    )

    assert missing == ()
