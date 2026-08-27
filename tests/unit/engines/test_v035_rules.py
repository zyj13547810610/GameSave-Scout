from pathlib import Path

import pytest

from gamesave_scout.engines.registry import DetectorRegistry
from gamesave_scout.engines.rule_detector import RuleDetector
from gamesave_scout.engines.rule_schema import load_engine_rules
from gamesave_scout.engines.service import EngineDetectionService

RULES_FILE = Path("resources/rules/builtin/engines.yaml")


def test_every_builtin_engine_rule_has_an_explicit_supported_category() -> None:
    rules = load_engine_rules(RULES_FILE)

    assert len(rules) == 80
    assert {rule.category for rule in rules} == {
        "general",
        "visual_novel_doujin",
    }
    assert next(rule for rule in rules if rule.engine_id == "godot").category == "general"
    assert next(rule for rule in rules if rule.engine_id == "kirikiri").category == (
        "visual_novel_doujin"
    )


def test_code_and_declarative_engine_categories_are_complete() -> None:
    service = EngineDetectionService.from_rules_file(RULES_FILE)

    assert service.category_for("unity") == "general"
    assert service.category_for("renpy") == "visual_novel_doujin"
    assert service.category_for("game_maker") == "general"
    assert service.category_for("suika2") == "visual_novel_doujin"
    assert service.category_for("missing") is None
    assert all(service.category_for(option.id) is not None for option in service.list_options())
    assert service.is_experimental("construct2") is True
    assert service.is_experimental("construct3") is True


@pytest.mark.parametrize(
    ("engine_id", "files"),
    [
        (
            "game_maker",
            {"data.win": b"FORM\0\0\0\0GEN8" + b"\0" * 32},
        ),
        (
            "cryengine",
            {"Bin64/CrySystem.dll": b"MZ", "Bin64/CryAction.dll": b"MZ"},
        ),
        (
            "re_engine",
            {"Game.exe": b"MZ", "re_chunk_000.pak": b"pak"},
        ),
        (
            "mt_framework",
            {"nativePC/rom/data.arc": b"arc"},
        ),
        (
            "defold",
            {
                "game.arci": b"index",
                "game.arcd": b"data",
                "game.dmanifest": b"manifest",
            },
        ),
        (
            "suika2",
            {
                "suika.exe": b"MZ",
                "conf/config.txt": b"window-title=Sample",
                "txt/init.txt": b"@bg file=bg/black.png",
            },
        ),
    ],
)
def test_v035_declarative_engine_combinations_match(
    tmp_path: Path,
    engine_id: str,
    files: dict[str, bytes],
) -> None:
    for relative, content in files.items():
        path = tmp_path.joinpath(*relative.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    outcome = _declarative_registry().detect(tmp_path, None)

    assert outcome.best is not None
    assert outcome.best.engine_id == engine_id


@pytest.mark.parametrize(
    "files",
    [
        {"data.win": b"FORM\0\0\0\0NOPE"},
        {"Bin64/CrySystem.dll": b"MZ"},
        {"re_chunk_000.pak": b"pak"},
        {"nativePC/readme.txt": b"not an archive"},
        {"game.arci": b"index", "game.arcd": b"data"},
        {"suika.exe": b"MZ", "conf/config.txt": b"config"},
    ],
)
def test_v035_declarative_engine_partial_combinations_remain_unknown(
    tmp_path: Path,
    files: dict[str, bytes],
) -> None:
    for relative, content in files.items():
        path = tmp_path.joinpath(*relative.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    assert _declarative_registry().detect(tmp_path, None).best is None


def _declarative_registry() -> DetectorRegistry:
    return DetectorRegistry(
        RuleDetector(rule) for rule in load_engine_rules(RULES_FILE)
    )
