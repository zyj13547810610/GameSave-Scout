"""Evaluate bounded declarative engine evidence."""

from __future__ import annotations

import glob
from pathlib import Path

from gameshelf.engines.base import DetectionContext
from gameshelf.engines.bounded_reader import (
    contains_in_edges,
    read_prefix,
    read_text_limit,
)
from gameshelf.engines.models import EngineEvidence, EngineMatch
from gameshelf.engines.rule_schema import EngineRule, EvidenceRule
from gameshelf.scanning.pe_metadata import read_pe_metadata


class RuleDetector:
    def __init__(self, rule: EngineRule) -> None:
        self.rule = rule

    def cheap_probe(self, context: DetectionContext) -> bool:
        positive = (*self.rule.required, *self.rule.optional)
        return any(_target_may_exist(context.game_dir, evidence) for evidence in positive)

    def inspect(self, context: DetectionContext) -> EngineMatch | None:
        required_matches: list[EngineEvidence] = []
        for evidence in self.rule.required:
            matched = _evaluate(context, evidence)
            if matched is None:
                return None
            required_matches.append(matched)

        optional_matches = tuple(
            match
            for evidence in self.rule.optional
            if (match := _evaluate(context, evidence)) is not None
        )
        negative_matches = tuple(
            match
            for evidence in self.rule.negative
            if (match := _evaluate(context, evidence)) is not None
        )
        positive_total = sum(
            max(0.0, evidence.weight)
            for evidence in (*self.rule.required, *self.rule.optional)
        )
        matched_weight = sum(
            max(0.0, evidence.weight)
            for evidence in (*required_matches, *optional_matches)
        )
        confidence = matched_weight / positive_total if positive_total else 0.0
        confidence += sum(evidence.weight for evidence in negative_matches)
        confidence = min(1.0, max(0.0, confidence))
        if confidence < self.rule.threshold:
            return None
        return EngineMatch(
            self.rule.engine_id,
            self.rule.variant,
            confidence,
            (*required_matches, *optional_matches, *negative_matches),
            self.rule.version,
            self.rule.experimental,
        )


def _target_may_exist(root: Path, evidence: EvidenceRule) -> bool:
    if evidence.op == "glob_exists":
        return any(_bounded_glob(root, evidence.path))
    return _target(root, evidence.path).exists()


def _evaluate(
    context: DetectionContext, evidence: EvidenceRule
) -> EngineEvidence | None:
    root = context.game_dir
    path = _target(root, evidence.path)
    matched = False
    if evidence.op == "path_exists":
        matched = path.exists()
    elif evidence.op == "glob_exists":
        matched = bool(_bounded_glob(root, evidence.path))
    elif evidence.op == "magic_at" and path.is_file():
        needle = _bytes_value(evidence.value or "")
        data = read_prefix(path, min(64 * 1024, evidence.offset + len(needle)))
        matched = data[evidence.offset : evidence.offset + len(needle)] == needle
    elif evidence.op == "edge_contains" and path.is_file():
        matched = contains_in_edges(path, _bytes_value(evidence.value or ""))
    elif evidence.op == "text_contains" and path.is_file():
        matched = (evidence.value or "").casefold() in read_text_limit(path).casefold()
    elif evidence.op == "pe_field_contains" and path.is_file():
        metadata = read_pe_metadata(path)
        field = evidence.field or "product_name"
        value = getattr(metadata, field, "")
        matched = (evidence.value or "").casefold() in str(value).casefold()
    if not matched:
        return None
    return EngineEvidence(
        f"rule_{evidence.op}",
        f"Matched {evidence.op}",
        evidence.weight,
        evidence.path,
    )


def _target(root: Path, relative: str) -> Path:
    return root.joinpath(*relative.split("/"))


def _bounded_glob(root: Path, pattern: str) -> tuple[Path, ...]:
    matches: list[Path] = []
    root_resolved = root.resolve(strict=False)
    for raw in glob.iglob(str(_target(root, pattern)), recursive=True):
        candidate = Path(raw).resolve(strict=False)
        try:
            candidate.relative_to(root_resolved)
        except ValueError:
            continue
        matches.append(candidate)
        if len(matches) == 128:
            break
    return tuple(matches)


def _bytes_value(value: str) -> bytes:
    if value.startswith("hex:"):
        return bytes.fromhex(value[4:])
    return value.encode("latin-1")
