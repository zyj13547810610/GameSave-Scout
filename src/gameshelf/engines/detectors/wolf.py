"""Recognize WOLF RPG Editor exported game layouts."""

from __future__ import annotations

from gameshelf.engines.base import DetectionContext
from gameshelf.engines.models import EngineEvidence, EngineMatch


class WolfRpgDetector:
    def cheap_probe(self, context: DetectionContext) -> bool:
        return (context.game_dir / "Game.exe").is_file()

    def inspect(self, context: DetectionContext) -> EngineMatch | None:
        root = context.game_dir
        executable = root / "Game.exe"
        plain = root / "Data" / "BasicData" / "Game.dat"
        encrypted = tuple(root.glob("*.wolf")) + tuple((root / "Data").glob("*.wolf"))
        if not executable.is_file() or (not plain.is_file() and not encrypted):
            return None
        companion = plain if plain.is_file() else encrypted[0]
        return EngineMatch(
            "wolf_rpg",
            None,
            0.94,
            (
                EngineEvidence("wolf_player", "发现 WOLF Game.exe", 0.4, "Game.exe"),
                EngineEvidence(
                    "wolf_data",
                    "发现 WOLF 游戏数据",
                    0.54,
                    companion.relative_to(root).as_posix(),
                ),
            ),
            "wolf-2026.08.12",
        )
