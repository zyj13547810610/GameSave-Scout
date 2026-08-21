"""Compose the bounded engine detectors used by library scans."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from gameshelf.engines.base import EngineDetector
from gameshelf.engines.detectors.creator_engines import CreatorEngineDetector
from gameshelf.engines.detectors.renpy import RenPyDetector
from gameshelf.engines.detectors.rpg_maker import RpgMakerDetector
from gameshelf.engines.detectors.unity import UnityDetector
from gameshelf.engines.detectors.unreal import UnrealDetector
from gameshelf.engines.detectors.wolf import WolfRpgDetector
from gameshelf.engines.models import DetectionOutcome
from gameshelf.engines.registry import DetectorRegistry
from gameshelf.engines.rule_detector import RuleDetector
from gameshelf.engines.rule_schema import EngineRule, load_engine_rules


@dataclass(frozen=True)
class EngineOption:
    id: str
    label: str
    experimental: bool = False


_BUILTIN_OPTIONS = (
    EngineOption("rpg_maker_2k", "RPG Maker 2000/2003"),
    EngineOption("rpg_maker_xp", "RPG Maker XP"),
    EngineOption("rpg_maker_vx", "RPG Maker VX"),
    EngineOption("rpg_maker_vx_ace", "RPG Maker VX Ace"),
    EngineOption("rpg_maker_mv", "RPG Maker MV"),
    EngineOption("rpg_maker_mz", "RPG Maker MZ"),
    EngineOption("mkxp_z", "MKXP-Z"),
    EngineOption("rgu", "RGU"),
    EngineOption("renpy", "Ren'Py"),
    EngineOption("unity", "Unity"),
    EngineOption("unreal", "Unreal Engine"),
    EngineOption("wolf_rpg", "WOLF RPG Editor"),
    EngineOption("smile_game_builder", "SMILE GAME BUILDER"),
    EngineOption("rpg_developer_bakin", "RPG Developer Bakin"),
    EngineOption("visual_novel_maker", "Visual Novel Maker"),
)
BUILTIN_ENGINE_CACHE_VERSION = "2026.08.18-1"


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
        return cls._from_rules(())

    @classmethod
    def from_rules_file(cls, rules_file: Path) -> EngineDetectionService:
        return cls._from_rules(load_engine_rules(rules_file))

    @classmethod
    def _from_rules(
        cls,
        rules: tuple[EngineRule, ...],
    ) -> EngineDetectionService:
        enabled_rules = tuple(rule for rule in rules if rule.metadata.enabled)
        detectors: tuple[EngineDetector, ...] = (
            RpgMakerDetector(),
            RenPyDetector(),
            UnityDetector(),
            UnrealDetector(),
            WolfRpgDetector(),
            CreatorEngineDetector(),
            *(RuleDetector(rule) for rule in enabled_rules),
        )
        options_by_id = {option.id: option for option in _BUILTIN_OPTIONS}
        for rule in enabled_rules:
            options_by_id[rule.engine_id] = EngineOption(
                rule.engine_id, rule.label, rule.experimental
            )
        options = tuple(
            sorted(
                options_by_id.values(),
                key=lambda option: (option.experimental, option.label.casefold()),
            )
        )
        return cls(
            DetectorRegistry(detectors),
            options,
            tuple(rule.version for rule in rules),
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
