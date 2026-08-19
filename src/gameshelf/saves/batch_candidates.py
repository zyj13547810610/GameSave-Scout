"""Stable candidate identity and bounded aggregation for batch save discovery."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import replace

from gameshelf.saves.batch_models import (
    BatchCandidateKind,
    RawBatchCandidate,
    RepresentativeFile,
)
from gameshelf.scanning.path_keys import windows_path_key

MAX_BATCH_CANDIDATES = 10_000
MAX_REPRESENTATIVE_FILES = 20

_REGISTRY_ROOTS = {
    "HKCU": "HKEY_CURRENT_USER",
    "HKEY_CURRENT_USER": "HKEY_CURRENT_USER",
    "HKLM": "HKEY_LOCAL_MACHINE",
    "HKEY_LOCAL_MACHINE": "HKEY_LOCAL_MACHINE",
    "HKCR": "HKEY_CLASSES_ROOT",
    "HKEY_CLASSES_ROOT": "HKEY_CLASSES_ROOT",
    "HKU": "HKEY_USERS",
    "HKEY_USERS": "HKEY_USERS",
}


def candidate_path_key(kind: BatchCandidateKind, value: str) -> str:
    """Return the stable Windows identity key for one candidate path."""

    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError("批量存档候选路径无效。")
    if kind != "registry":
        return windows_path_key(value.strip())

    clean = value.strip().replace("/", "\\").rstrip("\\")
    root, separator, suffix = clean.partition("\\")
    canonical_root = _REGISTRY_ROOTS.get(root.upper())
    if canonical_root is None or not separator or not suffix:
        raise ValueError("批量存档注册表候选必须包含受支持的根键和子键。")
    if any(part in {"", ".", ".."} for part in suffix.split("\\")):
        raise ValueError("批量存档注册表候选路径无效。")
    return f"{canonical_root}\\{suffix}".casefold()


class BatchCandidateAccumulator:
    """Merge candidates by stable identity while enforcing fixed hard limits."""

    def __init__(
        self,
        *,
        max_candidates: int = MAX_BATCH_CANDIDATES,
        max_representative_files: int = MAX_REPRESENTATIVE_FILES,
    ) -> None:
        if max_candidates < 1 or max_representative_files < 1:
            raise ValueError("批量存档候选聚合上限必须大于零。")
        self._max_candidates = max_candidates
        self._max_representative_files = max_representative_files
        self._candidates: OrderedDict[
            tuple[BatchCandidateKind, str], RawBatchCandidate
        ] = OrderedDict()
        self._truncated = False

    @property
    def truncated(self) -> bool:
        return self._truncated

    def add(self, candidate: RawBatchCandidate) -> bool:
        normalized_key = candidate_path_key(candidate.kind, candidate.path_key)
        identity = (candidate.kind, normalized_key)
        existing = self._candidates.get(identity)
        if existing is None:
            if len(self._candidates) >= self._max_candidates:
                self._truncated = True
                return False
            representatives, truncated = self._limit_representatives(
                candidate.representative_files
            )
            self._candidates[identity] = replace(
                candidate,
                path_key=normalized_key,
                sources=_stable_unique(candidate.sources),
                evidence=_stable_unique(candidate.evidence),
                representative_files=representatives,
                representatives_truncated=(
                    candidate.representatives_truncated or truncated
                ),
            )
            return True

        representatives, truncated = self._limit_representatives(
            (*existing.representative_files, *candidate.representative_files)
        )
        self._candidates[identity] = replace(
            existing,
            sources=_stable_unique((*existing.sources, *candidate.sources)),
            evidence=_stable_unique((*existing.evidence, *candidate.evidence)),
            representative_files=representatives,
            matched_file_count=max(
                existing.matched_file_count,
                candidate.matched_file_count,
            ),
            representatives_truncated=(
                existing.representatives_truncated
                or candidate.representatives_truncated
                or truncated
            ),
        )
        return True

    def snapshot(self) -> tuple[RawBatchCandidate, ...]:
        return tuple(self._candidates.values())

    def _limit_representatives(
        self,
        values: tuple[RepresentativeFile, ...],
    ) -> tuple[tuple[RepresentativeFile, ...], bool]:
        unique: list[RepresentativeFile] = []
        seen: set[tuple[str, int, int]] = set()
        truncated = False
        for value in values:
            key = (value.name.casefold(), value.size, value.modified_time_ns)
            if key in seen:
                continue
            seen.add(key)
            if len(unique) >= self._max_representative_files:
                truncated = True
                continue
            unique.append(value)
        return tuple(unique), truncated


def _stable_unique[T](values: tuple[T, ...]) -> tuple[T, ...]:
    return tuple(dict.fromkeys(values))
