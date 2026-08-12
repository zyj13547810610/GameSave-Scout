"""Versioned JSON configuration stored beneath the portable data directory."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4


class InvalidConfigError(ValueError):
    """Raised when an existing configuration cannot be safely interpreted."""


@dataclass(frozen=True)
class AppConfig:
    version: int = 1
    language: str = "zh-CN"
    startup_quick_scan: bool = True
    orphan_scan_exclusions: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "language": self.language,
            "startupQuickScan": self.startup_quick_scan,
            "orphanScanExclusions": list(self.orphan_scan_exclusions),
        }


class JsonConfigStore:
    """Load and atomically save the user-editable GameShelf configuration."""

    _ALLOWED_KEYS = {
        "version",
        "language",
        "startupQuickScan",
        "orphanScanExclusions",
    }

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> AppConfig:
        if not self._path.exists():
            return AppConfig()
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            return self._parse(raw)
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as error:
            if isinstance(error, InvalidConfigError):
                raise
            raise InvalidConfigError(
                f"配置文件无效，已保留原文件供手动恢复：{self._path}"
            ) from error

    def save(self, config: AppConfig) -> None:
        temp_dir = self._path.parent / "temp"
        temp_file = temp_dir / f"config-{uuid4()}.json"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            with temp_file.open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(config.to_json(), stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            self._path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(temp_file, self._path)
        except OSError:
            temp_file.unlink(missing_ok=True)
            raise

    @classmethod
    def _parse(cls, raw: object) -> AppConfig:
        if not isinstance(raw, dict) or not set(raw).issubset(cls._ALLOWED_KEYS):
            raise InvalidConfigError("配置文件无效：顶层结构或字段不受支持。")

        version = raw.get("version", 1)
        language = raw.get("language", "zh-CN")
        startup_quick_scan = raw.get("startupQuickScan", True)
        exclusions = raw.get("orphanScanExclusions", [])

        if type(version) is not int or version != 1:
            raise InvalidConfigError("配置文件无效：不支持的版本。")
        if not isinstance(language, str) or not language:
            raise InvalidConfigError("配置文件无效：语言必须是非空字符串。")
        if not isinstance(startup_quick_scan, bool):
            raise InvalidConfigError("配置文件无效：启动扫描开关必须是布尔值。")
        if not isinstance(exclusions, list) or not all(
            isinstance(item, str) for item in exclusions
        ):
            raise InvalidConfigError("配置文件无效：孤立存档排除项必须是字符串数组。")

        return AppConfig(
            version=version,
            language=language,
            startup_quick_scan=startup_quick_scan,
            orphan_scan_exclusions=tuple(exclusions),
        )
