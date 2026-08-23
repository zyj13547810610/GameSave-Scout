"""Immutable metadata shared by declarative rule catalogs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type RuleSource = Literal["builtin", "user"]
type RuleStatus = Literal["formal", "experimental"]
type RuleType = Literal["engine", "save_game", "save_engine"]


@dataclass(frozen=True, slots=True)
class RuleMetadata:
    rule_id: str
    rule_type: RuleType
    source: RuleSource
    status: RuleStatus
    version: str
    references: tuple[str, ...]
    priority: int
    enabled: bool

    @property
    def namespace(self) -> RuleSource:
        return self.source

    @property
    def qualified_id(self) -> str:
        return f"{self.namespace}:{self.rule_id}"

    @property
    def verification_label(self) -> str:
        if self.status == "experimental":
            return "实验"
        return "正式" if self.source == "builtin" else "已验证"
