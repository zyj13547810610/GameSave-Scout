"""Immutable values returned by the game-group boundary."""

from dataclasses import dataclass
from typing import Literal

type GroupMembershipMode = Literal["add", "remove"]


@dataclass(frozen=True)
class GameGroup:
    id: str
    name: str
    game_count: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class GroupMembershipUpdateResult:
    added_count: int
    removed_count: int
    unchanged_count: int
