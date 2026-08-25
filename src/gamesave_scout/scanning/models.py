"""Values emitted by game-directory discovery."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

type DiscoveryReason = Literal["direct_child", "generic_executable"]


@dataclass(frozen=True)
class DirectoryCandidate:
    path: Path
    relative_dir: str
    depth: int
    reason: DiscoveryReason
