"""Shared exact game identity used by save-rule matching and editor prefill."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from gameshelf.library.models import Game
from gameshelf.saves.models import SaveLocation

_EXPLICIT_PRODUCT_ID = re.compile(
    r"(?i)(?<![a-z0-9])"
    r"(steam|gog|epic|itch|vndb|dlsite):([a-z0-9._-]{1,96})"
)
_DLSITE_ID = re.compile(r"(?i)(?<![a-z0-9])((?:RJ|VJ)[0-9]+)(?![a-z0-9])")


@dataclass(frozen=True, slots=True)
class RuleIdentityMetadata:
    exact_titles: tuple[str, ...]
    product_ids: tuple[str, ...]

    def as_rule_metadata(self) -> dict[str, object]:
        return {
            "exact_titles": self.exact_titles,
            "product_ids": self.product_ids,
        }


def collect_rule_identity(
    game: Game,
    recorded_locations: tuple[SaveLocation, ...],
) -> RuleIdentityMetadata:
    """Collect bounded exact aliases and canonical store IDs without fuzzy matching."""

    titles = _unique_text((game.title, game.detected_title))
    product_ids: list[str] = []
    values: list[str] = [
        game.title,
        game.detected_title or "",
        game.relative_dir or "",
        Path(game.main_exe_relpath).stem if game.main_exe_relpath else "",
    ]
    for location in recorded_locations:
        if not location.confirmed or not location.enabled:
            continue
        values.extend(
            (
                location.path_template,
                location.display_path,
                *location.evidence,
            )
        )
    for value in values:
        for match in _EXPLICIT_PRODUCT_ID.finditer(value):
            namespace = match.group(1).casefold()
            identifier = match.group(2)
            if namespace == "dlsite" and _DLSITE_ID.fullmatch(identifier):
                identifier = identifier.upper()
            _append_unique(product_ids, f"{namespace}:{identifier}")
        for match in _DLSITE_ID.finditer(value):
            _append_unique(product_ids, f"dlsite:{match.group(1).upper()}")
    return RuleIdentityMetadata(titles, tuple(product_ids))


def _unique_text(values: tuple[str | None, ...]) -> tuple[str, ...]:
    result: list[str] = []
    keys: set[str] = set()
    for value in values:
        if not value:
            continue
        clean = value.strip()
        key = " ".join(clean.casefold().split())
        if not clean or key in keys:
            continue
        keys.add(key)
        result.append(clean)
    return tuple(result)


def _append_unique(target: list[str], value: str) -> None:
    key = value.casefold()
    if all(existing.casefold() != key for existing in target):
        target.append(value)
