"""Collect explicit save rules and identities for one batch discovery run."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from pathlib import Path, PureWindowsPath
from types import MappingProxyType
from typing import Literal, Protocol

from gameshelf.library.models import Game
from gameshelf.rules.catalog import RuleSnapshot
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
from gameshelf.saves.ludusavi_models import ManifestCondition, ManifestLocationRule
from gameshelf.saves.ludusavi_provider import SnapshotUpdateError
from gameshelf.saves.models import SaveLocation, SaveLocationSuggestion
from gameshelf.saves.rule_identity import collect_rule_identity
from gameshelf.saves.rule_probe import BoundedRuleProbe
from gameshelf.saves.templates import InvalidPathTemplate, PathTemplateResolver
from gameshelf.scanning.path_keys import windows_path_key

_FILE_RULE_PATTERN = re.compile(r"^(<[^<>\\/]+>)(?:[\\/](.*))?$")
_EMBEDDED_TOKEN = re.compile(r"<[^<>\\/]+>")
_PRODUCT_ID = re.compile(r"(?i)(?<![A-Z0-9])((?:RJ|VJ)[0-9]+)(?![A-Z0-9])")
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


class BatchRegistry(Protocol):
    def key_exists(self, key: str) -> bool: ...


type AddCandidate = Callable[[RawBatchCandidate, RuleIdentity], None]
type RuleSnapshotProvider = Callable[[], RuleSnapshot]


class BatchRuleProvider:
    def __init__(
        self,
        *,
        library: BatchLibrary,
        save_repository: BatchSaveLocations,
        resolver: PathTemplateResolver,
        ludusavi_provider: BatchLudusaviProvider,
        engine_hints: EngineSaveHintProvider,
        rule_snapshot_provider: RuleSnapshotProvider,
        registry: BatchRegistry,
        rule_probe: BoundedRuleProbe | None = None,
    ) -> None:
        self._library = library
        self._save_repository = save_repository
        self._resolver = resolver
        self._ludusavi_provider = ludusavi_provider
        self._engine_hints = engine_hints
        self._rule_snapshot_provider = rule_snapshot_provider
        self._registry = registry
        self._rule_probe = rule_probe or BoundedRuleProbe(resolver, registry)

    def collect(self, context: BatchRuleContext) -> BatchRuleCatalog:
        snapshot = self._rule_snapshot_provider()
        games = self._library.list_games()
        games_by_id = {game.id: game for game in games}
        local_names = _local_names(games)
        locations = self._save_repository.list_all()
        accumulator = BatchCandidateAccumulator()
        identities: dict[tuple[str, str], list[RuleIdentity]] = {}
        reverse_rules: list[BatchPathRule] = []
        warnings: list[str] = []
        version_parts: list[object] = [("catalog", snapshot.catalog_version)]

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

        locations_by_game: dict[str, list[SaveLocation]] = {}
        for location in locations:
            locations_by_game.setdefault(location.game_id, []).append(location)
        matched_rule_ids: set[str] = set()

        for game in games:
            if game.status == "save_only":
                continue
            per_game_install_dir: Path | None = None
            engine_metadata: Mapping[str, str] = {}
            metadata: dict[str, object] = collect_rule_identity(
                game,
                tuple(locations_by_game.get(game.id, ())),
            ).as_rule_metadata()
            if game.status == "installed":
                try:
                    per_game_install_dir = self._library.install_directory(game.id)
                except (OSError, ValueError):
                    per_game_install_dir = None
                if per_game_install_dir is not None:
                    engine_metadata = load_engine_metadata(game, per_game_install_dir)
                    metadata = {**engine_metadata, **metadata}
            try:
                game_suggestions = snapshot.save_rules.suggest_game_specific(
                    game,
                    per_game_install_dir,
                    metadata,
                )
                engine_suggestions = (
                    snapshot.save_rules.suggest_engine(
                        game,
                        per_game_install_dir,
                        metadata,
                    )
                    if per_game_install_dir is not None
                    else ()
                )
            except Exception as error:
                warnings.append(f"声明式存档规则不可用：{error}")
                game_suggestions = ()
                engine_suggestions = ()
            for suggestion in (*game_suggestions, *engine_suggestions):
                source = _declarative_source(suggestion)
                if source is None or not _allowed_rule_scope(
                    suggestion.path_template,
                    context,
                ):
                    continue
                rule_id = _suggestion_rule_id(suggestion)
                if rule_id is not None:
                    matched_rule_ids.add(rule_id)
                identity_metadata = collect_rule_identity(
                    game,
                    tuple(locations_by_game.get(game.id, ())),
                )
                identity = RuleIdentity(
                    source=source,
                    game_id=game.id,
                    external_title=game.title,
                    external_product_id=(
                        identity_metadata.product_ids[0]
                        if identity_metadata.product_ids
                        else _product_id(suggestion.display_path)
                    ),
                    engine_id=game.engine_id,
                    confidence=_declarative_confidence(suggestion),
                    strong_group_key=f"game:{game.id}",
                    evidence=suggestion.evidence,
                )
                self._add_probed_suggestion(
                    suggestion,
                    per_game_install_dir,
                    source,
                    identity,
                    add,
                    warnings,
                )

            if per_game_install_dir is not None:
                for suggestion in self._engine_hints.suggest(
                    game,
                    per_game_install_dir,
                    engine_metadata,
                ):
                    if not _allowed_rule_scope(suggestion.path_template, context):
                        continue
                    identity = RuleIdentity(
                        source="engine",
                        game_id=game.id,
                        external_title=game.title,
                        external_product_id=_product_id(suggestion.display_path),
                        engine_id=game.engine_id,
                        confidence=(
                            "high" if suggestion.confidence >= 0.9 else "medium"
                        ),
                        strong_group_key=f"game:{game.id}",
                        evidence=suggestion.evidence,
                    )
                    self._add_probed_suggestion(
                        suggestion,
                        per_game_install_dir,
                        "engine",
                        identity,
                        add,
                        warnings,
                    )
            version_parts.append((game.id, game.engine_id, game.engine_rules_version))

        for save_rule in snapshot.save_rules.rules:
            if save_rule.metadata.rule_type != "save_game":
                continue
            if save_rule.metadata.qualified_id in matched_rule_ids:
                continue
            for suggestion in snapshot.save_rules.suggest_rule(save_rule, None, {}):
                source = _declarative_source(suggestion)
                if source is None or not _allowed_rule_scope(
                    suggestion.path_template,
                    context,
                ):
                    continue
                title = save_rule.titles[0] if save_rule.titles else save_rule.label
                product_id = (
                    save_rule.product_ids[0] if save_rule.product_ids else None
                )
                identity = RuleIdentity(
                    source=source,
                    game_id=None,
                    external_title=title,
                    external_product_id=product_id,
                    engine_id=None,
                    confidence=_declarative_confidence(suggestion),
                    strong_group_key=(
                        f"product:{product_id.casefold()}"
                        if product_id is not None
                        else f"rule:{save_rule.metadata.qualified_id}"
                    ),
                    evidence=suggestion.evidence,
                )
                self._add_probed_suggestion(
                    suggestion,
                    None,
                    source,
                    identity,
                    add,
                    warnings,
                )

        rules_version = hashlib.sha256(
            json.dumps(
                version_parts,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return BatchRuleCatalog(
            candidates=tuple(
                replace(candidate, sources=_ordered_sources(candidate.sources))
                for candidate in accumulator.snapshot()
            ),
            identities_by_path=MappingProxyType(
                {
                    key: tuple(sorted(value, key=_identity_rank))
                    for key, value in identities.items()
                }
            ),
            reverse_path_rules=tuple(reverse_rules),
            warnings=tuple(warnings),
            rules_version=rules_version,
        )

    def _add_probed_suggestion(
        self,
        suggestion: SaveLocationSuggestion,
        install_dir: Path | None,
        source: BatchCandidateSource,
        identity: RuleIdentity,
        add: AddCandidate,
        warnings: list[str],
    ) -> None:
        result = self._rule_probe.probe(
            suggestion.kind,
            suggestion.path_template,
            install_dir,
        )
        if not result.found:
            return
        evidence = (*suggestion.evidence, *_probe_evidence(result.diagnostics))
        if result.truncated:
            warnings.append(f"规则探测已受限：{suggestion.path_template}")
        display_path = (
            result.matches[0]
            if suggestion.kind != "glob"
            else suggestion.display_path
        )
        add(
            _raw_candidate(
                scope_key=_scope_key(suggestion.path_template),
                kind=suggestion.kind,
                path_template=suggestion.path_template,
                display_path=display_path,
                path_key=candidate_path_key(suggestion.kind, display_path),
                source=source,
                evidence=evidence,
            ),
            replace(identity, evidence=evidence),
        )

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


def _is_literal(value: str) -> bool:
    return not any(character in value for character in "*?[") and not bool(
        _EMBEDDED_TOKEN.search(value)
    )


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


def _scope_key(path_template: str) -> str:
    token = path_template.replace("/", "\\").partition("\\")[0]
    return _SCOPE_BY_TOKEN.get(token, "registry" if token.startswith("HKEY_") else "recorded")


def _product_id(value: str) -> str | None:
    match = _PRODUCT_ID.search(value)
    return None if match is None else match.group(1).upper()


def _ordered_sources(
    sources: tuple[BatchCandidateSource, ...],
) -> tuple[BatchCandidateSource, ...]:
    ranks = {
        "recorded": -1,
        "user": 0,
        "builtin": 1,
        "ludusavi": 2,
        "engine": 5,
        "bounded_scan": 6,
        "registry": 7,
    }
    return tuple(sorted(sources, key=lambda source: ranks[source]))


def _identity_rank(identity: RuleIdentity) -> tuple[int, str]:
    ranks = {"recorded": -1, "user": 0, "builtin": 1, "ludusavi": 2, "engine": 5}
    return ranks.get(identity.source, 9), identity.strong_group_key or ""


def _declarative_source(
    suggestion: SaveLocationSuggestion,
) -> Literal["user", "builtin"] | None:
    for evidence in suggestion.source_evidence:
        if evidence.source == "user":
            return "user"
        if evidence.source == "builtin":
            return "builtin"
    return None


def _declarative_confidence(
    suggestion: SaveLocationSuggestion,
) -> BatchConfidence:
    if suggestion.group == "experimental":
        return "low"
    return "high" if suggestion.confidence >= 0.9 else "medium"


def _suggestion_rule_id(suggestion: SaveLocationSuggestion) -> str | None:
    if suggestion.suggestion_id is None:
        return None
    return suggestion.suggestion_id.rpartition(":")[0] or None


def _allowed_rule_scope(
    path_template: str,
    context: BatchRuleContext,
) -> bool:
    normalized = path_template.replace("/", "\\")
    if normalized.startswith(("HKEY_CURRENT_USER\\", "HKEY_LOCAL_MACHINE\\")):
        return True
    token = normalized.partition("\\")[0]
    return token == "<game>" or token in context.root_tokens


def _probe_evidence(diagnostics: tuple[str, ...]) -> tuple[str, ...]:
    labels = {
        "registry_probe_failed": "规则探测注册表失败",
        "filesystem_probe_failed": "规则探测文件系统失败",
        "reparse_point_skipped": "规则探测跳过链接或重解析点",
        "network_or_device_root_rejected": "规则探测拒绝网络或设备路径",
        "depth_limit_reached": "规则探测达到最大深度",
        "entry_limit_reached": "规则探测达到条目上限",
        "match_limit_reached": "规则探测达到结果上限",
        "deadline_reached": "规则探测达到时间上限",
    }
    return tuple(labels.get(code, f"规则探测诊断：{code}") for code in diagnostics)
