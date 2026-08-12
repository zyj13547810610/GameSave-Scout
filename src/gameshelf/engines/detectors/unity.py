"""Recognize Unity player layout without loading game assemblies."""

from __future__ import annotations

from gameshelf.engines.base import DetectionContext
from gameshelf.engines.models import EngineEvidence, EngineMatch


class UnityDetector:
    def cheap_probe(self, context: DetectionContext) -> bool:
        return (context.game_dir / "UnityPlayer.dll").is_file()

    def inspect(self, context: DetectionContext) -> EngineMatch | None:
        root = context.game_dir
        if not (root / "UnityPlayer.dll").is_file():
            return None
        executable = context.executable
        executables = [executable] if executable is not None else tuple(root.glob("*.exe"))
        for candidate in executables:
            if candidate is None or candidate.parent != root:
                continue
            data = root / f"{candidate.stem}_Data"
            if (data / "globalgamemanagers").is_file():
                return EngineMatch(
                    "unity",
                    None,
                    0.97,
                    (
                        EngineEvidence(
                            "unity_player", "发现 UnityPlayer.dll", 0.42, "UnityPlayer.dll"
                        ),
                        EngineEvidence(
                            "unity_data",
                            "发现同名 _Data/globalgamemanagers",
                            0.55,
                            data.name,
                        ),
                    ),
                    "unity-2026.08.12",
                )
        return None
