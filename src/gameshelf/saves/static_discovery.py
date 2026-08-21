"""Merge custom, Ludusavi, and engine save hints without persisting them."""

from __future__ import annotations

import glob
import hashlib
import logging
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from itertools import islice
from pathlib import Path
from typing import Protocol

from gameshelf.library.models import Game
from gameshelf.library.service import GameNotFoundError, LibraryService
from gameshelf.saves.custom_manifest_provider import CustomManifestLoadResult
from gameshelf.saves.engine_hints import EngineSaveHintProvider, load_engine_metadata
from gameshelf.saves.ludusavi_index import InvalidLudusaviIndex, LudusaviIndex
from gameshelf.saves.ludusavi_index_matcher import IndexedLudusaviMatcher
from gameshelf.saves.ludusavi_matcher import LudusaviMatcher
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
from gameshelf.saves.templates import InvalidPathTemplate, PathTemplateResolver
from gameshelf.scanning.path_keys import windows_path_key

logger = logging.getLogger(__name__)


class LudusaviIndexProvider(Protocol):
    def index_session(self) -> AbstractContextManager[LudusaviIndex]: ...


class CustomManifestLoader(Protocol):
    def load_all(self) -> CustomManifestLoadResult: ...


class BuiltinRuleSuggestions(Protocol):
    def suggest_game_specific(
        self,
        game: Game,
        install_dir: Path | None,
        metadata: Mapping[str, object],
    ) -> tuple[SaveLocationSuggestion, ...]: ...

    def suggest_engine(
        self,
        game: Game,
        install_dir: Path | None,
        metadata: Mapping[str, object],
    ) -> tuple[SaveLocationSuggestion, ...]: ...


class RegistryProbe(Protocol):
    def key_exists(self, key: str) -> bool: ...


type EngineMetadataLoader = Callable[[Game, Path], Mapping[str, str]]
type ExperimentalEngineCheck = Callable[[str | None], bool]


class _EmptyBuiltinRules:
    def suggest_game_specific(
        self,
        _game: Game,
        _install_dir: Path | None,
        _metadata: Mapping[str, object],
    ) -> tuple[SaveLocationSuggestion, ...]:
        return ()

    def suggest_engine(
        self,
        _game: Game,
        _install_dir: Path | None,
        _metadata: Mapping[str, object],
    ) -> tuple[SaveLocationSuggestion, ...]:
        return ()


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
        custom_provider: CustomManifestLoader,
        engine_hints: EngineSaveHintProvider,
        builtin_rules: BuiltinRuleSuggestions | None = None,
        registry: RegistryProbe | None = None,
        engine_metadata_loader: EngineMetadataLoader | None = None,
        engine_is_experimental: ExperimentalEngineCheck | None = None,
    ) -> None:
        self._library = library
        self._save_repository = save_repository
        self._resolver = resolver
        self._ludusavi_provider = ludusavi_provider
        self._custom_provider = custom_provider
        self._builtin_rules = builtin_rules or _EmptyBuiltinRules()
        self._registry = registry or _UnavailableRegistry()
        self._engine_hints = engine_hints
        self._engine_metadata_loader = engine_metadata_loader or load_engine_metadata
        self._engine_is_experimental = engine_is_experimental or (lambda _engine: False)
        self._official_matcher: IndexedLudusaviMatcher | None = None

    def suggest_for_game(self, game_id: str) -> tuple[SaveLocationSuggestion, ...]:
        game = self._library.get_game(game_id)
        if game is None:
            raise GameNotFoundError(game_id)
        install_dir = self._library.install_directory(game_id)
        existing = {
            (_canonical_kind(location.kind, location.path_template), location.path_key)
            for location in self._save_repository.list_for_game(game_id)
        }

        candidates: list[_RankedSuggestion] = []
        custom_result = self._custom_provider.load_all()
        for loaded in custom_result.manifests:
            matches = LudusaviMatcher(loaded.manifest, self._resolver).find(game, install_dir)
            candidates.extend(
                _ranked(
                    self._manifest_suggestions(
                        matches,
                        evidence_source="custom",
                        source_detail=f"自定义清单：{loaded.source_name}",
                    ),
                    source_rank=0,
                )
            )

        try:
            builtin_game = self._builtin_rules.suggest_game_specific(game, install_dir, {})
            candidates.extend(
                _ranked(
                    tuple(_builtin_group(item, game_specific=True) for item in builtin_game),
                    source_rank=1,
                )
            )
        except Exception as error:
            logger.warning("内置游戏存档规则不可用，已跳过：%s", error)

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

        metadata = self._engine_metadata_loader(game, install_dir)
        experimental = self._engine_is_experimental(game.engine_id)
        try:
            builtin_engine = self._builtin_rules.suggest_engine(game, install_dir, metadata)
            candidates.extend(
                _ranked(
                    tuple(_builtin_group(item, game_specific=False) for item in builtin_engine),
                    source_rank=3,
                )
            )
        except Exception as error:
            logger.warning("内置引擎存档规则不可用，已跳过：%s", error)
        for suggestion in self._engine_hints.suggest(game, install_dir, metadata):
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
                    source_rank=4,
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
            if suggestion.kind == "registry":
                found = self._registry.key_exists(suggestion.path_template)
            else:
                path = self._resolver.expand(suggestion.path_template, install_dir)
                if suggestion.kind == "directory":
                    found = path.is_dir()
                elif suggestion.kind == "file":
                    found = path.is_file()
                else:
                    found = next(islice(glob.iglob(str(path)), 1), None) is not None
        except (OSError, RuntimeError, ValueError) as error:
            logger.warning("存档建议存在性检查失败，已按可能路径保留：%s", error)
            diagnostic = "存在性检查失败，已按可能路径保留"
            return replace(
                suggestion,
                availability="predicted",
                evidence=tuple(dict.fromkeys((*suggestion.evidence, diagnostic))),
            )
        return replace(suggestion, availability="found" if found else "predicted")


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


def _builtin_group(
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
