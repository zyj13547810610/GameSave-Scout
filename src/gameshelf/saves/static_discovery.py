"""Merge custom, Ludusavi, and engine save hints without persisting them."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Protocol

from gameshelf.engines.bounded_reader import read_text_limit
from gameshelf.library.models import Game
from gameshelf.library.service import GameNotFoundError, LibraryService
from gameshelf.saves.custom_manifest_provider import CustomManifestLoadResult
from gameshelf.saves.engine_hints import EngineSaveHintProvider
from gameshelf.saves.ludusavi_matcher import LudusaviMatcher
from gameshelf.saves.ludusavi_models import LudusaviManifest, ManifestMatch
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


class LudusaviManifestProvider(Protocol):
    def load(self) -> LudusaviManifest: ...


class CustomManifestLoader(Protocol):
    def load_all(self) -> CustomManifestLoadResult: ...


type EngineMetadataLoader = Callable[[Game, Path], Mapping[str, str]]
type ExperimentalEngineCheck = Callable[[str | None], bool]


class StaticSaveDiscovery:
    def __init__(
        self,
        *,
        library: LibraryService,
        save_repository: SaveLocationRepository,
        resolver: PathTemplateResolver,
        ludusavi_provider: LudusaviManifestProvider,
        custom_provider: CustomManifestLoader,
        engine_hints: EngineSaveHintProvider,
        engine_metadata_loader: EngineMetadataLoader | None = None,
        engine_is_experimental: ExperimentalEngineCheck | None = None,
    ) -> None:
        self._library = library
        self._save_repository = save_repository
        self._resolver = resolver
        self._ludusavi_provider = ludusavi_provider
        self._custom_provider = custom_provider
        self._engine_hints = engine_hints
        self._engine_metadata_loader = engine_metadata_loader or _load_engine_metadata
        self._engine_is_experimental = engine_is_experimental or (lambda _engine: False)
        self._official_manifest: LudusaviManifest | None = None

    def suggest_for_game(self, game_id: str) -> tuple[SaveLocationSuggestion, ...]:
        game = self._library.get_game(game_id)
        if game is None:
            raise GameNotFoundError(game_id)
        install_dir = self._library.install_directory(game_id)
        existing = {
            (_canonical_kind(location.kind, location.path_template), location.path_key)
            for location in self._save_repository.list_for_game(game_id)
        }

        candidates: list[SaveLocationSuggestion] = []
        custom_result = self._custom_provider.load_all()
        for loaded in custom_result.manifests:
            matches = LudusaviMatcher(loaded.manifest, self._resolver).find(
                game, install_dir
            )
            candidates.extend(
                self._manifest_suggestions(
                    matches,
                    evidence_source="custom",
                    source_detail=f"自定义清单：{loaded.source_name}",
                )
            )

        try:
            if self._official_manifest is None:
                self._official_manifest = self._ludusavi_provider.load()
            official_matches = LudusaviMatcher(
                self._official_manifest,
                self._resolver,
            ).find(game, install_dir)
            candidates.extend(
                self._manifest_suggestions(
                    official_matches,
                    evidence_source="ludusavi",
                    source_detail="Ludusavi 官方清单",
                )
            )
        except (SnapshotUpdateError, OSError) as error:
            logger.warning("Ludusavi 官方清单不可用，已跳过：%s", error)

        metadata = self._engine_metadata_loader(game, install_dir)
        experimental = self._engine_is_experimental(game.engine_id)
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
                replace(
                    suggestion,
                    source_evidence=source_evidence,
                    preselected=(
                        group == "exact"
                        and suggestion.kind != "registry"
                        and suggestion.confidence >= 0.9
                    ),
                    category="save",
                    group=group,
                )
            )

        merged: dict[tuple[str, str], SaveLocationSuggestion] = {}
        for suggestion in candidates:
            key = self._suggestion_key(suggestion, install_dir)
            if key is None or key in existing:
                continue
            previous = merged.get(key)
            merged[key] = suggestion if previous is None else _merge(previous, suggestion)

        finalized: list[SaveLocationSuggestion] = []
        for key, suggestion in merged.items():
            preselected = (
                suggestion.preselected
                and suggestion.confidence >= 0.9
                and suggestion.category == "save"
                and suggestion.kind != "registry"
                and suggestion.group == "exact"
            )
            suggestion_id = hashlib.sha256(
                f"{key[0]}\0{key[1]}".encode()
            ).hexdigest()[:20]
            finalized.append(
                replace(
                    suggestion,
                    suggestion_id=suggestion_id,
                    preselected=preselected,
                )
            )
        group_rank = {"exact": 0, "possible": 1, "experimental": 2}
        return tuple(
            sorted(
                finalized,
                key=lambda item: (
                    group_rank[item.group],
                    -item.confidence,
                    item.display_path.casefold(),
                ),
            )
        )

    def invalidate_ludusavi(self) -> None:
        self._official_manifest = None

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


def _merge(
    first: SaveLocationSuggestion,
    second: SaveLocationSuggestion,
) -> SaveLocationSuggestion:
    strongest = second if second.confidence > first.confidence else first
    evidence = tuple(dict.fromkeys((*first.evidence, *second.evidence)))
    source_evidence = tuple(
        {
            (item.source, item.detail): item
            for item in (*first.source_evidence, *second.source_evidence)
        }.values()
    )
    category: SuggestionCategory = (
        "save"
        if "save" in {first.category, second.category}
        else "config"
        if "config" in {first.category, second.category}
        else "other"
    )
    group = _stronger_group(first.group, second.group)
    concrete_kind = next(
        (item.kind for item in (first, second) if item.kind != "glob"),
        strongest.kind,
    )
    return replace(
        strongest,
        kind=concrete_kind,
        confidence=max(first.confidence, second.confidence),
        evidence=evidence,
        source_evidence=source_evidence,
        preselected=first.preselected or second.preselected,
        category=category,
        group=group,
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


def _load_engine_metadata(game: Game, install_dir: Path) -> Mapping[str, str]:
    if game.engine_id != "unity":
        return {}
    candidates: list[Path] = []
    if game.main_exe_relpath:
        candidates.append(
            install_dir / f"{Path(game.main_exe_relpath).stem}_Data" / "app.info"
        )
    candidates.extend(sorted(install_dir.glob("*_Data/app.info")))
    for candidate in dict.fromkeys(candidates):
        if not candidate.is_file():
            continue
        try:
            lines = [line.strip() for line in read_text_limit(candidate).splitlines()]
        except OSError:
            continue
        if len(lines) >= 2 and lines[0] and lines[1]:
            return {"companyName": lines[0], "productName": lines[1]}
    return {}
