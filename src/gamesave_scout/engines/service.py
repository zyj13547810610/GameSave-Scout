"""Compose the bounded engine detectors used by library scans."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from gamesave_scout.engines.base import EngineDetector
from gamesave_scout.engines.detectors.creator_engines import CreatorEngineDetector
from gamesave_scout.engines.detectors.renpy import RenPyDetector
from gamesave_scout.engines.detectors.rpg_maker import RpgMakerDetector
from gamesave_scout.engines.detectors.runtime_frameworks import RuntimeFrameworkDetector
from gamesave_scout.engines.detectors.unity import UnityDetector
from gamesave_scout.engines.detectors.unreal import UnrealDetector
from gamesave_scout.engines.detectors.wolf import WolfRpgDetector
from gamesave_scout.engines.models import DetectionOutcome
from gamesave_scout.engines.registry import DetectorRegistry
from gamesave_scout.engines.rule_detector import RuleDetector
from gamesave_scout.engines.rule_schema import EngineCategory, EngineRule, load_engine_rules
from gamesave_scout.rules.serialization import serialize_rule_document


@dataclass(frozen=True)
class EngineOption:
    id: str
    label: str
    experimental: bool = False
    category: EngineCategory | None = None


_BUILTIN_OPTIONS = (
    EngineOption("rpg_maker_2k", "RPG Maker 2000/2003", category="visual_novel_doujin"),
    EngineOption("rpg_maker_xp", "RPG Maker XP", category="visual_novel_doujin"),
    EngineOption("rpg_maker_vx", "RPG Maker VX", category="visual_novel_doujin"),
    EngineOption("rpg_maker_vx_ace", "RPG Maker VX Ace", category="visual_novel_doujin"),
    EngineOption("rpg_maker_mv", "RPG Maker MV", category="visual_novel_doujin"),
    EngineOption("rpg_maker_mz", "RPG Maker MZ", category="visual_novel_doujin"),
    EngineOption("mkxp_z", "MKXP-Z", category="visual_novel_doujin"),
    EngineOption("rgu", "RGU", category="visual_novel_doujin"),
    EngineOption("renpy", "Ren'Py", category="visual_novel_doujin"),
    EngineOption("unity", "Unity", category="general"),
    EngineOption("unreal", "Unreal Engine", category="general"),
    EngineOption("wolf_rpg", "WOLF RPG Editor", category="visual_novel_doujin"),
    EngineOption("smile_game_builder", "SMILE GAME BUILDER", category="visual_novel_doujin"),
    EngineOption("rpg_developer_bakin", "RPG Developer Bakin", category="visual_novel_doujin"),
    EngineOption("visual_novel_maker", "Visual Novel Maker", category="visual_novel_doujin"),
    EngineOption("source", "Source", category="general"),
    EngineOption("source2", "Source 2", category="general"),
    EngineOption("monogame", "MonoGame", category="general"),
    EngineOption("fna", "FNA", category="general"),
    EngineOption("xna", "Microsoft XNA", category="general"),
    EngineOption("love", "LÖVE", category="general"),
    EngineOption("construct2", "Construct 2", True, "general"),
    EngineOption("construct3", "Construct 3", True, "general"),
)
BUILTIN_ENGINE_IDS = frozenset(option.id for option in _BUILTIN_OPTIONS)
BUILTIN_ENGINE_CACHE_VERSION = "2026.08.27-1"


class EngineDetectionService:
    def __init__(
        self,
        registry: DetectorRegistry,
        options: tuple[EngineOption, ...] = (),
        rule_versions: tuple[str, ...] = (),
    ) -> None:
        self._registry = registry
        self._options = options
        self._options_by_id = {option.id: option for option in options}
        versions = ",".join(sorted(set(rule_versions))) or "none"
        self._cache_version = (
            f"builtin:{BUILTIN_ENGINE_CACHE_VERSION}|declarative:{versions}"
        )

    @classmethod
    def builtins_only(cls) -> EngineDetectionService:
        return cls.from_rules(())

    @classmethod
    def from_rules_file(cls, rules_file: Path) -> EngineDetectionService:
        return cls.from_rules(load_engine_rules(rules_file))

    @classmethod
    def from_rules(
        cls,
        rules: Sequence[EngineRule],
    ) -> EngineDetectionService:
        all_rules = tuple(rules)
        enabled_rules = tuple(rule for rule in all_rules if rule.metadata.enabled)
        detectors: tuple[EngineDetector, ...] = (
            RpgMakerDetector(),
            RenPyDetector(),
            UnityDetector(),
            UnrealDetector(),
            WolfRpgDetector(),
            CreatorEngineDetector(),
            RuntimeFrameworkDetector(),
            *(RuleDetector(rule) for rule in enabled_rules),
        )
        options_by_id = {option.id: option for option in _BUILTIN_OPTIONS}
        for rule in enabled_rules:
            options_by_id[rule.engine_id] = EngineOption(
                rule.engine_id, rule.label, rule.experimental, rule.category
            )
        options = tuple(
            sorted(
                options_by_id.values(),
                key=lambda option: (option.experimental, option.label.casefold()),
            )
        )
        rules_digest = (
            hashlib.sha256(
                b"\0".join(serialize_rule_document(rule) for rule in all_rules)
            ).hexdigest()
            if all_rules
            else "none"
        )
        return cls(
            DetectorRegistry(detectors),
            options,
            (rules_digest,),
        )

    @property
    def cache_version(self) -> str:
        return self._cache_version

    def detect(self, game_dir: Path, executable: Path | None) -> DetectionOutcome:
        return self._registry.detect(game_dir, executable)

    def list_options(self) -> tuple[EngineOption, ...]:
        return self._options

    def has_option(self, engine_id: str) -> bool:
        return engine_id in self._options_by_id

    def label_for(self, engine_id: str | None) -> str:
        if engine_id is None:
            return "未知引擎"
        if engine_id.startswith("custom:"):
            return engine_id.removeprefix("custom:")
        option = self._options_by_id.get(engine_id)
        return option.label if option is not None else engine_id

    def is_experimental(self, engine_id: str | None) -> bool:
        option = self._options_by_id.get(engine_id or "")
        return option.experimental if option is not None else False

    def category_for(self, engine_id: str | None) -> EngineCategory | None:
        option = self._options_by_id.get(engine_id or "")
        return option.category if option is not None else None
