"""Merge snapshot rules, Ludusavi, and bounded engine hints without persisting."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from gameshelf.library.models import Game
from gameshelf.library.service import GameNotFoundError, LibraryService
from gameshelf.rules.catalog import RuleSnapshot
from gameshelf.saves.engine_hints import EngineSaveHintProvider, load_engine_metadata
from gameshelf.saves.ludusavi_index import InvalidLudusaviIndex, LudusaviIndex
from gameshelf.saves.ludusavi_index_matcher import IndexedLudusaviMatcher
from gameshelf.saves.ludusavi_models import ManifestMatch
from gameshelf.saves.ludusavi_provider import SnapshotUpdateError
from gameshelf.saves.models import (
    SaveLocationSuggestion,
    SuggestionCategory,
    SuggestionEvidence,
    SuggestionEvidenceSource,
    SuggestionGroup,
)
from gameshelf.saves.repository import SaveLocationRepository
from gameshelf.saves.rule_identity import collect_rule_identity
from gameshelf.saves.rule_probe import BoundedRuleProbe
from gameshelf.saves.templates import InvalidPathTemplate, PathTemplateResolver
from gameshelf.scanning.path_keys import windows_path_key

logger = logging.getLogger(__name__)
_PROBE_DIAGNOSTIC_MESSAGES = {
    "registry_probe_failed": "存在性检查失败，已按可能路径保留",
    "filesystem_probe_failed": "存在性检查失败，已按可能路径保留",
    "reparse_point_skipped": "存在性检查跳过了链接或重解析点",
    "network_or_device_root_rejected": "存在性检查拒绝网络或设备路径",
    "depth_limit_reached": "存在性检查达到最大深度",
    "entry_limit_reached": "存在性检查达到条目上限",
    "match_limit_reached": "存在性检查达到结果上限",
    "deadline_reached": "存在性检查达到时间上限",
}


class LudusaviIndexProvider(Protocol):
    def index_session(self) -> AbstractContextManager[LudusaviIndex]: ...


class RegistryProbe(Protocol):
    def key_exists(self, key: str) -> bool: ...


type EngineMetadataLoader = Callable[[Game, Path], Mapping[str, str]]
type RuleSnapshotProvider = Callable[[], RuleSnapshot]


class _UnavailableRegistry:
    def key_exists(self, _key: str) -> bool:
        return False


@dataclass(frozen=True, slots=True)
class _RankedSuggestion:
    suggestion: SaveLocationSuggestion
    source_rank: int


class StaticSaveDiscovery:
    def __init__(
        self,
        *,
        library: LibraryService,
        save_repository: SaveLocationRepository,
        resolver: PathTemplateResolver,
        ludusavi_provider: LudusaviIndexProvider,
        engine_hints: EngineSaveHintProvider,
        rule_snapshot_provider: RuleSnapshotProvider,
        registry: RegistryProbe | None = None,
        engine_metadata_loader: EngineMetadataLoader | None = None,
        rule_probe: BoundedRuleProbe | None = None,
    ) -> None:
        self._library = library
        self._save_repository = save_repository
        self._resolver = resolver
        self._ludusavi_provider = ludusavi_provider
        registry_probe = registry or _UnavailableRegistry()
        self._rule_snapshot_provider = rule_snapshot_provider
        self._rule_probe = rule_probe or BoundedRuleProbe(resolver, registry_probe)
        self._engine_hints = engine_hints
        self._engine_metadata_loader = engine_metadata_loader or load_engine_metadata
        self._official_matcher: IndexedLudusaviMatcher | None = None

    def suggest_for_game(self, game_id: str) -> tuple[SaveLocationSuggestion, ...]:
        snapshot = self._rule_snapshot_provider()
        game = self._library.get_game(game_id)
        if game is None:
            raise GameNotFoundError(game_id)
        install_dir = self._library.install_directory(game_id)
        recorded_locations = self._save_repository.list_for_game(game_id)
        existing = {
            (_canonical_kind(location.kind, location.path_template), location.path_key)
            for location in recorded_locations
        }
        identity = collect_rule_identity(game, recorded_locations)
        engine_metadata = self._engine_metadata_loader(game, install_dir)
        metadata = {
            **engine_metadata,
            **identity.as_rule_metadata(),
        }

        candidates: list[_RankedSuggestion] = []
        try:
            game_rules = snapshot.save_rules.suggest_game_specific(
                game,
                install_dir,
                metadata,
            )
            for source, source_rank in (("user", 0), ("builtin", 1)):
                selected = tuple(
                    _declarative_group(item, game_specific=True)
                    for item in game_rules
                    if _declarative_source(item) == source
                )
                candidates.extend(_ranked(selected, source_rank=source_rank))
        except Exception as error:
            logger.warning("游戏专属存档规则不可用，已跳过：%s", error)

        try:
            with self._ludusavi_provider.index_session() as index:
                if (
                    self._official_matcher is None
                    or self._official_matcher.manifest_sha256 != index.metadata.manifest_sha256
                ):
                    self._official_matcher = IndexedLudusaviMatcher(
                        index,
                        self._resolver,
                    )
                official_matches = self._official_matcher.find(game, install_dir)
            candidates.extend(
                _ranked(
                    self._manifest_suggestions(
                        official_matches,
                        evidence_source="ludusavi",
                        source_detail="Ludusavi 官方清单",
                    ),
                    source_rank=2,
                )
            )
        except (InvalidLudusaviIndex, SnapshotUpdateError, OSError) as error:
            logger.warning("Ludusavi 官方索引不可用，已跳过：%s", error)

        experimental = snapshot.engine_detection.is_experimental(game.engine_id)
        try:
            engine_rules = snapshot.save_rules.suggest_engine(game, install_dir, metadata)
            for source, source_rank in (("user", 3), ("builtin", 4)):
                selected = tuple(
                    _declarative_group(item, game_specific=False)
                    for item in engine_rules
                    if _declarative_source(item) == source
                )
                candidates.extend(_ranked(selected, source_rank=source_rank))
        except Exception as error:
            logger.warning("引擎通用存档规则不可用，已跳过：%s", error)
        for suggestion in self._engine_hints.suggest(
            game,
            install_dir,
            engine_metadata,
        ):
            source_evidence = tuple(
                SuggestionEvidence("engine", detail) for detail in suggestion.evidence
            )
            group: SuggestionGroup
            if experimental:
                group = "experimental"
            elif suggestion.confidence >= 0.9:
                group = "exact"
            else:
                group = "possible"
            candidates.append(
                _RankedSuggestion(
                    replace(
                        suggestion,
                        source_evidence=source_evidence,
                        preselected=(
                            group == "exact"
                            and suggestion.kind != "registry"
                            and suggestion.confidence >= 0.9
                        ),
                        group=group,
                    ),
                    source_rank=5,
                )
            )

        merged: dict[tuple[str, str], _RankedSuggestion] = {}
        for ranked in candidates:
            suggestion = self._with_availability(ranked.suggestion, install_dir)
            key = self._suggestion_key(suggestion, install_dir)
            if key is None or key in existing:
                continue
            previous = merged.get(key)
            current = replace(ranked, suggestion=suggestion)
            merged[key] = current if previous is None else _merge_ranked(previous, current)

        finalized: list[SaveLocationSuggestion] = []
        for key, ranked in merged.items():
            suggestion = ranked.suggestion
            preselected = (
                suggestion.preselected
                and suggestion.availability == "found"
                and suggestion.confidence >= 0.9
                and suggestion.category == "save"
                and suggestion.kind != "registry"
                and suggestion.group == "exact"
            )
            suggestion_id = hashlib.sha256(f"{key[0]}\0{key[1]}".encode()).hexdigest()[:20]
            finalized.append(
                replace(
                    suggestion,
                    suggestion_id=suggestion_id,
                    preselected=preselected,
                )
            )
        availability_rank = {"found": 0, "predicted": 1}
        group_rank = {"exact": 0, "possible": 1, "experimental": 2}
        return tuple(
            sorted(
                finalized,
                key=lambda item: (
                    availability_rank[item.availability],
                    group_rank[item.group],
                    -item.confidence,
                    item.display_path.casefold(),
                ),
            )
        )

    def invalidate_ludusavi(self) -> None:
        self._official_matcher = None

    def registry_targets_for_game(self, game_id: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
        return tuple(
            (suggestion.path_template, suggestion.evidence)
            for suggestion in self.suggest_for_game(game_id)
            if suggestion.kind == "registry"
        )

    def _manifest_suggestions(
        self,
        matches: tuple[ManifestMatch, ...],
        *,
        evidence_source: SuggestionEvidenceSource,
        source_detail: str,
    ) -> tuple[SaveLocationSuggestion, ...]:
        suggestions: list[SaveLocationSuggestion] = []
        for match in matches:
            for location in match.locations:
                details = (source_detail, *match.evidence, *location.evidence)
                source_evidence = tuple(
                    SuggestionEvidence(evidence_source, detail) for detail in details
                )
                suggestions.append(
                    SaveLocationSuggestion(
                        kind=location.kind,
                        path_template=location.path_template,
                        display_path=location.display_path,
                        source="ludusavi",
                        confidence=match.confidence,
                        evidence=details,
                        source_evidence=source_evidence,
                        preselected=(
                            match.confirmed
                            and location.preselected
                            and match.confidence >= 0.9
                            and location.kind != "registry"
                        ),
                        category=location.category,
                        group="exact" if match.confirmed else "possible",
                    )
                )
        return tuple(suggestions)

    def _suggestion_key(
        self,
        suggestion: SaveLocationSuggestion,
        install_dir: Path,
    ) -> tuple[str, str] | None:
        if suggestion.kind == "registry":
            return suggestion.kind, suggestion.path_template.casefold()
        try:
            path = self._resolver.expand(suggestion.path_template, install_dir)
        except InvalidPathTemplate:
            return None
        return (
            _canonical_kind(suggestion.kind, suggestion.path_template),
            windows_path_key(path),
        )

    def _with_availability(
        self,
        suggestion: SaveLocationSuggestion,
        install_dir: Path,
    ) -> SaveLocationSuggestion:
        try:
            result = self._rule_probe.probe(
                suggestion.kind,
                suggestion.path_template,
                install_dir,
            )
        except (OSError, RuntimeError, ValueError) as error:
            logger.warning("存档建议存在性检查失败，已按可能路径保留：%s", error)
            diagnostic = "存在性检查失败，已按可能路径保留"
            return replace(
                suggestion,
                availability="predicted",
                evidence=tuple(dict.fromkeys((*suggestion.evidence, diagnostic))),
            )
        diagnostics = tuple(
            _PROBE_DIAGNOSTIC_MESSAGES.get(code, code) for code in result.diagnostics
        )
        evidence = tuple(dict.fromkeys((*suggestion.evidence, *diagnostics)))
        return replace(
            suggestion,
            availability="found" if result.found else "predicted",
            evidence=evidence,
        )


def _merge_ranked(
    first: _RankedSuggestion,
    second: _RankedSuggestion,
) -> _RankedSuggestion:
    preferred = first if first.source_rank <= second.source_rank else second
    other = second if preferred is first else first
    merged = _merge(preferred.suggestion, other.suggestion)
    return _RankedSuggestion(merged, min(first.source_rank, second.source_rank))


def _merge(
    preferred: SaveLocationSuggestion,
    other: SaveLocationSuggestion,
) -> SaveLocationSuggestion:
    evidence = tuple(dict.fromkeys((*preferred.evidence, *other.evidence)))
    source_evidence = tuple(
        {
            (item.source, item.detail): item
            for item in (*preferred.source_evidence, *other.source_evidence)
        }.values()
    )
    category: SuggestionCategory = (
        "save"
        if "save" in {preferred.category, other.category}
        else "config"
        if "config" in {preferred.category, other.category}
        else "other"
    )
    group = _stronger_group(preferred.group, other.group)
    concrete_kind = next(
        (item.kind for item in (preferred, other) if item.kind != "glob"),
        preferred.kind,
    )
    return replace(
        preferred,
        kind=concrete_kind,
        confidence=max(preferred.confidence, other.confidence),
        evidence=evidence,
        source_evidence=source_evidence,
        preselected=preferred.preselected or other.preselected,
        category=category,
        group=group,
        availability=(
            "found" if "found" in {preferred.availability, other.availability} else "predicted"
        ),
    )


def _stronger_group(first: SuggestionGroup, second: SuggestionGroup) -> SuggestionGroup:
    ranks = {"exact": 0, "possible": 1, "experimental": 2}
    return first if ranks[first] <= ranks[second] else second


def _canonical_kind(kind: str, path_template: str) -> str:
    if kind == "registry":
        return "registry"
    if kind == "glob" and any(character in path_template for character in "*?["):
        return "glob"
    return "path"


def _ranked(
    suggestions: tuple[SaveLocationSuggestion, ...],
    *,
    source_rank: int,
) -> tuple[_RankedSuggestion, ...]:
    return tuple(_RankedSuggestion(item, source_rank) for item in suggestions)


def _declarative_group(
    suggestion: SaveLocationSuggestion,
    *,
    game_specific: bool,
) -> SaveLocationSuggestion:
    if suggestion.group == "experimental":
        return suggestion
    group: SuggestionGroup = (
        "exact" if game_specific or suggestion.confidence >= 0.9 else "possible"
    )
    return replace(
        suggestion,
        group=group,
        preselected=(group == "exact" and suggestion.kind != "registry"),
    )


def _declarative_source(suggestion: SaveLocationSuggestion) -> str | None:
    return next(
        (
            item.source
            for item in suggestion.source_evidence
            if item.source in {"user", "builtin"}
        ),
        None,
    )
