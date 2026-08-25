from pathlib import Path

import pytest

from gamesave_scout.engines.base import DetectionContext
from gamesave_scout.engines.detectors.creator_engines import CreatorEngineDetector
from gamesave_scout.engines.registry import DetectorRegistry
from gamesave_scout.engines.rule_detector import RuleDetector
from gamesave_scout.engines.rule_schema import load_engine_rules
from gamesave_scout.scanning.pe_metadata import PeMetadata


@pytest.mark.parametrize(
    ("engine_id", "files"),
    [
        (
            "tyrano",
            {
                "data/system/Config.tjs": b";projectID = sample",
                "tyrano/tyrano.js": b"TYRANO",
            },
        ),
        ("kirikiri", {"data.xp3": b"XP3\r\n \n\x1a\x8bg\x01", "startup.tjs": b"System"}),
        (
            "choicescript",
            {
                "scenes/startup.txt": b"*title Sample",
                "scenes/choicescript_stats.txt": b"*stat_chart",
            },
        ),
        ("srpg_studio", {"data.dts": b"\x00DTS", "runtime.rts": b"\x00RTS"}),
        (
            "pixel_game_maker_mv",
            {"package.json": b'{"name":"ActionGameKit"}', "js/libs/AGtk.js": b"Agtk"},
        ),
    ],
)
def test_mtool_listed_rules(file_tree, engine_id, files) -> None:
    rules = load_engine_rules(Path("resources/rules/builtin/engines.yaml"))
    outcome = DetectorRegistry(RuleDetector(rule) for rule in rules).detect(
        file_tree(files), None
    )
    assert outcome.best is not None
    assert outcome.best.engine_id == engine_id


@pytest.mark.parametrize(
    ("product", "companion", "engine_id"),
    [
        ("SMILE GAME BUILDER", "Managed/Assembly-CSharp.dll", "smile_game_builder"),
        ("RPG Developer Bakin", "BakinGameData.dat", "rpg_developer_bakin"),
        ("Visual Novel Maker", "data/Scripts.json", "visual_novel_maker"),
    ],
)
def test_creator_requires_product_and_companion(
    file_tree, monkeypatch, product, companion, engine_id
) -> None:
    root = file_tree({"Player.exe": b"MZ", companion: b"data"})
    monkeypatch.setattr(
        "gamesave_scout.engines.detectors.creator_engines.read_pe_metadata",
        lambda _: PeMetadata(product, product, "", "x64"),
    )
    match = CreatorEngineDetector().inspect(
        DetectionContext(root, root / "Player.exe")
    )
    assert match is not None and match.engine_id == engine_id


def test_generic_unity_metadata_without_creator_companion_is_unknown(
    file_tree, monkeypatch
) -> None:
    root = file_tree({"Player.exe": b"MZ", "UnityPlayer.dll": b"MZ"})
    monkeypatch.setattr(
        "gamesave_scout.engines.detectors.creator_engines.read_pe_metadata",
        lambda _: PeMetadata("SMILE GAME BUILDER", "", "SmileBoom", "x64"),
    )
    assert CreatorEngineDetector().inspect(
        DetectionContext(root, root / "Player.exe")
    ) is None
