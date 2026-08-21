"""Collect explicit save rules and identities for one batch discovery run."""

from __future__ import annotations

import glob
import hashlib
import json
import re
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from itertools import islice
from pathlib import Path, PureWindowsPath
from types import MappingProxyType
from typing import Literal, Protocol

from gameshelf.library.models import Game
from gameshelf.saves.batch_candidates import (
    BatchCandidateAccumulator,
    candidate_path_key,
)
from gameshelf.saves.batch_models import (
    BatchCandidateKind,
    BatchCandidateSource,
    BatchConfidence,
    RawBatchCandidate,
)
from gameshelf.saves.custom_manifest_provider import CustomManifestLoadResult
from gameshelf.saves.engine_hints import (
    EngineSaveHintProvider,
    load_engine_metadata,
)
from gameshelf.saves.ludusavi_index import (
    IndexedName,
    IndexedPathRule,
    InvalidLudusaviIndex,
    LudusaviIndex,
)
from gameshelf.saves.ludusavi_matcher import normalize_ludusavi_name
from gameshelf.saves.ludusavi_models import (
    LudusaviManifest,
    ManifestCondition,
    ManifestLocationRule,
)
from gameshelf.saves.ludusavi_provider import SnapshotUpdateError
from gameshelf.saves.models import SaveLocation, SaveLocationSuggestion
from gameshelf.saves.templates import InvalidPathTemplate, PathTemplateResolver
from gameshelf.scanning.path_keys import windows_path_key

_FILE_RULE_PATTERN = re.compile(r"^(<[^<>\\/]+>)(?:[\\/](.*))?$")
_EMBEDDED_TOKEN = re.compile(r"<[^<>\\/]+>")
_PRODUCT_ID = re.compile(r"(?i)(?<![A-Z0-9])((?:RJ|VJ)[0-9]+)(?![A-Z0-9])")
_REGISTRY_ROOTS = {
    "HKCU": "HKEY_CURRENT_USER",
    "HKEY_CURRENT_USER": "HKEY_CURRENT_USER",
    "HKLM": "HKEY_LOCAL_MACHINE",
    "HKEY_LOCAL_MACHINE": "HKEY_LOCAL_MACHINE",
}
_SCOPE_BY_TOKEN = {
    "<winDocuments>": "documents",
    "<winSavedGames>": "saved_games",
    "<winAppData>": "app_data",
    "<winLocalAppData>": "local_app_data",
    "<winLocalAppDataLow>": "local_app_data_low",
}


@dataclass(frozen=True, slots=True)
class BatchRuleContext:
    root_tokens: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RuleIdentity:
    source: BatchCandidateSource
    game_id: str | None
    external_title: str | None
    external_product_id: str | None
    engine_id: str | None
    confidence: BatchConfidence
    strong_group_key: str | None
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BatchPathRule:
    source: BatchCandidateSource
    kind: Literal["file", "registry"]
    root_token: str
    relative_pattern: str
    first_segment_key: str
    identity: RuleIdentity


@dataclass(frozen=True, slots=True)
class BatchRuleCatalog:
    candidates: tuple[RawBatchCandidate, ...]
    identities_by_path: Mapping[
        tuple[str, str],
        tuple[RuleIdentity, ...],
    ]
    reverse_path_rules: tuple[BatchPathRule, ...]
    warnings: tuple[str, ...]
    rules_version: str


class BatchLibrary(Protocol):
    def list_games(self) -> tuple[Game, ...]: ...

    def install_directory(self, game_id: str) -> Path: ...


class BatchSaveLocations(Protocol):
    def list_all(self) -> tuple[SaveLocation, ...]: ...


class BatchLudusaviProvider(Protocol):
    def index_session(self) -> AbstractContextManager[LudusaviIndex]: ...


class BatchCustomManifestProvider(Protocol):
    def load_all(self) -> CustomManifestLoadResult: ...


class BatchRegistry(Protocol):
    def key_exists(self, key: str) -> bool: ...


class BatchBuiltinRules(Protocol):
    @property
    def rules_version(self) -> str | None: ...

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


class _EmptyBuiltinRules:
    @property
    def rules_version(self) -> str | None:
        return None

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


type AddCandidate = Callable[[RawBatchCandidate, RuleIdentity], None]


class BatchRuleProvider:
    def __init__(
        self,
        *,
        library: BatchLibrary,
        save_repository: BatchSaveLocations,
        resolver: PathTemplateResolver,
        ludusavi_provider: BatchLudusaviProvider,
        custom_provider: BatchCustomManifestProvider,
        engine_hints: EngineSaveHintProvider,
        builtin_rules: BatchBuiltinRules | None = None,
        registry: BatchRegistry,
    ) -> None:
        self._library = library
        self._save_repository = save_repository
        self._resolver = resolver
        self._ludusavi_provider = ludusavi_provider
        self._custom_provider = custom_provider
        self._engine_hints = engine_hints
        self._builtin_rules = builtin_rules or _EmptyBuiltinRules()
        self._registry = registry

    def collect(self, context: BatchRuleContext) -> BatchRuleCatalog:
        games = self._library.list_games()
        games_by_id = {game.id: game for game in games}
        local_names = _local_names(games)
        locations = self._save_repository.list_all()
        accumulator = BatchCandidateAccumulator()
        identities: dict[tuple[str, str], list[RuleIdentity]] = {}
        reverse_rules: list[BatchPathRule] = []
        warnings: list[str] = []
        version_parts: list[object] = []

        def add(candidate: RawBatchCandidate, identity: RuleIdentity) -> None:
            accumulator.add(candidate)
            key = (candidate.kind, candidate_path_key(candidate.kind, candidate.path_key))
            target = identities.setdefault(key, [])
            if identity not in target:
                target.append(identity)

        for location in locations:
            game = games_by_id.get(location.game_id)
            identity = RuleIdentity(
                source="recorded",
                game_id=location.game_id,
                external_title=game.title if game is not None else None,
                external_product_id=None,
                engine_id=game.engine_id if game is not None else None,
                confidence="high",
                strong_group_key=f"game:{location.game_id}",
                evidence=("GameShelf 已记录该存档位置", *location.evidence),
            )
            add(
                _raw_candidate(
                    scope_key=_scope_key(location.path_template),
                    kind=location.kind,
                    path_template=location.path_template,
                    display_path=location.display_path,
                    path_key=location.path_key,
                    source="recorded",
                    evidence=identity.evidence,
                ),
                identity,
            )

        try:
            custom_result = self._custom_provider.load_all()
        except (OSError, UnicodeError, ValueError) as error:
            custom_result = CustomManifestLoadResult((), ())
            warnings.append(f"无法加载自定义存档清单：{error}")
        for custom_error in custom_result.errors:
            warnings.append(f"自定义清单 {custom_error.source_name}：{custom_error.message}")
        for loaded in custom_result.manifests:
            version_parts.append(_manifest_version_part(loaded.source_name, loaded.manifest))
            self._collect_custom_manifest(
                loaded.source_name,
                loaded.manifest,
                context,
                local_names,
                add,
                reverse_rules,
            )

        official_digest = "unavailable"
        try:
            with self._ludusavi_provider.index_session() as index:
                official_digest = index.metadata.manifest_sha256
                indexed_game_matches = _indexed_game_matches(
                    index.load_names(),
                    local_names,
                )
                root_tokens = (*context.root_tokens, "HKEY_CURRENT_USER", "HKEY_LOCAL_MACHINE")
                for rule in index.load_literal_path_rules(root_tokens):
                    identity = _indexed_identity(
                        rule,
                        indexed_game_matches,
                        games_by_id,
                    )
                    path_rule = BatchPathRule(
                        source="ludusavi",
                        kind=rule.kind,
                        root_token=rule.root_token,
                        relative_pattern=rule.relative_pattern,
                        first_segment_key=rule.first_segment_key,
                        identity=identity,
                    )
                    if rule.kind == "file" and not _is_literal(rule.relative_pattern):
                        reverse_rules.append(path_rule)
                        continue
                    candidate = self._candidate_from_rule(path_rule)
                    if candidate is not None:
                        add(candidate, identity)
                matched_index_ids = {
                    indexed_game_id
                    for indexed_game_id, game_ids in indexed_game_matches.items()
                    if len(game_ids) == 1
                }
                for indexed_game_id, manifest_game in index.load_games(matched_index_ids).items():
                    game_id = indexed_game_matches[indexed_game_id][0]
                    game = games_by_id[game_id]
                    try:
                        install_dir = self._library.install_directory(game_id)
                    except (OSError, ValueError):
                        continue
                    for manifest_rule in manifest_game.files:
                        identity = RuleIdentity(
                            source="ludusavi",
                            game_id=game_id,
                            external_title=manifest_game.canonical_name,
                            external_product_id=_product_id(
                                f"{manifest_game.canonical_name} {manifest_rule.path}"
                            ),
                            engine_id=game.engine_id,
                            confidence=_rule_confidence(manifest_rule.conditions),
                            strong_group_key=f"game:{game_id}",
                            evidence=(
                                f"Ludusavi 游戏目录规则：{manifest_game.canonical_name}",
                                *_condition_evidence(manifest_rule.conditions),
                            ),
                        )
                        candidate = self._candidate_from_install_rule(
                            manifest_rule,
                            install_dir,
                            "ludusavi",
                            identity,
                        )
                        if candidate is not None:
                            add(candidate, identity)
        except (InvalidLudusaviIndex, SnapshotUpdateError, OSError, ValueError) as error:
            warnings.append(f"Ludusavi 规则不可用：{error}")
        version_parts.append(("ludusavi", official_digest))
        version_parts.append(("builtin", self._builtin_rules.rules_version))

        for game in games:
            if game.status != "installed":
                continue
            try:
                install_dir = self._library.install_directory(game.id)
            except (OSError, ValueError):
                continue
            metadata = load_engine_metadata(game, install_dir)
            try:
                builtin_suggestions = (
                    *self._builtin_rules.suggest_game_specific(
                        game,
                        install_dir,
                        metadata,
                    ),
                    *self._builtin_rules.suggest_engine(
                        game,
                        install_dir,
                        metadata,
                    ),
                )
            except Exception as error:
                warnings.append(f"内置存档规则不可用：{error}")
                builtin_suggestions = ()
            for suggestion in builtin_suggestions:
                found_suggestion = self._with_availability(suggestion, install_dir)
                if found_suggestion.availability != "found":
                    continue
                identity = RuleIdentity(
                    source="builtin",
                    game_id=game.id,
                    external_title=game.title,
                    external_product_id=_product_id(found_suggestion.display_path),
                    engine_id=game.engine_id,
                    confidence=(
                        "high" if found_suggestion.confidence >= 0.9 else "medium"
                    ),
                    strong_group_key=f"game:{game.id}",
                    evidence=found_suggestion.evidence,
                )
                add(
                    _raw_candidate(
                        scope_key=_scope_key(found_suggestion.path_template),
                        kind=found_suggestion.kind,
                        path_template=found_suggestion.path_template,
                        display_path=found_suggestion.display_path,
                        path_key=candidate_path_key(
                            found_suggestion.kind,
                            found_suggestion.display_path,
                        ),
                        source="builtin",
                        evidence=found_suggestion.evidence,
                    ),
                    identity,
                )
            for suggestion in self._engine_hints.suggest(game, install_dir, metadata):
                if suggestion.kind == "registry":
                    if not self._registry.key_exists(suggestion.path_template):
                        continue
                    path_key = candidate_path_key("registry", suggestion.path_template)
                else:
                    if suggestion.kind != "glob" and not Path(suggestion.display_path).exists():
                        continue
                    path_key = candidate_path_key(
                        suggestion.kind,
                        suggestion.display_path,
                    )
                identity = RuleIdentity(
                    source="engine",
                    game_id=game.id,
                    external_title=game.title,
                    external_product_id=_product_id(suggestion.display_path),
                    engine_id=game.engine_id,
                    confidence=("high" if suggestion.confidence >= 0.9 else "medium"),
                    strong_group_key=f"game:{game.id}",
                    evidence=suggestion.evidence,
                )
                add(
                    _raw_candidate(
                        scope_key=_scope_key(suggestion.path_template),
                        kind=suggestion.kind,
                        path_template=suggestion.path_template,
                        display_path=suggestion.display_path,
                        path_key=path_key,
                        source="engine",
                        evidence=suggestion.evidence,
                    ),
                    identity,
                )
            version_parts.append((game.id, game.engine_id, game.engine_rules_version))

        rules_version = hashlib.sha256(
            json.dumps(
                version_parts,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return BatchRuleCatalog(
            candidates=accumulator.snapshot(),
            identities_by_path=MappingProxyType(
                {key: tuple(value) for key, value in identities.items()}
            ),
            reverse_path_rules=tuple(reverse_rules),
            warnings=tuple(warnings),
            rules_version=rules_version,
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
        except (OSError, RuntimeError, ValueError):
            found = False
        return replace(suggestion, availability="found" if found else "predicted")

    def _collect_custom_manifest(
        self,
        source_name: str,
        manifest: LudusaviManifest,
        context: BatchRuleContext,
        local_names: Mapping[str, tuple[str, ...]],
        add: AddCandidate,
        reverse_rules: list[BatchPathRule],
    ) -> None:
        aliases = _custom_aliases(manifest)
        for canonical_name, game in manifest.games.items():
            if game.alias is not None:
                continue
            matching_game_ids = {
                game_id
                for name in (
                    canonical_name,
                    *game.install_dirs,
                    *aliases.get(canonical_name, ()),
                )
                for game_id in local_names.get(normalize_ludusavi_name(name), ())
            }
            game_id = next(iter(matching_game_ids)) if len(matching_game_ids) == 1 else None
            for kind, rules in (("file", game.files), ("registry", game.registry)):
                for rule in rules:
                    parts = _manifest_path_parts(kind, rule.path)
                    if parts is None or not _supports_windows(rule.conditions):
                        continue
                    root_token, relative_pattern = parts
                    if kind == "file" and root_token not in context.root_tokens:
                        continue
                    identity = RuleIdentity(
                        source="custom",
                        game_id=game_id,
                        external_title=canonical_name,
                        external_product_id=_product_id(f"{canonical_name} {relative_pattern}"),
                        engine_id=None,
                        confidence=_rule_confidence(rule.conditions),
                        strong_group_key=(
                            f"game:{game_id}"
                            if game_id is not None
                            else "custom:"
                            f"{source_name.casefold()}:"
                            f"{normalize_ludusavi_name(canonical_name)}"
                        ),
                        evidence=(
                            f"自定义清单 {source_name}：{canonical_name}",
                            *_condition_evidence(rule.conditions),
                        ),
                    )
                    path_rule = BatchPathRule(
                        source="custom",
                        kind=kind,  # type: ignore[arg-type]
                        root_token=root_token,
                        relative_pattern=relative_pattern,
                        first_segment_key=_first_segment_key(relative_pattern),
                        identity=identity,
                    )
                    if kind == "file" and not _is_literal(relative_pattern):
                        reverse_rules.append(path_rule)
                        continue
                    candidate = self._candidate_from_rule(path_rule)
                    if candidate is not None:
                        add(candidate, identity)
            if game_id is None:
                continue
            try:
                install_dir = self._library.install_directory(game_id)
            except (OSError, ValueError):
                continue
            for rule in game.files:
                identity = RuleIdentity(
                    source="custom",
                    game_id=game_id,
                    external_title=canonical_name,
                    external_product_id=_product_id(f"{canonical_name} {rule.path}"),
                    engine_id=None,
                    confidence=_rule_confidence(rule.conditions),
                    strong_group_key=f"game:{game_id}",
                    evidence=(
                        f"自定义清单 {source_name} 的游戏目录规则：{canonical_name}",
                        *_condition_evidence(rule.conditions),
                    ),
                )
                candidate = self._candidate_from_install_rule(
                    rule,
                    install_dir,
                    "custom",
                    identity,
                )
                if candidate is not None:
                    add(candidate, identity)

    def _candidate_from_install_rule(
        self,
        rule: ManifestLocationRule,
        install_dir: Path,
        source: BatchCandidateSource,
        identity: RuleIdentity,
    ) -> RawBatchCandidate | None:
        match = _FILE_RULE_PATTERN.fullmatch(rule.path)
        if match is None or match.group(1) not in {"<base>", "<game>"}:
            return None
        relative = (match.group(2) or "").replace("/", "\\")
        if not _is_literal(relative) or not _supports_windows(rule.conditions):
            return None
        parts = PureWindowsPath(relative).parts
        if any(part in {"..", "\\", "/"} for part in parts):
            return None
        path = install_dir.joinpath(*parts)
        if path.is_dir():
            kind: BatchCandidateKind = "directory"
        elif path.is_file():
            kind = "file"
        else:
            return None
        try:
            path_template = self._resolver.collapse(path, install_dir)
        except InvalidPathTemplate:
            return None
        return _raw_candidate(
            scope_key="rules",
            kind=kind,
            path_template=path_template,
            display_path=str(path),
            path_key=windows_path_key(path),
            source=source,
            evidence=identity.evidence,
        )

    def _candidate_from_rule(
        self,
        rule: BatchPathRule,
    ) -> RawBatchCandidate | None:
        if rule.kind == "registry":
            registry_path = f"{rule.root_token}\\{rule.relative_pattern}"
            if not _is_literal(rule.relative_pattern) or not self._registry.key_exists(
                registry_path
            ):
                return None
            return _raw_candidate(
                scope_key="registry",
                kind="registry",
                path_template=registry_path,
                display_path=registry_path,
                path_key=candidate_path_key("registry", registry_path),
                source=rule.source,
                evidence=rule.identity.evidence,
            )
        template = (
            rule.root_token
            if not rule.relative_pattern
            else f"{rule.root_token}\\{rule.relative_pattern}"
        )
        try:
            file_path = self._resolver.expand(template, None)
        except InvalidPathTemplate:
            return None
        if file_path.is_dir():
            kind: BatchCandidateKind = "directory"
        elif file_path.is_file():
            kind = "file"
        else:
            return None
        return _raw_candidate(
            scope_key=_scope_key(template),
            kind=kind,
            path_template=template,
            display_path=str(file_path),
            path_key=windows_path_key(file_path),
            source=rule.source,
            evidence=rule.identity.evidence,
        )


def _raw_candidate(
    *,
    scope_key: str,
    kind: BatchCandidateKind,
    path_template: str,
    display_path: str,
    path_key: str,
    source: BatchCandidateSource,
    evidence: tuple[str, ...],
) -> RawBatchCandidate:
    return RawBatchCandidate(
        scope_key=scope_key,
        kind=kind,
        path_template=path_template,
        display_path=display_path,
        path_key=path_key,
        sources=(source,),
        evidence=evidence,
        representative_files=(),
        matched_file_count=0,
        representatives_truncated=False,
    )


def _indexed_identity(
    rule: IndexedPathRule,
    matches: Mapping[int, tuple[str, ...]],
    games_by_id: Mapping[str, Game],
) -> RuleIdentity:
    game_ids = matches.get(rule.game_id, ())
    game_id = game_ids[0] if len(game_ids) == 1 else None
    game = games_by_id.get(game_id) if game_id is not None else None
    evidence = (
        f"Ludusavi 路径规则：{rule.canonical_name}",
        *_condition_evidence(rule.conditions),
    )
    return RuleIdentity(
        source="ludusavi",
        game_id=game_id,
        external_title=rule.canonical_name,
        external_product_id=_product_id(f"{rule.canonical_name} {rule.relative_pattern}"),
        engine_id=game.engine_id if game is not None else None,
        confidence=_rule_confidence(rule.conditions),
        strong_group_key=(f"game:{game_id}" if game_id is not None else f"ludusavi:{rule.game_id}"),
        evidence=evidence,
    )


def _local_names(games: tuple[Game, ...]) -> Mapping[str, tuple[str, ...]]:
    result: dict[str, list[str]] = {}
    for game in games:
        values = (
            game.title,
            game.detected_title,
            game.relative_dir,
            Path(game.main_exe_relpath).stem if game.main_exe_relpath else None,
        )
        for value in values:
            if not value:
                continue
            key = normalize_ludusavi_name(value)
            if key and game.id not in result.setdefault(key, []):
                result[key].append(game.id)
    return MappingProxyType({key: tuple(value) for key, value in result.items()})


def _indexed_game_matches(
    names: tuple[IndexedName, ...],
    local_names: Mapping[str, tuple[str, ...]],
) -> Mapping[int, tuple[str, ...]]:
    matches: dict[int, list[str]] = {}
    for name in names:
        for game_id in local_names.get(name.normalized_name, ()):
            target = matches.setdefault(name.game_id, [])
            if game_id not in target:
                target.append(game_id)
    return MappingProxyType({key: tuple(value) for key, value in matches.items()})


def _manifest_path_parts(kind: str, value: str) -> tuple[str, str] | None:
    if kind == "file":
        match = _FILE_RULE_PATTERN.fullmatch(value)
        if match is None:
            return None
        root, relative = match.groups()
        return root, (relative or "").replace("/", "\\").strip("\\")
    clean = value.replace("/", "\\").strip("\\")
    root, separator, relative = clean.partition("\\")
    canonical_root = _REGISTRY_ROOTS.get(root.upper())
    if canonical_root is None or not separator or not relative:
        return None
    return canonical_root, relative


def _is_literal(value: str) -> bool:
    return not any(character in value for character in "*?[") and not bool(
        _EMBEDDED_TOKEN.search(value)
    )


def _first_segment_key(value: str) -> str:
    segment = value.partition("\\")[0]
    return "" if not _is_literal(segment) else windows_path_key(segment)


def _supports_windows(conditions: tuple[ManifestCondition, ...]) -> bool:
    return not conditions or any(
        condition.os is None or condition.os.casefold() == "windows" for condition in conditions
    )


def _rule_confidence(
    conditions: tuple[ManifestCondition, ...],
) -> BatchConfidence:
    return "medium" if any(condition.store for condition in conditions) else "high"


def _condition_evidence(
    conditions: tuple[ManifestCondition, ...],
) -> tuple[str, ...]:
    result: list[str] = []
    for condition in conditions:
        if condition.os:
            result.append(f"规则系统条件：{condition.os}")
        if condition.store:
            result.append(f"规则商店条件：{condition.store}")
    return tuple(result)


def _custom_aliases(manifest: LudusaviManifest) -> Mapping[str, tuple[str, ...]]:
    result: dict[str, list[str]] = {}
    for name, game in manifest.games.items():
        if game.alias is None:
            continue
        current = game.alias
        for _ in range(8):
            target = manifest.games[current].alias
            if target is None:
                result.setdefault(current, []).append(name)
                break
            current = target
    return MappingProxyType({key: tuple(value) for key, value in result.items()})


def _manifest_version_part(source: str, manifest: LudusaviManifest) -> object:
    return (
        source,
        tuple(
            (
                name,
                tuple(rule.path for rule in game.files),
                tuple(rule.path for rule in game.registry),
                game.alias,
            )
            for name, game in manifest.games.items()
        ),
    )


def _scope_key(path_template: str) -> str:
    token = path_template.replace("/", "\\").partition("\\")[0]
    return _SCOPE_BY_TOKEN.get(token, "registry" if token.startswith("HKEY_") else "recorded")


def _product_id(value: str) -> str | None:
    match = _PRODUCT_ID.search(value)
    return None if match is None else match.group(1).upper()
