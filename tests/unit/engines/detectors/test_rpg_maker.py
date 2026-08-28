import pytest

from gamesave_scout.engines.base import DetectionContext
from gamesave_scout.engines.detectors.rpg_maker import RpgMakerDetector
from gamesave_scout.engines.registry import DetectorRegistry


@pytest.mark.parametrize(
    ("files", "engine_id", "variant"),
    [
        ({"RPG_RT.exe": b"MZ", "RPG_RT.ldb": b"LcfDataBase"}, "rpg_maker_2k", None),
        (
            {"Game.ini": b"[Game]\nLibrary=RGSS104E.dll", "Game.rgssad": b"RGSSAD"},
            "rpg_maker_xp",
            "XP",
        ),
        (
            {"Game.ini": b"[Game]\nLibrary=RGSS202E.dll", "Game.rgss2a": b"RGSS2A"},
            "rpg_maker_vx",
            "VX",
        ),
        (
            {"Game.ini": b"[Game]\nLibrary=RGSS301.dll", "Game.rgss3a": b"RGSS3A"},
            "rpg_maker_vx_ace",
            "VX Ace",
        ),
        (
            {
                "Game.ini": b"[Game]\nLibrary=RGSS301.dll",
                "Data/Scripts.rvdata2": b"synthetic scripts",
            },
            "rpg_maker_vx_ace",
            "VX Ace",
        ),
        (
            {"www/js/rpg_core.js": b"Utils.RPGMAKER_NAME = 'MV'", "www/data/System.json": b"{}"},
            "rpg_maker_mv",
            "MV",
        ),
        (
            {"js/rpg_core.js": b"Utils.RPGMAKER_NAME = 'MV'", "data/System.json": b"{}"},
            "rpg_maker_mv",
            "MV",
        ),
        (
            {"js/rmmz_core.js": b"Utils.RPGMAKER_NAME = 'MZ'", "data/System.json": b"{}"},
            "rpg_maker_mz",
            "MZ",
        ),
    ],
)
def test_rpg_maker_variants(file_tree, files, engine_id, variant) -> None:
    match = RpgMakerDetector().inspect(DetectionContext(file_tree(files), None))

    assert match is not None
    assert (match.engine_id, match.variant) == (engine_id, variant)


@pytest.mark.parametrize(
    "files",
    [{"Game.exe": b"MZ"}, {"www/index.html": b"html"}, {"Game.rgss3a": b"RGSS3A"}],
)
def test_generic_files_do_not_force_rpg_maker(file_tree, files) -> None:
    assert RpgMakerDetector().inspect(DetectionContext(file_tree(files), None)) is None


def test_rpg_maker_mv_outer_launcher_data_www_layout(file_tree) -> None:
    root = file_tree(
        {
            "data/package.json": b'{"main":"www/index.html"}',
            "data/www/js/rpg_core.js": b"// rpg_core.js v1.6.2\nUtils.RPGMAKER_NAME = 'MV'",
            "data/www/data/System.json": b"{}",
        }
    )

    outcome = DetectorRegistry((RpgMakerDetector(),)).detect(root, None)

    assert outcome.best is not None
    assert outcome.best.engine_id == "rpg_maker_mv"
    assert outcome.best.variant == "MV"


@pytest.mark.parametrize(
    "files",
    [
        {"data/www/js/rpg_core.js": b"Utils.RPGMAKER_NAME = 'MV'"},
        {"data/www/data/System.json": b"{}"},
        {
            "data/www/js/rpg_core.js": b"generic javascript",
            "data/www/data/System.json": b"{}",
        },
    ],
)
def test_rpg_maker_mv_outer_launcher_incomplete_evidence_remains_unknown(
    file_tree,
    files,
) -> None:
    root = file_tree(files)

    assert DetectorRegistry((RpgMakerDetector(),)).detect(root, None).best is None
