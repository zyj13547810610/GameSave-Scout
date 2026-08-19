"""Conservative identity matching and grouping for batch save candidates."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from pathlib import Path, PureWindowsPath

from rapidfuzz.fuzz import ratio

from gameshelf.library.models import Game
from gameshelf.saves.batch_candidates import candidate_path_key
from gameshelf.saves.batch_models import (
    BatchCandidateSource,
    BatchClassification,
    BatchConfidence,
    CandidateAlternative,
    MatchedBatchCandidate,
    RawBatchCandidate,
)
from gameshelf.saves.batch_rules import BatchPathRule, BatchRuleCatalog, RuleIdentity
from gameshelf.saves.ludusavi_matcher import normalize_ludusavi_name
from gameshelf.saves.models import SaveLocation
from gameshelf.scanning.path_keys import windows_path_key

_FUZZY_THRESHOLD = 0.86
_MEDIUM_THRESHOLD = 0.93
_FUZZY_WIN_MARGIN = 0.03
_TEMPLATE_PATH = re.compile(r"^(<[^<>\\/]+>)(?:[\\/](.*))?$")
_RJ_VJ_ID = re.compile(r"(?i)(?<![A-Z0-9])((?:RJ|VJ)[0-9]+)(?![A-Z0-9])")
_STEAM_USERDATA_ID = re.compile(r"(?i)(?:^|[\\/])userdata[\\/][0-9]+[\\/]([0-9]{3,10})(?:[\\/]|$)")
_STEAM_LABEL_ID = re.compile(r"(?i)(?:steam(?:app)?|app)[ _-]?id[^0-9]*([0-9]{3,10})")
_GENERIC_NAME_KEYS = frozenset(
    {
        "appdata",
        "data",
        "documents",
        "local",
        "locallow",
        "remote",
        "roaming",
        "save",
        "saved",
        "savedata",
        "savegame",
        "savegames",
        "saves",
        "slot",
        "slots",
        "steam",
        "userdata",
        "users",
    }
)
_CONFIDENCE_ORDER: dict[BatchConfidence, int] = {
    "low": 0,
    "medium": 1,
    "high": 2,
}


class BatchCandidateMatcher:
    """Apply the fixed matching priority without turning weak clues into identity."""

    def __init__(
        self,
        *,
        games: Sequence[Game],
        save_locations: Sequence[SaveLocation],
        catalog: BatchRuleCatalog,
    ) -> None:
        self._games = tuple(games)
        self._games_by_id = {game.id: game for game in self._games}
        self._locations_by_path: dict[tuple[str, str], list[SaveLocation]] = {}
        for location in save_locations:
            key = (
                location.kind,
                candidate_path_key(location.kind, location.path_key),
            )
            self._locations_by_path.setdefault(key, []).append(location)
        self._catalog = catalog
        self._reverse_rules = _index_reverse_rules(catalog.reverse_path_rules)

    def match_all(
        self,
        candidates: Sequence[RawBatchCandidate],
    ) -> tuple[MatchedBatchCandidate, ...]:
        return tuple(self._match(candidate) for candidate in candidates)

    def _match(self, candidate: RawBatchCandidate) -> MatchedBatchCandidate:
        path_identity = (
            candidate.kind,
            candidate_path_key(candidate.kind, candidate.path_key),
        )
        recorded = self._locations_by_path.get(path_identity, ())
        if recorded:
            return self._recorded_match(candidate, recorded)

        identities = self._identities(candidate, path_identity)
        game_match = self._unique_existing_game(identities)
        if game_match is not None:
            game, matching_identities = game_match
            alternatives = _identity_alternatives(
                identities,
                self._games_by_id,
                excluded_game_id=game.id,
            )
            return _build_match(
                candidate,
                classification=_classification(game),
                confidence=_best_confidence(matching_identities),
                suggested_game_id=game.id,
                suggested_title=game.title,
                external_product_id=_first_product_id(matching_identities),
                engine_id=game.engine_id or _unique_engine(identities),
                strong_group_key=f"game:{game.id}",
                alternatives=alternatives,
                extra_sources=tuple(identity.source for identity in matching_identities),
                extra_evidence=tuple(
                    evidence for identity in matching_identities for evidence in identity.evidence
                ),
            )

        external_match = self._unique_external_rule(identities)
        if external_match is not None:
            strong_key, matching_identities = external_match
            chosen = matching_identities[0]
            return _build_match(
                candidate,
                classification="unknown",
                confidence=_best_confidence(matching_identities),
                suggested_game_id=None,
                suggested_title=chosen.external_title,
                external_product_id=_first_product_id(matching_identities),
                engine_id=_unique_engine(identities) or _engine_hint(candidate),
                strong_group_key=strong_key,
                alternatives=_identity_alternatives(
                    identities,
                    self._games_by_id,
                    excluded_strong_key=strong_key,
                ),
                extra_sources=tuple(identity.source for identity in matching_identities),
                extra_evidence=tuple(
                    evidence for identity in matching_identities for evidence in identity.evidence
                ),
            )

        identity_alternatives = _identity_alternatives(
            identities,
            self._games_by_id,
        )
        product = _stable_product(candidate, identities)
        if product is not None:
            product_id, title = product
            return _build_match(
                candidate,
                classification="unknown",
                confidence="high",
                suggested_game_id=None,
                suggested_title=title,
                external_product_id=product_id,
                engine_id=_unique_engine(identities) or _engine_hint(candidate),
                strong_group_key=f"product:{product_id.casefold()}",
                alternatives=identity_alternatives,
            )

        fuzzy = (
            None
            if self._has_conflicting_existing_games(identities)
            else self._fuzzy_match(candidate, identities)
        )
        if fuzzy is not None:
            game, score, alternatives = fuzzy
            return _build_match(
                candidate,
                classification=_classification(game),
                confidence="medium" if score >= _MEDIUM_THRESHOLD else "low",
                suggested_game_id=game.id,
                suggested_title=game.title,
                external_product_id=None,
                engine_id=game.engine_id or _unique_engine(identities) or _engine_hint(candidate),
                strong_group_key=None,
                alternatives=_merge_alternatives(identity_alternatives, alternatives),
            )

        return _build_match(
            candidate,
            classification="unknown",
            confidence="low",
            suggested_game_id=None,
            suggested_title=None,
            external_product_id=None,
            engine_id=_unique_engine(identities) or _engine_hint(candidate),
            strong_group_key=None,
            alternatives=identity_alternatives,
        )

    def _recorded_match(
        self,
        candidate: RawBatchCandidate,
        locations: Sequence[SaveLocation],
    ) -> MatchedBatchCandidate:
        game_ids = tuple(dict.fromkeys(location.game_id for location in locations))
        game = self._games_by_id.get(game_ids[0]) if len(game_ids) == 1 else None
        alternatives = tuple(
            CandidateAlternative(
                title=self._games_by_id[game_id].title,
                reason="possibleSameGame",
                game_id=game_id,
            )
            for game_id in game_ids
            if game_id in self._games_by_id and (game is None or game_id != game.id)
        )
        if game is None:
            return _build_match(
                candidate,
                classification="unknown",
                confidence="high",
                suggested_game_id=None,
                suggested_title=None,
                external_product_id=None,
                engine_id=None,
                strong_group_key=None,
                alternatives=alternatives,
                extra_sources=("recorded",),
                extra_evidence=("GameShelf 已记录同类型规范路径",),
            )
        return _build_match(
            candidate,
            classification=_classification(game),
            confidence="high",
            suggested_game_id=game.id,
            suggested_title=game.title,
            external_product_id=None,
            engine_id=game.engine_id,
            strong_group_key=f"game:{game.id}",
            alternatives=alternatives,
            extra_sources=("recorded",),
            extra_evidence=("GameShelf 已记录同类型规范路径",),
        )

    def _identities(
        self,
        candidate: RawBatchCandidate,
        path_identity: tuple[str, str],
    ) -> tuple[RuleIdentity, ...]:
        result = list(self._catalog.identities_by_path.get(path_identity, ()))
        template_match = _TEMPLATE_PATH.fullmatch(candidate.path_template)
        if template_match is None:
            return tuple(dict.fromkeys(result))
        root_token, relative = template_match.groups()
        relative = (relative or "").replace("/", "\\").strip("\\")
        relative_paths = [relative] if relative else []
        if candidate.kind == "directory" and relative:
            relative_paths.extend(
                f"{relative}\\{representative.name}"
                for representative in candidate.representative_files
            )
        for relative_path in relative_paths:
            first_key = windows_path_key(relative_path.partition("\\")[0])
            rules = (
                *self._reverse_rules.get((root_token, first_key), ()),
                *self._reverse_rules.get((root_token, ""), ()),
            )
            for rule in rules:
                if PureWindowsPath(relative_path).match(rule.relative_pattern):
                    result.append(rule.identity)
        return tuple(dict.fromkeys(result))

    def _unique_existing_game(
        self,
        identities: tuple[RuleIdentity, ...],
    ) -> tuple[Game, tuple[RuleIdentity, ...]] | None:
        by_game: dict[str, list[RuleIdentity]] = {}
        for identity in identities:
            game = self._games_by_id.get(identity.game_id or "")
            if game is None or game.status == "save_only":
                continue
            by_game.setdefault(game.id, []).append(identity)
        if len(by_game) != 1:
            return None
        game_id, matching = next(iter(by_game.items()))
        return self._games_by_id[game_id], tuple(matching)

    def _unique_external_rule(
        self,
        identities: tuple[RuleIdentity, ...],
    ) -> tuple[str, tuple[RuleIdentity, ...]] | None:
        groups: dict[str, list[RuleIdentity]] = {}
        for identity in identities:
            if identity.source not in {"custom", "ludusavi"}:
                continue
            if identity.game_id is not None:
                game = self._games_by_id.get(identity.game_id)
                if game is not None:
                    continue
            strong_key = identity.strong_group_key
            if strong_key is None or strong_key.startswith("game:"):
                continue
            groups.setdefault(strong_key, []).append(identity)
        if len(groups) != 1:
            return None
        strong_key, matching = next(iter(groups.items()))
        return strong_key, tuple(matching)

    def _has_conflicting_existing_games(
        self,
        identities: tuple[RuleIdentity, ...],
    ) -> bool:
        game_ids = {
            identity.game_id
            for identity in identities
            if identity.game_id is not None
            and (game := self._games_by_id.get(identity.game_id)) is not None
            and game.status != "save_only"
        }
        return len(game_ids) > 1

    def _fuzzy_match(
        self,
        candidate: RawBatchCandidate,
        identities: tuple[RuleIdentity, ...],
    ) -> tuple[Game, float, tuple[CandidateAlternative, ...]] | None:
        signals = _candidate_name_signals(candidate, identities)
        if not signals:
            return None
        scored: list[tuple[float, Game]] = []
        for game in self._games:
            if game.status == "save_only":
                continue
            game_names = _game_names(game)
            score = max(
                (ratio(signal, game_name) / 100 for signal in signals for game_name in game_names),
                default=0.0,
            )
            if score >= _FUZZY_THRESHOLD:
                scored.append((score, game))
        scored.sort(key=lambda item: (-item[0], item[1].title.casefold(), item[1].id))
        if not scored:
            return None
        best_score, best_game = scored[0]
        if len(scored) > 1 and best_score - scored[1][0] < _FUZZY_WIN_MARGIN:
            return None
        alternatives = tuple(
            CandidateAlternative(game.title, "possibleSameGame", game.id) for _, game in scored[1:6]
        )
        return best_game, best_score, alternatives


def group_matched_candidates(
    candidates: Sequence[MatchedBatchCandidate],
) -> tuple[tuple[MatchedBatchCandidate, ...], ...]:
    """Merge only candidates that carry the same explicit strong identity."""

    groups: list[list[MatchedBatchCandidate]] = []
    positions: dict[str, int] = {}
    for candidate in candidates:
        key = candidate.strong_group_key
        if key is None:
            groups.append([candidate])
            continue
        position = positions.get(key)
        if position is None:
            positions[key] = len(groups)
            groups.append([candidate])
        else:
            groups[position].append(candidate)
    return tuple(tuple(group) for group in groups)


def _index_reverse_rules(
    rules: tuple[BatchPathRule, ...],
) -> dict[tuple[str, str], tuple[BatchPathRule, ...]]:
    grouped: dict[tuple[str, str], list[BatchPathRule]] = {}
    for rule in rules:
        if rule.kind != "file":
            continue
        grouped.setdefault((rule.root_token, rule.first_segment_key), []).append(rule)
    return {key: tuple(values) for key, values in grouped.items()}


def _stable_product(
    candidate: RawBatchCandidate,
    identities: tuple[RuleIdentity, ...],
) -> tuple[str, str | None] | None:
    identity_products = tuple(
        identity.external_product_id for identity in identities if identity.external_product_id
    )
    text_values = (
        *identity_products,
        candidate.path_template,
        candidate.display_path,
        *candidate.evidence,
        *(file.name for file in candidate.representative_files),
    )
    combined = " ".join(text_values)
    product_match = _RJ_VJ_ID.search(combined)
    if product_match is not None:
        product_id = product_match.group(1).upper()
        return product_id, _title_for_product(identities, product_id)

    normalized_path = candidate.display_path.replace("/", "\\")
    steam_match = _STEAM_USERDATA_ID.search(normalized_path) or _STEAM_LABEL_ID.search(combined)
    if steam_match is not None:
        product_id = f"steam:{steam_match.group(1)}"
        return product_id, _title_for_product(identities, product_id)

    template_match = _TEMPLATE_PATH.fullmatch(candidate.path_template)
    if template_match is not None and template_match.group(1) == "<winLocalAppDataLow>":
        parts = PureWindowsPath(template_match.group(2) or "").parts
        if len(parts) >= 2:
            company = normalize_ludusavi_name(parts[0])
            product = normalize_ludusavi_name(parts[1])
            if company and product:
                return f"unity:{company}/{product}", parts[1]

    if candidate.kind == "registry":
        registry_parts = list(PureWindowsPath(candidate.display_path).parts)
        try:
            software_index = next(
                index for index, part in enumerate(registry_parts) if part.casefold() == "software"
            )
        except StopIteration:
            return None
        suffix = [
            part
            for part in registry_parts[software_index + 1 :]
            if part.casefold() != "wow6432node"
        ]
        if len(suffix) >= 2:
            company = normalize_ludusavi_name(suffix[0])
            product = normalize_ludusavi_name(suffix[1])
            if company and product:
                return f"registry:{company}/{product}", suffix[1]
    return None


def _title_for_product(
    identities: tuple[RuleIdentity, ...],
    product_id: str,
) -> str | None:
    normalized_product = product_id.casefold()
    titles = {
        identity.external_title
        for identity in identities
        if identity.external_title
        and identity.external_product_id
        and identity.external_product_id.casefold() == normalized_product
    }
    return next(iter(titles)) if len(titles) == 1 else None


def _candidate_name_signals(
    candidate: RawBatchCandidate,
    identities: tuple[RuleIdentity, ...],
) -> tuple[str, ...]:
    raw_values: list[str] = [
        identity.external_title for identity in identities if identity.external_title is not None
    ]
    if candidate.kind != "registry":
        path_parts = PureWindowsPath(candidate.display_path).parts
        raw_values.extend(reversed(path_parts[-5:]))
    signals: list[str] = []
    for value in raw_values:
        normalized = normalize_ludusavi_name(value)
        if len(normalized) < 4 or normalized in _GENERIC_NAME_KEYS:
            continue
        if normalized not in signals:
            signals.append(normalized)
    return tuple(signals)


def _game_names(game: Game) -> tuple[str, ...]:
    values = (
        game.title,
        game.detected_title,
        game.relative_dir,
        Path(game.main_exe_relpath).stem if game.main_exe_relpath else None,
    )
    names: list[str] = []
    for value in values:
        if not value:
            continue
        normalized = normalize_ludusavi_name(value)
        if len(normalized) >= 4 and normalized not in names:
            names.append(normalized)
    return tuple(names)


def _engine_hint(candidate: RawBatchCandidate) -> str | None:
    path_key = windows_path_key(candidate.display_path)
    if "\\saved\\savegames" in path_key:
        return "unreal"
    if candidate.path_template.startswith("<winLocalAppDataLow>"):
        return "unity"
    suffixes = {
        PureWindowsPath(file.name).suffix.casefold() for file in candidate.representative_files
    }
    if ".rmmzsave" in suffixes:
        return "rpg_maker_mz"
    if ".rpgsave" in suffixes:
        return "rpg_maker_mv"
    if ".rvdata2" in suffixes:
        return "rpg_maker_vx_ace"
    if ".rvdata" in suffixes:
        return "rpg_maker_xp"
    if ".lsd" in suffixes:
        return "rpg_maker_2k"
    if "\\renpy\\" in f"\\{path_key}\\":
        return "renpy"
    return None


def _identity_alternatives(
    identities: tuple[RuleIdentity, ...],
    games_by_id: dict[str, Game],
    *,
    excluded_game_id: str | None = None,
    excluded_strong_key: str | None = None,
) -> tuple[CandidateAlternative, ...]:
    result: list[CandidateAlternative] = []
    seen: set[tuple[str, str | None]] = set()
    for identity in identities:
        if excluded_game_id is not None and identity.game_id == excluded_game_id:
            continue
        if excluded_strong_key is not None and identity.strong_group_key == excluded_strong_key:
            continue
        game = games_by_id.get(identity.game_id or "")
        title = game.title if game is not None else identity.external_title
        if not title:
            continue
        key = (title.casefold(), identity.game_id)
        if key in seen:
            continue
        seen.add(key)
        result.append(
            CandidateAlternative(
                title=title,
                reason="possibleSameGame",
                game_id=identity.game_id,
            )
        )
    return tuple(result)


def _merge_alternatives(
    *groups: Iterable[CandidateAlternative],
) -> tuple[CandidateAlternative, ...]:
    result: list[CandidateAlternative] = []
    seen: set[tuple[str, str | None]] = set()
    for alternative in (item for group in groups for item in group):
        key = (alternative.title.casefold(), alternative.game_id)
        if key in seen:
            continue
        seen.add(key)
        result.append(alternative)
    return tuple(result)


def _best_confidence(identities: Sequence[RuleIdentity]) -> BatchConfidence:
    return max(
        (identity.confidence for identity in identities),
        key=_CONFIDENCE_ORDER.__getitem__,
        default="low",
    )


def _first_product_id(identities: Sequence[RuleIdentity]) -> str | None:
    values = tuple(
        dict.fromkeys(
            identity.external_product_id for identity in identities if identity.external_product_id
        )
    )
    return values[0] if len(values) == 1 else None


def _unique_engine(identities: Sequence[RuleIdentity]) -> str | None:
    values = tuple(
        dict.fromkeys(identity.engine_id for identity in identities if identity.engine_id)
    )
    return values[0] if len(values) == 1 else None


def _classification(game: Game) -> BatchClassification:
    if game.status == "installed":
        return "installed"
    if game.status == "missing":
        return "missing"
    return "unknown"


def _build_match(
    candidate: RawBatchCandidate,
    *,
    classification: BatchClassification,
    confidence: BatchConfidence,
    suggested_game_id: str | None,
    suggested_title: str | None,
    external_product_id: str | None,
    engine_id: str | None,
    strong_group_key: str | None,
    alternatives: tuple[CandidateAlternative, ...],
    extra_sources: tuple[BatchCandidateSource, ...] = (),
    extra_evidence: tuple[str, ...] = (),
) -> MatchedBatchCandidate:
    sources = tuple(dict.fromkeys((*candidate.sources, *extra_sources)))
    evidence = tuple(dict.fromkeys((*candidate.evidence, *extra_evidence)))
    return MatchedBatchCandidate(
        scope_key=candidate.scope_key,
        kind=candidate.kind,
        path_template=candidate.path_template,
        display_path=candidate.display_path,
        path_key=candidate.path_key,
        sources=sources,
        evidence=evidence,
        representative_files=candidate.representative_files,
        matched_file_count=candidate.matched_file_count,
        representatives_truncated=candidate.representatives_truncated,
        classification=classification,
        confidence=confidence,
        suggested_game_id=suggested_game_id,
        suggested_title=suggested_title,
        external_product_id=external_product_id,
        engine_id=engine_id,
        strong_group_key=strong_group_key,
        alternatives=alternatives,
    )
