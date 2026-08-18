"""Layered, cancellable analysis for one discovered game directory."""

from __future__ import annotations

import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from gameshelf.bridge.tasks import TaskContext
from gameshelf.engines.models import DetectionOutcome, EngineEvidence
from gameshelf.library.models import Game
from gameshelf.scanning.analysis_cache import (
    AnalysisCacheEntry,
    PendingAnalysisCache,
)
from gameshelf.scanning.executable_ranker import (
    RANKER_RULES_VERSION,
    ExecutableCandidate,
    rank_executables,
)
from gameshelf.scanning.models import DirectoryCandidate
from gameshelf.scanning.path_keys import PathTraversalError, expand_relative
from gameshelf.scanning.pe_metadata import PeMetadata, read_pe_metadata

type AnalysisKind = Literal["reuse", "refresh_engine", "refresh_executable", "full"]

_REPARSE_FLAG = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class EngineDetector(Protocol):
    @property
    def cache_version(self) -> str: ...

    def detect(self, game_dir: Path, executable: Path | None) -> DetectionOutcome: ...


@dataclass(frozen=True)
class ExecutableFingerprint:
    relative_path: str
    file_size: int
    modified_time_ns: int


@dataclass(frozen=True)
class AnalysisPlan:
    kind: AnalysisKind
    executable: Path | None


@dataclass(frozen=True)
class AnalyzedCandidate:
    payload: dict[str, object]
    pending_cache: PendingAnalysisCache | None
    analysis_kind: AnalysisKind
    warning_count: int


def choose_analysis_plan(
    game_dir: Path,
    existing: Game | None,
    cache: AnalysisCacheEntry | None,
    *,
    ranker_rules_version: str,
    engine_rules_version: str,
) -> AnalysisPlan:
    """Choose the cheapest analysis path that can safely reuse existing results."""

    if existing is None or cache is None or existing.main_exe_relpath is None:
        return AnalysisPlan("full", None)
    if existing.main_exe_relpath != cache.executable_relpath:
        return AnalysisPlan("full", None)
    try:
        executable = expand_relative(game_dir, existing.main_exe_relpath)
    except PathTraversalError:
        return AnalysisPlan("full", None)
    fingerprint = _fingerprint(executable, game_dir)
    if fingerprint is None:
        return AnalysisPlan("full", None)
    if cache.ranker_rules_version != ranker_rules_version:
        return AnalysisPlan("full", None)
    if (
        cache.file_size != fingerprint.file_size
        or cache.modified_time_ns != fingerprint.modified_time_ns
    ):
        return AnalysisPlan("refresh_executable", executable)
    if cache.engine_rules_version != engine_rules_version:
        return AnalysisPlan("refresh_engine", executable)
    return AnalysisPlan("reuse", executable)


class _NoEngineDetector:
    cache_version = "none"

    def detect(self, game_dir: Path, executable: Path | None) -> DetectionOutcome:
        return DetectionOutcome(None, (), False)


class GameAnalyzer:
    def __init__(
        self,
        engine_detection: EngineDetector | None,
        *,
        ranker: Callable[[Path], tuple[ExecutableCandidate, ...]] = rank_executables,
        pe_reader: Callable[[Path], PeMetadata] = read_pe_metadata,
        ranker_rules_version: str = RANKER_RULES_VERSION,
    ) -> None:
        self._engine_detection: EngineDetector = engine_detection or _NoEngineDetector()
        self._ranker = ranker
        self._pe_reader = pe_reader
        self._ranker_rules_version = ranker_rules_version

    def analyze(
        self,
        candidate: DirectoryCandidate,
        existing: Game | None,
        cache: AnalysisCacheEntry | None,
        context: TaskContext,
    ) -> AnalyzedCandidate:
        context.raise_if_cancelled()
        plan = choose_analysis_plan(
            candidate.path,
            existing,
            cache,
            ranker_rules_version=self._ranker_rules_version,
            engine_rules_version=self._engine_detection.cache_version,
        )
        context.raise_if_cancelled()

        if plan.kind == "reuse":
            assert existing is not None and cache is not None
            return AnalyzedCandidate(
                payload=_existing_payload(existing),
                pending_cache=_pending_from_entry(cache),
                analysis_kind="reuse",
                warning_count=0,
            )

        if plan.kind in {"refresh_engine", "refresh_executable"}:
            assert existing is not None and plan.executable is not None
            architecture = existing.exe_arch
            if plan.kind == "refresh_executable":
                context.raise_if_cancelled()
                architecture = self._pe_reader(plan.executable).architecture
                context.raise_if_cancelled()
            context.raise_if_cancelled()
            detection = self._engine_detection.detect(candidate.path, plan.executable)
            context.raise_if_cancelled()
            detection_payload = _engine_payload(detection)
            return AnalyzedCandidate(
                payload={
                    "mainExeRelpath": existing.detected_main_exe_relpath,
                    "exeArch": architecture,
                    **detection_payload,
                },
                pending_cache=(
                    None
                    if detection_payload["engineDetectionFailed"] is True
                    else self._pending_cache(plan.executable, candidate.path)
                ),
                analysis_kind=plan.kind,
                warning_count=len(detection.diagnostics),
            )

        context.raise_if_cancelled()
        ranked = self._ranker(candidate.path)
        recommendation = ranked[0] if ranked else None
        automatic_executable = (
            candidate.path.joinpath(*recommendation.relative_path.split("/"))
            if recommendation is not None
            else None
        )
        executable, manual_warning = _detection_executable(
            candidate.path, existing, automatic_executable
        )
        context.raise_if_cancelled()
        detection = self._engine_detection.detect(candidate.path, executable)
        context.raise_if_cancelled()
        detection_payload = _engine_payload(detection)
        return AnalyzedCandidate(
            payload={
                "mainExeRelpath": (
                    recommendation.relative_path if recommendation is not None else None
                ),
                "exeArch": (
                    recommendation.architecture
                    if recommendation is not None
                    else "unknown"
                ),
                **detection_payload,
            },
            pending_cache=(
                self._pending_cache(executable, candidate.path)
                if executable is not None
                and detection_payload["engineDetectionFailed"] is not True
                else None
            ),
            analysis_kind="full",
            warning_count=int(manual_warning) + len(detection.diagnostics),
        )

    def _pending_cache(
        self,
        executable: Path,
        game_dir: Path,
    ) -> PendingAnalysisCache | None:
        fingerprint = _fingerprint(executable, game_dir)
        if fingerprint is None:
            return None
        return PendingAnalysisCache(
            executable_relpath=fingerprint.relative_path,
            file_size=fingerprint.file_size,
            modified_time_ns=fingerprint.modified_time_ns,
            ranker_rules_version=self._ranker_rules_version,
            engine_rules_version=self._engine_detection.cache_version,
        )


def _pending_from_entry(entry: AnalysisCacheEntry) -> PendingAnalysisCache:
    return PendingAnalysisCache(
        executable_relpath=entry.executable_relpath,
        file_size=entry.file_size,
        modified_time_ns=entry.modified_time_ns,
        ranker_rules_version=entry.ranker_rules_version,
        engine_rules_version=entry.engine_rules_version,
    )


def _existing_payload(existing: Game) -> dict[str, object]:
    evidence_codes = {item.code for item in existing.engine_evidence}
    detection_failed = (
        existing.detected_engine_id is None
        and "detector_error" in evidence_codes
        and not any(code.startswith("candidate:") for code in evidence_codes)
    )
    return {
        "mainExeRelpath": existing.detected_main_exe_relpath,
        "exeArch": existing.exe_arch,
        "engineDetectionFailed": detection_failed,
        "detectedEngineId": existing.detected_engine_id,
        "detectedEngineVariant": existing.detected_engine_variant,
        "engineConfidence": existing.engine_confidence,
        "engineEvidence": [_evidence_dto(item) for item in existing.engine_evidence],
        "engineRulesVersion": existing.engine_rules_version,
    }


def _engine_payload(outcome: DetectionOutcome) -> dict[str, object]:
    match = outcome.best
    evidence: tuple[EngineEvidence, ...]
    if match is not None:
        evidence = match.evidence
    elif outcome.ambiguous:
        evidence = tuple(
            EngineEvidence(
                code=f"candidate:{candidate.engine_id}",
                detail=candidate.variant or candidate.engine_id,
                weight=candidate.confidence,
            )
            for candidate in outcome.alternatives
        )
    else:
        evidence = ()
    return {
        "engineDetectionFailed": bool(outcome.diagnostics)
        and match is None
        and not outcome.ambiguous,
        "detectedEngineId": match.engine_id if match is not None else None,
        "detectedEngineVariant": match.variant if match is not None else None,
        "engineConfidence": (
            match.confidence
            if match is not None
            else max(
                (candidate.confidence for candidate in outcome.alternatives),
                default=None,
            )
        ),
        "engineEvidence": [
            _evidence_dto(item) for item in (*evidence, *outcome.diagnostics)
        ],
        "engineRulesVersion": (
            match.rule_version
            if match is not None
            else ",".join(
                dict.fromkeys(
                    candidate.rule_version for candidate in outcome.alternatives
                )
            )
            or None
        ),
    }


def _evidence_dto(item: EngineEvidence) -> dict[str, object]:
    return {
        "code": item.code,
        "detail": item.detail,
        "path": item.path,
        "weight": item.weight,
    }


def _detection_executable(
    game_dir: Path,
    existing: Game | None,
    automatic: Path | None,
) -> tuple[Path | None, bool]:
    if existing is None or not existing.main_exe_is_manual:
        return automatic, False
    relative = existing.main_exe_relpath
    if relative is None:
        return automatic, True
    try:
        selected = expand_relative(game_dir, relative)
    except PathTraversalError:
        return automatic, True
    if selected.suffix.casefold() != ".exe" or _fingerprint(selected, game_dir) is None:
        return automatic, True
    return selected, False


def _fingerprint(path: Path, root: Path) -> ExecutableFingerprint | None:
    if path.suffix.casefold() != ".exe":
        return None
    try:
        relative = path.relative_to(root)
        info = path.stat(follow_symlinks=False)
        resolved_root = root.resolve(strict=True)
        resolved_path = path.resolve(strict=True)
    except (OSError, ValueError):
        return None
    if not stat.S_ISREG(info.st_mode) or not resolved_path.is_relative_to(resolved_root):
        return None
    current = root
    for part in relative.parts:
        current /= part
        try:
            item_info = current.stat(follow_symlinks=False)
        except OSError:
            return None
        if current.is_symlink() or bool(
            getattr(item_info, "st_file_attributes", 0) & _REPARSE_FLAG
        ):
            return None
    return ExecutableFingerprint(relative.as_posix(), info.st_size, info.st_mtime_ns)
