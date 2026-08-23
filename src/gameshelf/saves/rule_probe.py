"""Bounded existence probing shared by declarative save-rule consumers."""

from __future__ import annotations

import os
import re
import stat
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Protocol

from gameshelf.saves.models import SaveLocationKind
from gameshelf.saves.templates import InvalidPathTemplate, PathTemplateResolver

MAX_RULE_PROBE_DEPTH = 8
MAX_RULE_PROBE_ENTRIES = 10_000
MAX_RULE_PROBE_MATCHES = 256
RULE_PROBE_DEADLINE_SECONDS = 2.0
_TEMPLATE = re.compile(r"^(<[^<>\\/]+>)(?:[\\/](.*))?$")
_REGISTRY_ROOTS = ("HKEY_CURRENT_USER\\", "HKEY_LOCAL_MACHINE\\")
_REPARSE_FLAG = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)

type ReparsePointCheck = Callable[[Path], bool]


@dataclass(frozen=True, slots=True)
class RuleProbeResult:
    matches: tuple[str, ...]
    truncated: bool
    diagnostics: tuple[str, ...]

    @property
    def found(self) -> bool:
        return bool(self.matches)


class RegistryKeyProbe(Protocol):
    def key_exists(self, key: str) -> bool: ...


class BoundedRuleProbe:
    def __init__(
        self,
        resolver: PathTemplateResolver,
        registry: RegistryKeyProbe,
        *,
        max_depth: int = MAX_RULE_PROBE_DEPTH,
        max_entries: int = MAX_RULE_PROBE_ENTRIES,
        max_matches: int = MAX_RULE_PROBE_MATCHES,
        deadline_seconds: float = RULE_PROBE_DEADLINE_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
        is_reparse_point: ReparsePointCheck | None = None,
    ) -> None:
        self._resolver = resolver
        self._registry = registry
        self._max_depth = max_depth
        self._max_entries = max_entries
        self._max_matches = max_matches
        self._deadline_seconds = deadline_seconds
        self._monotonic = monotonic
        self._is_reparse_point = is_reparse_point or _is_reparse_point

    def probe(
        self,
        kind: SaveLocationKind,
        path_template: str,
        install_dir: Path | None,
    ) -> RuleProbeResult:
        if kind == "registry":
            return self._probe_registry(path_template)
        match = _TEMPLATE.fullmatch(path_template)
        if match is None:
            return RuleProbeResult((), False, ("invalid_path_template",))
        token, suffix = match.groups()
        try:
            token_root = self._resolver.expand(token, install_dir)
        except InvalidPathTemplate:
            return RuleProbeResult((), False, ("invalid_path_template",))
        if _is_network_or_device(token_root):
            return RuleProbeResult((), False, ("network_or_device_root_rejected",))
        if self._unsafe_path(token_root, token_root):
            return RuleProbeResult((), True, ("reparse_point_skipped",))
        if kind != "glob":
            return self._probe_literal(kind, path_template, install_dir, token_root)
        return self._probe_glob(token_root, suffix or "")

    def _probe_registry(self, key: str) -> RuleProbeResult:
        normalized = key.replace("/", "\\")
        if not normalized.upper().startswith(_REGISTRY_ROOTS):
            return RuleProbeResult((), False, ("invalid_registry_key",))
        try:
            found = self._registry.key_exists(normalized)
        except (OSError, RuntimeError, ValueError):
            return RuleProbeResult((), False, ("registry_probe_failed",))
        return RuleProbeResult((normalized,) if found else (), False, ())

    def _probe_literal(
        self,
        kind: SaveLocationKind,
        template: str,
        install_dir: Path | None,
        token_root: Path,
    ) -> RuleProbeResult:
        try:
            target = self._resolver.expand(template, install_dir)
        except InvalidPathTemplate:
            return RuleProbeResult((), False, ("invalid_path_template",))
        if _is_network_or_device(target):
            return RuleProbeResult((), False, ("network_or_device_root_rejected",))
        if self._unsafe_path(token_root, target):
            return RuleProbeResult((), True, ("reparse_point_skipped",))
        try:
            found = target.is_dir() if kind == "directory" else target.is_file()
        except OSError:
            return RuleProbeResult((), False, ("filesystem_probe_failed",))
        return RuleProbeResult((str(target),) if found else (), False, ())

    def _probe_glob(self, token_root: Path, relative_pattern: str) -> RuleProbeResult:
        clean_pattern = relative_pattern.replace("/", "\\").strip("\\")
        parts = PureWindowsPath(clean_pattern).parts
        fixed: list[str] = []
        for part in parts:
            if any(character in part for character in "*?[") or part == "**":
                break
            fixed.append(part)
        search_root = token_root.joinpath(*fixed)
        if not search_root.is_dir() or self._unsafe_path(token_root, search_root):
            return RuleProbeResult((), False, ())

        started = self._monotonic()
        stack = [search_root]
        visited = 0
        matches: list[str] = []
        diagnostics: list[str] = []
        truncated = False
        while stack:
            if self._monotonic() - started >= self._deadline_seconds:
                diagnostics.append("deadline_reached")
                truncated = True
                break
            directory = stack.pop()
            try:
                children = sorted(directory.iterdir(), key=lambda path: path.name.casefold())
            except OSError:
                diagnostics.append("filesystem_probe_failed")
                continue
            for child in children:
                visited += 1
                if visited > self._max_entries:
                    diagnostics.append("entry_limit_reached")
                    truncated = True
                    stack.clear()
                    break
                try:
                    relative = child.relative_to(token_root)
                except ValueError:
                    continue
                depth = len(relative.parts)
                if self._is_reparse_point(child):
                    if "reparse_point_skipped" not in diagnostics:
                        diagnostics.append("reparse_point_skipped")
                    truncated = True
                    continue
                try:
                    is_dir = child.is_dir()
                except OSError:
                    diagnostics.append("filesystem_probe_failed")
                    continue
                if PureWindowsPath(*relative.parts).match(clean_pattern):
                    matches.append(str(child))
                    if len(matches) >= self._max_matches:
                        diagnostics.append("match_limit_reached")
                        truncated = True
                        stack.clear()
                        break
                if is_dir:
                    if depth < self._max_depth:
                        stack.append(child)
                    elif any(part == "**" for part in parts):
                        diagnostics.append("depth_limit_reached")
                        truncated = True
        return RuleProbeResult(
            tuple(matches),
            truncated,
            tuple(dict.fromkeys(diagnostics)),
        )

    def _unsafe_path(self, root: Path, target: Path) -> bool:
        try:
            relative = target.relative_to(root)
        except ValueError:
            return True
        current = root
        if self._is_reparse_point(current):
            return True
        for part in relative.parts:
            current /= part
            if current.exists() and self._is_reparse_point(current):
                return True
        return False


def _is_network_or_device(path: Path) -> bool:
    value = os.fspath(path).replace("/", "\\")
    return value.startswith(("\\\\", "\\?\\", "\\.\\"))


def _is_reparse_point(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    return path.is_symlink() or bool(
        getattr(metadata, "st_file_attributes", 0) & _REPARSE_FLAG
    )
