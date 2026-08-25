"""Targeted registry metadata snapshots for guided save detection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from gamesave_scout.platform.windows.registry import (
    RegistryKeyMetadata,
    RegistryMetadataEnumeration,
    RegistryValueMetadata,
)
from gamesave_scout.saves.guided_models import GuidedDiscoveryDraft


class RegistryMetadataSource(Protocol):
    def iter_metadata(
        self,
        key: str,
        *,
        max_subkey_depth: int = 4,
        max_keys: int = 256,
        max_values: int = 2048,
    ) -> RegistryMetadataEnumeration: ...


@dataclass(frozen=True, slots=True)
class RegistryTargetSnapshot:
    approved_key: str
    keys: tuple[RegistryKeyMetadata, ...]
    truncated: bool


@dataclass(frozen=True, slots=True)
class RegistrySnapshot:
    targets: tuple[RegistryTargetSnapshot, ...]


class RegistryMetadataReader:
    def __init__(self, source: RegistryMetadataSource) -> None:
        self._source = source

    def snapshot(self, keys: tuple[str, ...]) -> RegistrySnapshot:
        targets: dict[str, RegistryTargetSnapshot] = {}
        for approved_key in keys:
            normalized = approved_key.replace("/", "\\")
            dedupe_key = normalized.casefold()
            if dedupe_key in targets:
                continue
            enumeration = self._source.iter_metadata(normalized)
            targets[dedupe_key] = RegistryTargetSnapshot(
                approved_key=normalized,
                keys=enumeration.keys,
                truncated=enumeration.truncated,
            )
        return RegistrySnapshot(
            tuple(targets[key] for key in sorted(targets))
        )


def diff_registry_snapshots(
    before: RegistrySnapshot, after: RegistrySnapshot
) -> tuple[GuidedDiscoveryDraft, ...]:
    before_targets = {target.approved_key.casefold(): target for target in before.targets}
    after_targets = {target.approved_key.casefold(): target for target in after.targets}
    drafts: list[GuidedDiscoveryDraft] = []
    for target_key in sorted(before_targets.keys() | after_targets.keys()):
        before_target = before_targets.get(target_key)
        after_target = after_targets.get(target_key)
        approved_key = (
            before_target.approved_key
            if before_target is not None
            else after_target.approved_key  # type: ignore[union-attr]
        )
        evidence = _target_changes(before_target, after_target)
        if not evidence:
            continue
        affected_by_truncation = bool(
            (before_target is not None and before_target.truncated)
            or (after_target is not None and after_target.truncated)
        )
        if affected_by_truncation:
            evidence.append("注册表枚举达到上限，结果可能不完整")
        drafts.append(
            GuidedDiscoveryDraft(
                candidate_template=approved_key,
                display_path=approved_key,
                path_key=approved_key.casefold(),
                kind="registry",
                confidence=0.65,
                evidence=tuple(evidence),
                representative_files=(),
                first_changed_at=None,
                last_changed_at=None,
                mark_offset_ms=None,
                affected_by_overflow=False,
                affected_by_truncation=affected_by_truncation,
                preselected=False,
            )
        )
    return tuple(drafts)


def _target_changes(
    before: RegistryTargetSnapshot | None,
    after: RegistryTargetSnapshot | None,
) -> list[str]:
    before_values = _flatten_values(before)
    after_values = _flatten_values(after)
    evidence: list[str] = []
    for value_key in sorted(before_values.keys() | after_values.keys()):
        old = before_values.get(value_key)
        new = after_values.get(value_key)
        display_name = _display_value_name(value_key, old, new)
        if old is None:
            evidence.append(f"注册表值已创建：{display_name}")
        elif new is None:
            evidence.append(f"注册表值已删除：{display_name}")
        elif old != new:
            evidence.append(f"注册表值元数据已变化：{display_name}")
    if before is not None and after is not None:
        before_available = {item.key.casefold(): item.available for item in before.keys}
        after_available = {item.key.casefold(): item.available for item in after.keys}
        if before_available != after_available and not evidence:
            evidence.append("批准的注册表键可用状态发生变化")
    return evidence


def _flatten_values(
    target: RegistryTargetSnapshot | None,
) -> dict[tuple[str, str], RegistryValueMetadata]:
    if target is None:
        return {}
    return {
        (key.key.casefold(), value.name.casefold()): value
        for key in target.keys
        if key.available
        for value in key.values
    }


def _display_value_name(
    value_key: tuple[str, str],
    before: RegistryValueMetadata | None,
    after: RegistryValueMetadata | None,
) -> str:
    value = before or after
    assert value is not None
    return f"{value_key[0]}\\{value.name}"
