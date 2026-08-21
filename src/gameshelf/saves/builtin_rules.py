"""Typed suggestions produced from the bundled declarative save rules."""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Iterable, Mapping
from pathlib import Path

from gameshelf.library.models import Game
from gameshelf.saves.models import SaveLocationSuggestion, SuggestionEvidence
from gameshelf.saves.rule_schema import BuiltinSaveRule, SaveRuleLocation, load_save_rules
from gameshelf.saves.templates import InvalidPathTemplate, PathTemplateResolver

_UNSAFE_WINDOWS_CHARACTER = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_WINDOWS_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


class BuiltinSaveRuleProvider:
    def __init__(
        self,
        rules: tuple[BuiltinSaveRule, ...],
        resolver: PathTemplateResolver,
        logger: logging.Logger | None = None,
    ) -> None:
        self._rules = tuple(
            sorted(
                (rule for rule in rules if rule.metadata.enabled),
                key=lambda rule: (-rule.metadata.priority, rule.metadata.qualified_id),
            )
        )
        self._resolver = resolver
        self._logger = logger or logging.getLogger(__name__)

    @classmethod
    def from_file(
        cls,
        path: Path,
        resolver: PathTemplateResolver,
        logger: logging.Logger | None = None,
    ) -> BuiltinSaveRuleProvider:
        return cls(load_save_rules(path), resolver, logger)

    @classmethod
    def empty(
        cls,
        resolver: PathTemplateResolver,
        logger: logging.Logger | None = None,
    ) -> BuiltinSaveRuleProvider:
        return cls((), resolver, logger)

    @property
    def rules_version(self) -> str | None:
        return self._rules[0].metadata.version if self._rules else None

    def suggest_game_specific(
        self,
        game: Game,
        install_dir: Path | None,
        metadata: Mapping[str, object],
    ) -> tuple[SaveLocationSuggestion, ...]:
        title_key = _normalize_title(game.title)
        product_ids = _metadata_product_ids(metadata)
        matches = (
            rule
            for rule in self._rules
            if rule.metadata.rule_type == "save_game"
            and (
                title_key in {_normalize_title(title) for title in rule.titles}
                or bool(product_ids.intersection(rule.product_ids))
            )
        )
        return self._suggest(matches, install_dir, metadata)

    def suggest_engine(
        self,
        game: Game,
        install_dir: Path | None,
        metadata: Mapping[str, object],
    ) -> tuple[SaveLocationSuggestion, ...]:
        if game.engine_id is None:
            return ()
        matches = (
            rule
            for rule in self._rules
            if rule.metadata.rule_type == "save_engine"
            and game.engine_id in rule.engine_ids
        )
        return self._suggest(matches, install_dir, metadata)

    def _suggest(
        self,
        rules: Iterable[BuiltinSaveRule],
        install_dir: Path | None,
        metadata: Mapping[str, object],
    ) -> tuple[SaveLocationSuggestion, ...]:
        suggestions: list[SaveLocationSuggestion] = []
        for rule in rules:
            detail = _evidence_detail(rule)
            for index, location in enumerate(rule.locations):
                rendered = self._render_location(rule, location, metadata)
                if rendered is None:
                    continue
                if location.kind == "registry":
                    display_path = rendered
                else:
                    try:
                        display_path = str(self._resolver.expand(rendered, install_dir))
                    except InvalidPathTemplate as error:
                        self._logger.warning(
                            "内置存档规则 %s 的路径无法安全展开：%s",
                            rule.metadata.qualified_id,
                            error,
                        )
                        continue
                suggestions.append(
                    SaveLocationSuggestion(
                        kind=location.kind,
                        path_template=rendered,
                        display_path=display_path,
                        source="engine",
                        confidence=location.confidence,
                        evidence=(detail,),
                        source_evidence=(
                            SuggestionEvidence(source="builtin", detail=detail),
                        ),
                        suggestion_id=f"{rule.metadata.qualified_id}:{index}",
                        category=location.category,
                        group=(
                            "experimental"
                            if rule.metadata.status == "experimental"
                            else "possible"
                        ),
                    )
                )
        return tuple(suggestions)

    def _render_location(
        self,
        rule: BuiltinSaveRule,
        location: SaveRuleLocation,
        metadata: Mapping[str, object],
    ) -> str | None:
        rendered = location.path_template
        for field in location.metadata_fields:
            value = metadata.get(field)
            if not isinstance(value, str) or not _safe_windows_segment(value):
                self._logger.warning(
                    "内置存档规则 %s 缺少安全元数据 %s，已跳过该位置。",
                    rule.metadata.qualified_id,
                    field,
                )
                return None
            rendered = rendered.replace(f"{{{field}}}", value)
        return rendered


def _normalize_title(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _metadata_product_ids(metadata: Mapping[str, object]) -> set[str]:
    raw = metadata.get("product_ids", ())
    if not isinstance(raw, (list, tuple, set, frozenset)):
        return set()
    return {value for value in raw if isinstance(value, str)}


def _safe_windows_segment(value: str) -> bool:
    stripped = value.strip()
    if (
        not stripped
        or stripped != value
        or value.endswith((".", " "))
        or _UNSAFE_WINDOWS_CHARACTER.search(value) is not None
        or len(value) > 128
    ):
        return False
    base_name = value.split(".", 1)[0].casefold()
    return base_name not in _RESERVED_WINDOWS_NAMES


def _evidence_detail(rule: BuiltinSaveRule) -> str:
    references = rule.metadata.references
    if not references:
        reference_summary = "无公开链接（实验规则）"
    elif len(references) == 1:
        reference_summary = references[0]
    else:
        reference_summary = f"{references[0]}（另 {len(references) - 1} 项）"
    return (
        f"内置规则 {rule.metadata.qualified_id}"
        f"（{rule.metadata.status}；依据：{reference_summary}）"
    )
