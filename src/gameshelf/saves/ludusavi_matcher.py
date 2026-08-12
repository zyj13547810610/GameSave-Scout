"""Match local games to parsed Ludusavi entries without platform assumptions."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from pathlib import Path, PureWindowsPath

from rapidfuzz.fuzz import ratio

from gameshelf.library.models import Game
from gameshelf.saves.ludusavi_models import (
    LudusaviManifest,
    ManifestGame,
    ManifestLocationRule,
    ManifestMatch,
    MatchedLocation,
    MatchLocationCategory,
)
from gameshelf.saves.templates import InvalidPathTemplate, PathTemplateResolver

_TOKEN_PATTERN = re.compile(r"^(<[^<>\\/]+>)(?:[\\/](.*))?$")
_DIRECT_INSTALL_TOKENS = {"<base>", "<game>"}
_UNSUPPORTED_CONTEXT_TOKENS = {
    "<root>",
    "<storeGameId>",
    "<storeUserId>",
    "<osUserName>",
    "<xdgData>",
    "<xdgConfig>",
}
_FUZZY_THRESHOLD = 0.86


class LudusaviMatcher:
    def __init__(
        self,
        manifest: LudusaviManifest,
        resolver: PathTemplateResolver,
    ) -> None:
        self._manifest = manifest
        self._resolver = resolver
        self._aliases = self._aliases_by_canonical()

    def find(self, game: Game, install_dir: Path) -> tuple[ManifestMatch, ...]:
        matches: list[ManifestMatch] = []
        signals = self._game_signals(game, install_dir)
        for manifest_game in self._manifest.games.values():
            if manifest_game.alias is not None:
                continue
            scored = self._score(manifest_game, signals)
            if scored is None:
                continue
            confidence, matched_name, exact, evidence = scored
            locations = self._locations(manifest_game, install_dir)
            if not locations:
                continue
            matches.append(
                ManifestMatch(
                    canonical_name=manifest_game.canonical_name,
                    confidence=confidence,
                    confirmed=exact,
                    matched_name=matched_name,
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

    def _score(
        self,
        manifest_game: ManifestGame,
        signals: tuple[tuple[str, str], ...],
    ) -> tuple[float, str, bool, tuple[str, ...]] | None:
        candidate_names = (
            manifest_game.canonical_name,
            *manifest_game.install_dirs,
            *self._aliases.get(manifest_game.canonical_name, ()),
        )
        for signal_kind, signal in signals:
            for candidate in candidate_names:
                if _normalize_name(signal) == _normalize_name(candidate):
                    return (
                        1.0,
                        candidate,
                        True,
                        (f"{signal_kind}精确匹配：{signal}",),
                    )

        best_score = 0.0
        best_signal = ""
        best_candidate = ""
        for _, signal in signals:
            for candidate in candidate_names:
                score = ratio(_normalize_name(signal), _normalize_name(candidate)) / 100
                if score > best_score:
                    best_score = score
                    best_signal = signal
                    best_candidate = candidate
        if best_score < _FUZZY_THRESHOLD:
            return None
        return (
            round(best_score, 4),
            best_candidate,
            False,
            (f"名称相似：{best_signal} ↔ {best_candidate}",),
        )

    def _locations(
        self,
        game: ManifestGame,
        install_dir: Path,
    ) -> tuple[MatchedLocation, ...]:
        locations: list[MatchedLocation] = []
        for rule in game.files:
            location = self._file_location(rule, install_dir)
            if location is not None:
                locations.append(location)
        for rule in game.registry:
            locations.append(self._registry_location(rule))
        return tuple(locations)

    def _file_location(
        self,
        rule: ManifestLocationRule,
        install_dir: Path,
    ) -> MatchedLocation | None:
        match = _TOKEN_PATTERN.fullmatch(rule.path)
        if match is None:
            return None
        token, suffix = match.groups()
        if token in _UNSUPPORTED_CONTEXT_TOKENS:
            return None
        try:
            if token in _DIRECT_INSTALL_TOKENS:
                path = install_dir
                if suffix:
                    path = path.joinpath(*PureWindowsPath(suffix).parts)
            else:
                portable_input = token if not suffix else f"{token}\\{suffix}"
                path = self._resolver.expand(portable_input, install_dir)
            path_template = self._resolver.collapse(path, install_dir)
        except InvalidPathTemplate:
            return None
        category = _category(rule.tags)
        evidence = _condition_evidence(rule)
        preselected = category == "save" and not any(
            condition.store for condition in rule.conditions
        )
        return MatchedLocation(
            kind="glob",
            path_template=path_template,
            display_path=str(path),
            category=category,
            preselected=preselected,
            tags=rule.tags,
            evidence=evidence,
        )

    @staticmethod
    def _registry_location(rule: ManifestLocationRule) -> MatchedLocation:
        display_path = rule.path.replace("/", "\\")
        category = _category(rule.tags)
        evidence = _condition_evidence(rule)
        return MatchedLocation(
            kind="registry",
            path_template=display_path,
            display_path=display_path,
            category=category,
            preselected=category == "save" and not any(
                condition.store for condition in rule.conditions
            ),
            tags=rule.tags,
            evidence=evidence,
        )

    def _aliases_by_canonical(self) -> dict[str, tuple[str, ...]]:
        aliases: dict[str, list[str]] = {}
        for name, game in self._manifest.games.items():
            if game.alias is None:
                continue
            canonical = self._resolve_alias(name)
            aliases.setdefault(canonical, []).append(name)
        return {key: tuple(values) for key, values in aliases.items()}

    def _resolve_alias(self, name: str) -> str:
        current = name
        for _ in range(8):
            target = self._manifest.games[current].alias
            if target is None:
                return current
            current = target
        return current

    @staticmethod
    def _game_signals(game: Game, install_dir: Path) -> tuple[tuple[str, str], ...]:
        values: list[tuple[str, str | None]] = [
            ("安装目录", install_dir.name),
            ("检测标题", game.detected_title),
            ("显示标题", game.title),
            (
                "主程序",
                Path(game.main_exe_relpath).stem if game.main_exe_relpath else None,
            ),
        ]
        seen: set[str] = set()
        result: list[tuple[str, str]] = []
        for label, value in values:
            if value is None or not value.strip():
                continue
            key = _normalize_name(value)
            if key in seen:
                continue
            seen.add(key)
            result.append((label, value))
        return tuple(result)


def _normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _category(tags: frozenset[str]) -> MatchLocationCategory:
    if not tags or "save" in tags:
        return "save"
    if "config" in tags:
        return "config"
    return "other"


def _condition_evidence(rule: ManifestLocationRule) -> tuple[str, ...]:
    evidence: list[str] = []
    for condition in rule.conditions:
        if condition.os:
            evidence.append(f"适用系统：{condition.os}")
        if condition.store:
            evidence.append(f"需要平台：{condition.store}")
    return _deduplicate(evidence)


def _deduplicate(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))
