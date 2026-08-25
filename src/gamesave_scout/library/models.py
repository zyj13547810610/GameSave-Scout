"""Immutable values returned by the game-library boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from gamesave_scout.engines.models import EngineEvidence

type ScanMode = Literal["children", "recursive"]
type GameStatus = Literal["installed", "missing", "save_only"]
type RemovableGameStatus = Literal["installed", "missing"]
type ExecutableArchitecture = Literal["x86", "x64", "unknown"]


@dataclass(frozen=True)
class ScanRoot:
    id: str
    display_path: str
    path_key: str
    enabled: bool
    scan_mode: ScanMode
    max_depth: int
    exclusions: tuple[str, ...]
    last_scanned_at: str | None
    last_scan_status: str
    last_error: str | None
    created_at: str


@dataclass(frozen=True)
class Game:
    id: str
    scan_root_id: str | None
    relative_dir: str | None
    install_path_key: str | None
    title: str
    detected_title: str | None
    status: GameStatus
    detected_engine_id: str | None
    detected_engine_variant: str | None
    engine_id: str | None
    engine_variant: str | None
    engine_is_manual: bool
    engine_confidence: float | None
    engine_evidence: tuple[EngineEvidence, ...]
    engine_rules_version: str | None
    main_exe_relpath: str | None
    main_exe_is_manual: bool
    working_dir_relpath: str | None
    launch_args: tuple[str, ...]
    environment: Mapping[str, str]
    exe_arch: ExecutableArchitecture
    cover_original_relpath: str | None
    cover_thumb_relpath: str | None
    cover_revision: int
    last_launched_at: str | None
    missing_since: str | None
    version: str | None = None
    detected_version: str | None = None
    detected_main_exe_relpath: str | None = None
    group_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class GameRemovalRequest:
    game_id: str
    expected_status: RemovableGameStatus


@dataclass(frozen=True)
class BatchGameRemovalResult:
    installed_count: int
    missing_count: int
    updated_roots: tuple[ScanRoot, ...]
    managed_cover_relpaths: tuple[str, ...]

    @property
    def updated_root_ids(self) -> tuple[str, ...]:
        return tuple(root.id for root in self.updated_roots)
