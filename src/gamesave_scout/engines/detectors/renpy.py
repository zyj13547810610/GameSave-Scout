"""Recognize Ren'Py from scripts paired with its runtime."""

from __future__ import annotations

from gamesave_scout.engines.base import DetectionContext
from gamesave_scout.engines.models import EngineEvidence, EngineMatch


class RenPyDetector:
    def cheap_probe(self, context: DetectionContext) -> bool:
        return (context.game_dir / "game").is_dir()

    def inspect(self, context: DetectionContext) -> EngineMatch | None:
        root = context.game_dir
        game = root / "game"
        has_script = game.is_dir() and any(
            path.suffix.casefold() in {".rpy", ".rpyc"} for path in game.iterdir()
        )
        has_runtime = (root / "renpy").is_dir() or any(
            path.name.casefold().startswith("lib") and path.is_dir()
            for path in root.iterdir()
        )
        if not has_script or not has_runtime:
            return None
        return EngineMatch(
            "renpy",
            None,
            0.96,
            (
                EngineEvidence("renpy_script", "发现 Ren'Py game 脚本", 0.5, "game"),
                EngineEvidence("renpy_runtime", "发现 Ren'Py 运行时", 0.46, "renpy"),
            ),
            "renpy-2026.08.12",
        )
