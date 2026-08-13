"""Recognize RPG Maker runtime generations from paired project/runtime evidence."""

from __future__ import annotations

from pathlib import Path

from gameshelf.engines.base import DetectionContext
from gameshelf.engines.bounded_reader import read_text_limit
from gameshelf.engines.models import EngineEvidence, EngineMatch

_VERSION = "rpg-maker-2026.08.13"


class RpgMakerDetector:
    def cheap_probe(self, context: DetectionContext) -> bool:
        root = context.game_dir
        return any(
            (root / name).exists()
            for name in ("RPG_RT.exe", "Game.ini", "www", "js", "mkxp.json", "mkxp.conf")
        )

    def inspect(self, context: DetectionContext) -> EngineMatch | None:
        root = context.game_dir
        if (root / "RPG_RT.exe").is_file() and any(
            (root / name).is_file() for name in ("RPG_RT.ldb", "RPG_RT.lmt")
        ):
            return _match("rpg_maker_2k", None, "rpg_rt_pair", "RPG_RT runtime and map/database")

        ini = root / "Game.ini"
        if ini.is_file():
            text = read_text_limit(ini).casefold()
            families = (
                ("rgss1", "rpg_maker_xp", "XP", (".rgssad", "rgss1")),
                ("rgss2", "rpg_maker_vx", "VX", (".rgss2a", "rgss2")),
                ("rgss3", "rpg_maker_vx_ace", "VX Ace", (".rgss3a", "rgss3")),
            )
            for marker, engine_id, variant, companions in families:
                has_unpacked_vx_ace_scripts = (
                    marker == "rgss3"
                    and (root / "Data" / "Scripts.rvdata2").is_file()
                )
                if marker in text and (
                    _has_companion(root, companions) or has_unpacked_vx_ace_scripts
                ):
                    return _match(
                        engine_id,
                        variant,
                        "rgss_family",
                        f"Game.ini selects {marker.upper()}",
                    )

        layouts = (
            (
                root / "www" / "js" / "rpg_core.js",
                root / "www" / "data" / "System.json",
                "rpg_maker_mv",
                "MV",
            ),
            (root / "js" / "rpg_core.js", root / "data" / "System.json", "rpg_maker_mv", "MV"),
            (
                root / "www" / "js" / "rmmz_core.js",
                root / "www" / "data" / "System.json",
                "rpg_maker_mz",
                "MZ",
            ),
            (root / "js" / "rmmz_core.js", root / "data" / "System.json", "rpg_maker_mz", "MZ"),
        )
        for script, system, engine_id, variant in layouts:
            script_matches = (
                script.is_file()
                and variant.casefold() in read_text_limit(script).casefold()
            )
            if script_matches and system.is_file():
                return _match(
                    engine_id,
                    variant,
                    "javascript_runtime",
                    f"{variant} runtime and System.json",
                )

        mkxp_config = next(
            (
                root / name
                for name in ("mkxp.json", "mkxp.conf")
                if (root / name).is_file()
            ),
            None,
        )
        has_mkxp_exe = any(
            "mkxp" in path.name.casefold() for path in root.glob("*.exe")
        )
        if mkxp_config is not None and has_mkxp_exe:
            return _match(
                "mkxp_z",
                "MKXP-Z",
                "mkxp_runtime",
                "MKXP configuration and executable",
            )
        has_rgu_exe = any(
            path.name.casefold().startswith("rgu") for path in root.glob("*.exe")
        )
        if has_rgu_exe and _has_companion(root, (".rgssad", ".rgss2a", ".rgss3a")):
            return _match("rgu", None, "rgu_runtime", "RGU executable and RGSS archive")
        return None


def _has_companion(root: Path, markers: tuple[str, ...]) -> bool:
    for path in root.iterdir():
        name = path.name.casefold()
        if any(marker in name for marker in markers):
            return True
    return False


def _match(engine_id: str, variant: str | None, code: str, detail: str) -> EngineMatch:
    return EngineMatch(
        engine_id,
        variant,
        0.96,
        (EngineEvidence(code, detail, 0.96),),
        _VERSION,
    )
