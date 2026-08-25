"""Recognize creator tools that require product metadata plus runtime layout."""

from __future__ import annotations

from dataclasses import dataclass

from gamesave_scout.engines.base import DetectionContext
from gamesave_scout.engines.models import EngineEvidence, EngineMatch
from gamesave_scout.scanning.pe_metadata import read_pe_metadata


@dataclass(frozen=True)
class _CreatorSignature:
    engine_id: str
    label: str
    product_markers: tuple[str, ...]
    companion_paths: tuple[str, ...]


_SIGNATURES = (
    _CreatorSignature(
        "smile_game_builder",
        "SMILE GAME BUILDER",
        ("smile game builder", "smileboom"),
        ("Managed/Assembly-CSharp.dll",),
    ),
    _CreatorSignature(
        "rpg_developer_bakin",
        "RPG Developer Bakin",
        ("rpg developer bakin", "bakinplayer"),
        ("BakinGameData.dat", "data/BakinGameData.dat"),
    ),
    _CreatorSignature(
        "visual_novel_maker",
        "Visual Novel Maker",
        ("visual novel maker",),
        ("data/Scripts.json", "scripts/Script.json"),
    ),
)


class CreatorEngineDetector:
    def cheap_probe(self, context: DetectionContext) -> bool:
        return context.executable is not None and context.executable.is_file()

    def inspect(self, context: DetectionContext) -> EngineMatch | None:
        if context.executable is None or not context.executable.is_file():
            return None
        metadata = read_pe_metadata(context.executable)
        metadata_text = " ".join(
            (metadata.product_name, metadata.file_description, metadata.company_name)
        ).casefold()
        root = context.game_dir
        for signature in _SIGNATURES:
            has_product = any(marker in metadata_text for marker in signature.product_markers)
            companion = next(
                (
                    relative
                    for relative in signature.companion_paths
                    if root.joinpath(*relative.split("/")).exists()
                ),
                None,
            )
            if not has_product or companion is None:
                continue
            return EngineMatch(
                signature.engine_id,
                None,
                0.94,
                (
                    EngineEvidence(
                        "creator_product",
                        f"PE 产品信息包含 {signature.label}",
                        0.55,
                        context.executable.name,
                    ),
                    EngineEvidence(
                        "creator_layout",
                        f"发现 {signature.label} 专属运行时数据",
                        0.39,
                        companion,
                    ),
                ),
                "creator-engines-2026.08.12",
            )
        return None
