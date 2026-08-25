"""Strict, degradable local settings for bundled declarative rules."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from gamesave_scout.rules.models import RuleDiagnostic


@dataclass(frozen=True, slots=True)
class RuleSettings:
    version: int = 1
    disabled_builtin_rule_ids: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class RuleSettingsLoadResult:
    settings: RuleSettings
    diagnostics: tuple[RuleDiagnostic, ...]


class RuleSettingsStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self, known_builtin_rule_ids: frozenset[str]) -> RuleSettingsLoadResult:
        if not self._path.exists():
            return RuleSettingsLoadResult(RuleSettings(), ())
        try:
            content = self._path.read_text(encoding="utf-8")
            settings = parse_rule_settings(
                json.loads(content),
                known_builtin_rule_ids=known_builtin_rule_ids,
            )
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            return RuleSettingsLoadResult(
                RuleSettings(),
                (
                    RuleDiagnostic(
                        severity="warning",
                        code="invalid_rule_settings",
                        message=f"规则设置无效，已忽略全部内置禁用项：{error}",
                        source_name=self._path.name,
                    ),
                ),
            )
        return RuleSettingsLoadResult(settings, ())

    def save(self, settings: RuleSettings) -> None:
        payload = {
            "version": settings.version,
            "disabledBuiltinRuleIds": sorted(settings.disabled_builtin_rule_ids),
        }
        content = (
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.parent / f"settings-{uuid4()}.tmp"
        try:
            with temporary.open("xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._path)
        except OSError:
            temporary.unlink(missing_ok=True)
            raise


def parse_rule_settings(
    raw: object,
    *,
    known_builtin_rule_ids: frozenset[str],
) -> RuleSettings:
    if not isinstance(raw, dict) or set(raw) != {
        "version",
        "disabledBuiltinRuleIds",
    }:
        raise ValueError("顶层结构或字段不受支持。")
    if raw["version"] != 1 or type(raw["version"]) is not int:
        raise ValueError("只支持 version 1。")
    disabled = raw["disabledBuiltinRuleIds"]
    if not isinstance(disabled, list) or not all(
        isinstance(item, str) for item in disabled
    ):
        raise ValueError("disabledBuiltinRuleIds 必须是字符串数组。")
    if len(disabled) != len(set(disabled)):
        raise ValueError("disabledBuiltinRuleIds 不能包含重复项。")
    if any(not item.startswith("builtin:") for item in disabled):
        raise ValueError("只能禁用 builtin: 内置规则。")
    unknown = sorted(set(disabled) - known_builtin_rule_ids)
    if unknown:
        raise ValueError(f"包含未知内置规则：{', '.join(unknown)}")
    return RuleSettings(disabled_builtin_rule_ids=frozenset(disabled))
