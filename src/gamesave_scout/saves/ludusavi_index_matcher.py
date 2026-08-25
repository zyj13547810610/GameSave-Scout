"""Match local games against the derived Ludusavi SQLite name catalog."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rapidfuzz import fuzz, process

from gamesave_scout.library.models import Game
from gamesave_scout.saves.ludusavi_index import IndexedName, LudusaviIndex
from gamesave_scout.saves.ludusavi_matcher import (
    ludusavi_game_signals,
    materialize_manifest_locations,
    normalize_ludusavi_name,
)
from gamesave_scout.saves.ludusavi_models import ManifestMatch
from gamesave_scout.saves.templates import PathTemplateResolver

_FUZZY_SCORE_CUTOFF = 86.0


@dataclass(frozen=True, slots=True)
class _NameMatch:
    candidate: IndexedName
    confidence: float
    signal_order: int
    signal_kind: str
    signal: str
    catalog_order: int


class IndexedLudusaviMatcher:
    """Resolve names in memory, then load rules only for selected game IDs."""

    def __init__(
        self,
        index: LudusaviIndex,
        resolver: PathTemplateResolver,
    ) -> None:
        self._index = index
        self._resolver = resolver
        self._names = index.load_names()
        exact_names: dict[str, list[tuple[int, IndexedName]]] = {}
        for catalog_order, candidate in enumerate(self._names):
            exact_names.setdefault(candidate.normalized_name, []).append(
                (catalog_order, candidate)
            )
        self._exact_names = {
            normalized_name: tuple(candidates)
            for normalized_name, candidates in exact_names.items()
        }
        self._fuzzy_choices = tuple(
            candidate.normalized_name for candidate in self._names
        )

    @property
    def manifest_sha256(self) -> str:
        return self._index.metadata.manifest_sha256

    def find(self, game: Game, install_dir: Path) -> tuple[ManifestMatch, ...]:
        signals = ludusavi_game_signals(game, install_dir)
        exact = self._find_exact(signals)
        if exact:
            return self._materialize(exact, install_dir, confirmed=True)

        fuzzy = self._find_fuzzy(signals)
        if not fuzzy:
            return ()
        return self._materialize(fuzzy, install_dir, confirmed=False)

    def _find_exact(
        self,
        signals: tuple[tuple[str, str], ...],
    ) -> dict[int, _NameMatch]:
        selected: dict[int, _NameMatch] = {}
        for signal_order, (signal_kind, signal) in enumerate(signals):
            normalized_signal = normalize_ludusavi_name(signal)
            for catalog_order, candidate in self._exact_names.get(
                normalized_signal,
                (),
            ):
                selected.setdefault(
                    candidate.game_id,
                    _NameMatch(
                        candidate=candidate,
                        confidence=1.0,
                        signal_order=signal_order,
                        signal_kind=signal_kind,
                        signal=signal,
                        catalog_order=catalog_order,
                    ),
                )
        return selected

    def _find_fuzzy(
        self,
        signals: tuple[tuple[str, str], ...],
    ) -> dict[int, _NameMatch]:
        selected: dict[int, _NameMatch] = {}
        for signal_order, (signal_kind, signal) in enumerate(signals):
            normalized_signal = normalize_ludusavi_name(signal)
            results = process.extract(
                normalized_signal,
                self._fuzzy_choices,
                scorer=fuzz.ratio,
                score_cutoff=_FUZZY_SCORE_CUTOFF,
                limit=None,
            )
            for _choice, score, catalog_order in results:
                candidate = self._names[catalog_order]
                match = _NameMatch(
                    candidate=candidate,
                    confidence=round(score / 100, 4),
                    signal_order=signal_order,
                    signal_kind=signal_kind,
                    signal=signal,
                    catalog_order=catalog_order,
                )
                current = selected.get(candidate.game_id)
                if current is None or _match_priority(match) > _match_priority(current):
                    selected[candidate.game_id] = match
        return selected

    def _materialize(
        self,
        selected: dict[int, _NameMatch],
        install_dir: Path,
        *,
        confirmed: bool,
    ) -> tuple[ManifestMatch, ...]:
        games = self._index.load_games(selected.keys())
        matches: list[ManifestMatch] = []
        for game_id, name_match in selected.items():
            manifest_game = games[game_id]
            locations = materialize_manifest_locations(
                manifest_game,
                install_dir,
                self._resolver,
            )
            if not locations:
                continue
            if confirmed:
                evidence = (
                    f"{name_match.signal_kind}精确匹配：{name_match.signal}",
                )
            else:
                evidence = (
                    "名称相似："
                    f"{name_match.signal} ↔ {name_match.candidate.display_name}",
                )
            matches.append(
                ManifestMatch(
                    canonical_name=manifest_game.canonical_name,
                    confidence=name_match.confidence,
                    confirmed=confirmed,
                    matched_name=name_match.candidate.display_name,
                    evidence=evidence,
                    locations=locations,
                )
            )
        return tuple(
            sorted(
                matches,
                key=lambda item: (-item.confidence, item.canonical_name.casefold()),
            )
        )


def _match_priority(match: _NameMatch) -> tuple[float, int, int, int]:
    return (
        match.confidence,
        -match.signal_order,
        -match.candidate.candidate_order,
        -match.catalog_order,
    )
