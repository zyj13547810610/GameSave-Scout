"""Bounded metadata-only filesystem scanning for batch save discovery."""

from __future__ import annotations

import os
import re
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path, PureWindowsPath
from time import monotonic
from typing import Literal, Protocol, cast

from gameshelf.bridge.tasks import TaskCancelled
from gameshelf.saves.batch_candidates import (
    MAX_BATCH_CANDIDATES,
    MAX_REPRESENTATIVE_FILES,
    BatchCandidateAccumulator,
    candidate_path_key,
)
from gameshelf.saves.batch_models import (
    BatchCandidateSource,
    BatchScanScope,
    RawBatchCandidate,
    RepresentativeFile,
)
from gameshelf.saves.batch_rules import BatchPathRule, BatchRuleCatalog
from gameshelf.saves.guided_scope import is_windows_reparse_point
from gameshelf.scanning.path_keys import is_same_or_child, windows_path_key

type BatchScopeStatus = Literal[
    "completed",
    "unavailable",
    "truncated",
    "cancelled",
]
type BatchCancelReason = Literal["user", "shutdown"]

MAX_CUSTOM_SCOPE_ENTRIES = 100_000
MAX_TOTAL_ENTRIES = 500_000

_NOISE_DIRECTORIES = frozenset(
    {
        "temp",
        "cache",
        "caches",
        "gpucache",
        "code cache",
        "crashpad",
        "crashes",
        "logs",
        "shadercache",
    }
)
_SAVE_EXTENSIONS = frozenset(
    {
        ".sav",
        ".save",
        ".dat",
        ".rvdata",
        ".rvdata2",
        ".rpgsave",
        ".rmmzsave",
        ".lsd",
        ".json",
    }
)
_NON_JSON_SAVE_EXTENSIONS = _SAVE_EXTENSIONS - {".json"}
_SAVE_NAME = re.compile(r"(?i)(?:^|[^a-z0-9])(save(?:data|game)?|slot)|^(?:save|slot)")
_PRODUCT_ID = re.compile(r"(?i)(?<![A-Z0-9])(?:RJ|VJ)[0-9]{4,}(?![A-Z0-9])")
_ENGINE_DIRECTORY_NAMES = frozenset({"save", "saves", "savedata", "savegame", "savegames", "slots"})
_ROOT_TOKEN_BY_SCOPE = {
    "documents": "<winDocuments>",
    "saved_games": "<winSavedGames>",
    "app_data": "<winAppData>",
    "local_app_data": "<winLocalAppData>",
    "local_app_data_low": "<winLocalAppDataLow>",
}


class BatchScanContext(Protocol):
    def raise_if_cancelled(self) -> None: ...

    def report(
        self,
        completed: int,
        total: int | None,
        message: str,
        *,
        details: Mapping[str, str | int | float | bool | None] | None = None,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class BatchScopeResult:
    scope_key: str
    status: BatchScopeStatus
    entries: int
    candidate_count: int
    truncated: bool
    error: str | None


@dataclass(frozen=True, slots=True)
class BatchScanOutput:
    scope_results: tuple[BatchScopeResult, ...]
    candidates: tuple[RawBatchCandidate, ...]
    total_entries: int
    elapsed_seconds: float

    def scope(self, key: str) -> BatchScopeResult:
        for result in self.scope_results:
            if result.scope_key == key:
                return result
        raise KeyError(key)


class BatchScanCancelled(RuntimeError):
    def __init__(self, output: BatchScanOutput, reason: BatchCancelReason) -> None:
        super().__init__("批量存档扫描已取消。")
        self.output = output
        self.reason = reason


type ReparsePointCheck = Callable[[Path], bool]
type ReverseRuleIndex = Mapping[tuple[str, str], tuple[BatchPathRule, ...]]


@dataclass(slots=True)
class _ScopeState:
    scope: BatchScanScope
    entries: int = 0
    status: BatchScopeStatus = "completed"
    error: str | None = None


@dataclass(frozen=True, slots=True)
class _FileMetadata:
    path: Path
    name: str
    suffix: str
    size: int
    modified_time_ns: int

    def representative(self) -> RepresentativeFile:
        return RepresentativeFile(self.name, self.size, self.modified_time_ns)


class BatchFilesystemScanner:
    """Scan selected roots once, with fixed traversal and memory limits."""

    def __init__(
        self,
        *,
        max_entries_per_custom: int = MAX_CUSTOM_SCOPE_ENTRIES,
        max_total_entries: int = MAX_TOTAL_ENTRIES,
        max_candidates: int = MAX_BATCH_CANDIDATES,
        max_representative_files: int = MAX_REPRESENTATIVE_FILES,
        progress_interval: int = 256,
        is_reparse_point: ReparsePointCheck | None = None,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        limits = (
            max_entries_per_custom,
            max_total_entries,
            max_candidates,
            max_representative_files,
            progress_interval,
        )
        if any(value < 1 for value in limits):
            raise ValueError("批量存档扫描上限必须大于零。")
        self._max_entries_per_custom = max_entries_per_custom
        self._max_total_entries = max_total_entries
        self._max_candidates = max_candidates
        self._max_representative_files = max_representative_files
        self._progress_interval = progress_interval
        self._is_reparse_point = is_reparse_point or is_windows_reparse_point
        self._clock = clock

    def scan(
        self,
        scopes: Sequence[BatchScanScope],
        catalog: BatchRuleCatalog,
        context: BatchScanContext,
    ) -> BatchScanOutput:
        started = self._clock()
        all_scopes = tuple(scopes)
        reverse_rule_index = self._index_reverse_rules(catalog.reverse_path_rules)
        accumulator = BatchCandidateAccumulator(
            max_candidates=self._max_candidates,
            max_representative_files=self._max_representative_files,
        )
        for candidate in catalog.candidates:
            accumulator.add(self._attribute_candidate(candidate, all_scopes))

        scope_results: list[BatchScopeResult] = []
        total_entries = 0
        try:
            context.raise_if_cancelled()
            for scope in all_scopes:
                state = _ScopeState(scope)
                unavailable = self._unavailable_reason(scope.root)
                if unavailable is not None:
                    scope_results.append(
                        self._result(state, accumulator, "unavailable", unavailable)
                    )
                    continue
                try:
                    total_entries = self._scan_scope(
                        state,
                        all_scopes,
                        reverse_rule_index,
                        accumulator,
                        context,
                        total_entries,
                        started,
                    )
                except TaskCancelled as error:
                    state.status = "cancelled"
                    state.error = None
                    scope_results.append(self._result(state, accumulator, "cancelled"))
                    output = self._output(
                        scope_results,
                        accumulator,
                        sum(result.entries for result in scope_results),
                        started,
                    )
                    raise BatchScanCancelled(
                        output,
                        _cancel_reason(error),
                    ) from error
                scope_results.append(self._result(state, accumulator, state.status))
                if total_entries >= self._max_total_entries or accumulator.truncated:
                    break
        except TaskCancelled as error:
            raise BatchScanCancelled(
                self._output(scope_results, accumulator, total_entries, started),
                _cancel_reason(error),
            ) from error
        return self._output(scope_results, accumulator, total_entries, started)

    def _scan_scope(
        self,
        state: _ScopeState,
        all_scopes: tuple[BatchScanScope, ...],
        reverse_rule_index: ReverseRuleIndex,
        accumulator: BatchCandidateAccumulator,
        context: BatchScanContext,
        total_entries: int,
        started: float,
    ) -> int:
        queue: deque[tuple[Path, int]] = deque([(state.scope.root, 0)])
        nested_root_keys = {
            windows_path_key(other.root)
            for other in all_scopes
            if other.key != state.scope.key
            and is_same_or_child(windows_path_key(other.root), windows_path_key(state.scope.root))
            and windows_path_key(other.root) != windows_path_key(state.scope.root)
        }
        while queue:
            directory, depth = queue.popleft()
            files: list[_FileMetadata] = []
            try:
                iterator = os.scandir(directory)
                with iterator:
                    for entry in iterator:
                        if self._limit_reached(state, total_entries):
                            state.status = "truncated"
                            return total_entries
                        state.entries += 1
                        total_entries += 1
                        entry_path = Path(entry.path)
                        if total_entries % self._progress_interval == 0:
                            self._report(
                                context,
                                state,
                                accumulator,
                                entry_path,
                                total_entries,
                                started,
                            )
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                if (
                                    entry.name.casefold() in _NOISE_DIRECTORIES
                                    or windows_path_key(entry_path) in nested_root_keys
                                    or entry.is_symlink()
                                    or self._is_reparse_point(entry_path)
                                ):
                                    continue
                                self._add_directory_rule_candidate(
                                    entry_path,
                                    state.scope,
                                    all_scopes,
                                    reverse_rule_index,
                                    accumulator,
                                )
                                if accumulator.truncated:
                                    state.status = "truncated"
                                    return total_entries
                                if depth < state.scope.max_depth:
                                    queue.append((entry_path, depth + 1))
                                continue
                            if not entry.is_file(follow_symlinks=False):
                                continue
                            metadata = entry.stat(follow_symlinks=False)
                        except OSError:
                            continue
                        files.append(
                            _FileMetadata(
                                path=entry_path,
                                name=entry.name,
                                suffix=entry_path.suffix.casefold(),
                                size=max(0, metadata.st_size),
                                modified_time_ns=max(0, metadata.st_mtime_ns),
                            )
                        )
            except OSError:
                if directory == state.scope.root:
                    state.status = "unavailable"
                    state.error = "目录不存在、无权访问或暂时不可用。"
                    return total_entries
                continue

            self._add_file_candidates(
                directory,
                files,
                state.scope,
                all_scopes,
                reverse_rule_index,
                accumulator,
            )
            if accumulator.truncated:
                state.status = "truncated"
                return total_entries

        self._report(
            context,
            state,
            accumulator,
            state.scope.root,
            total_entries,
            started,
        )
        return total_entries

    def _add_directory_rule_candidate(
        self,
        directory: Path,
        scope: BatchScanScope,
        all_scopes: tuple[BatchScanScope, ...],
        reverse_rule_index: ReverseRuleIndex,
        accumulator: BatchCandidateAccumulator,
    ) -> None:
        matching = self._matching_rules(directory, all_scopes, reverse_rule_index)
        for rule in matching:
            self._add_candidate(
                accumulator,
                scope,
                directory,
                source=rule.source,
                evidence=(*rule.identity.evidence, "规则目录命中"),
                representatives=(),
                matched_file_count=0,
            )

    def _add_file_candidates(
        self,
        directory: Path,
        files: list[_FileMetadata],
        scope: BatchScanScope,
        all_scopes: tuple[BatchScanScope, ...],
        reverse_rule_index: ReverseRuleIndex,
        accumulator: BatchCandidateAccumulator,
    ) -> None:
        rule_files: dict[BatchPathRule, list[_FileMetadata]] = {}
        for file in files:
            for rule in self._matching_rules(
                file.path,
                all_scopes,
                reverse_rule_index,
            ):
                rule_files.setdefault(rule, []).append(file)
        for rule, matched in rule_files.items():
            self._add_candidate(
                accumulator,
                scope,
                directory,
                source=rule.source,
                evidence=(*rule.identity.evidence, "规则文件命中"),
                representatives=tuple(item.representative() for item in matched),
                matched_file_count=len(matched),
            )

        allowed = [file for file in files if file.suffix in _SAVE_EXTENSIONS]
        if not allowed:
            return
        directory_signal = self._directory_signal(directory, scope)
        named_non_json = [
            file
            for file in allowed
            if file.suffix in _NON_JSON_SAVE_EXTENSIONS and _SAVE_NAME.search(file.name)
        ]
        if not directory_signal and not named_non_json:
            return
        representatives = allowed
        evidence = (
            "目录路径包含稳定产品 ID 或明确存档结构"
            if directory_signal
            else "目录内存在典型存档文件名与扩展名"
        )
        self._add_candidate(
            accumulator,
            scope,
            directory,
            source="bounded_scan",
            evidence=(evidence,),
            representatives=tuple(item.representative() for item in representatives),
            matched_file_count=len(representatives),
        )

    def _matching_rules(
        self,
        path: Path,
        scopes: tuple[BatchScanScope, ...],
        reverse_rule_index: ReverseRuleIndex,
    ) -> tuple[BatchPathRule, ...]:
        matches: list[BatchPathRule] = []
        path_key = windows_path_key(path)
        for standard_scope in scopes:
            token = _ROOT_TOKEN_BY_SCOPE.get(standard_scope.key)
            if token is None or not is_same_or_child(
                path_key, windows_path_key(standard_scope.root)
            ):
                continue
            try:
                relative = str(path.relative_to(standard_scope.root)).replace("/", "\\")
            except ValueError:
                continue
            first_segment_key = windows_path_key(relative.partition("\\")[0])
            rules = (
                *reverse_rule_index.get((token, first_segment_key), ()),
                *reverse_rule_index.get((token, ""), ()),
            )
            for rule in rules:
                pattern = rule.relative_pattern.replace("/", "\\")
                if PureWindowsPath(relative).match(pattern):
                    matches.append(rule)
        return tuple(dict.fromkeys(matches))

    @staticmethod
    def _index_reverse_rules(
        rules: tuple[BatchPathRule, ...],
    ) -> ReverseRuleIndex:
        grouped: dict[tuple[str, str], list[BatchPathRule]] = {}
        for rule in rules:
            if rule.kind != "file":
                continue
            grouped.setdefault(
                (rule.root_token, rule.first_segment_key),
                [],
            ).append(rule)
        return {key: tuple(values) for key, values in grouped.items()}

    def _add_candidate(
        self,
        accumulator: BatchCandidateAccumulator,
        scope: BatchScanScope,
        directory: Path,
        *,
        source: BatchCandidateSource,
        evidence: tuple[str, ...],
        representatives: tuple[RepresentativeFile, ...],
        matched_file_count: int,
    ) -> None:
        path_template = self._path_template(scope, directory)
        display_path = str(directory)
        accumulator.add(
            RawBatchCandidate(
                scope_key=scope.key,
                kind="directory",
                path_template=path_template,
                display_path=display_path,
                path_key=candidate_path_key("directory", display_path),
                sources=(source,),
                evidence=evidence,
                representative_files=representatives,
                matched_file_count=matched_file_count,
                representatives_truncated=False,
            )
        )

    @staticmethod
    def _directory_signal(directory: Path, scope: BatchScanScope) -> bool:
        try:
            relative = directory.relative_to(scope.root)
        except ValueError:
            relative = directory
        parts = tuple(part.casefold() for part in relative.parts)
        if not parts:
            parts = (directory.name.casefold(),)
        if any(_PRODUCT_ID.search(part) for part in parts):
            return True
        if directory.name.casefold() in _ENGINE_DIRECTORY_NAMES:
            return True
        return len(parts) >= 2 and parts[-2:] == ("saved", "savegames")

    @staticmethod
    def _attribute_candidate(
        candidate: RawBatchCandidate,
        scopes: tuple[BatchScanScope, ...],
    ) -> RawBatchCandidate:
        if candidate.kind == "registry":
            return candidate
        path_key = windows_path_key(candidate.display_path)
        containing = [
            scope for scope in scopes if is_same_or_child(path_key, windows_path_key(scope.root))
        ]
        if not containing:
            return candidate
        most_specific = max(
            containing,
            key=lambda scope: len(windows_path_key(scope.root)),
        )
        if most_specific.key == candidate.scope_key:
            return candidate
        return replace(candidate, scope_key=most_specific.key)

    @staticmethod
    def _path_template(scope: BatchScanScope, directory: Path) -> str:
        token = _ROOT_TOKEN_BY_SCOPE.get(scope.key)
        if token is None:
            return str(directory)
        relative = str(directory.relative_to(scope.root)).replace("/", "\\")
        return token if relative == "." else f"{token}\\{relative}"

    def _limit_reached(self, state: _ScopeState, total_entries: int) -> bool:
        return total_entries >= self._max_total_entries or (
            state.scope.source == "custom" and state.entries >= self._max_entries_per_custom
        )

    def _unavailable_reason(self, root: Path) -> str | None:
        try:
            if not root.is_dir():
                return "目录不存在、无权访问或暂时不可用。"
            if root.is_symlink() or self._is_reparse_point(root):
                return "目录是符号链接、联接或其他重解析点。"
        except OSError:
            return "目录不存在、无权访问或暂时不可用。"
        return None

    def _report(
        self,
        context: BatchScanContext,
        state: _ScopeState,
        accumulator: BatchCandidateAccumulator,
        current_path: Path,
        total_entries: int,
        started: float,
    ) -> None:
        context.raise_if_cancelled()
        context.report(
            total_entries,
            None,
            f"正在扫描 {state.scope.label}",
            details={
                "phase": "filesystem",
                "scope": state.scope.key,
                "currentPath": str(current_path),
                "entries": state.entries,
                "candidateCount": len(accumulator.snapshot()),
                "elapsedSeconds": max(0.0, self._clock() - started),
            },
        )

    @staticmethod
    def _scope_candidate_count(accumulator: BatchCandidateAccumulator, scope_key: str) -> int:
        return sum(candidate.scope_key == scope_key for candidate in accumulator.snapshot())

    def _result(
        self,
        state: _ScopeState,
        accumulator: BatchCandidateAccumulator,
        status: BatchScopeStatus,
        error: str | None = None,
    ) -> BatchScopeResult:
        return BatchScopeResult(
            scope_key=state.scope.key,
            status=status,
            entries=state.entries,
            candidate_count=self._scope_candidate_count(accumulator, state.scope.key),
            truncated=status == "truncated",
            error=state.error if error is None else error,
        )

    def _output(
        self,
        scope_results: list[BatchScopeResult],
        accumulator: BatchCandidateAccumulator,
        total_entries: int,
        started: float,
    ) -> BatchScanOutput:
        return BatchScanOutput(
            scope_results=tuple(scope_results),
            candidates=accumulator.snapshot(),
            total_entries=total_entries,
            elapsed_seconds=max(0.0, self._clock() - started),
        )


def _cancel_reason(error: TaskCancelled) -> BatchCancelReason:
    reason = getattr(error, "reason", "user")
    if reason not in {"user", "shutdown"}:
        return "user"
    return cast(BatchCancelReason, reason)
