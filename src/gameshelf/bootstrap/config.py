"""Versioned JSON configuration stored beneath the portable data directory."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)
UI_SCALE_OPTIONS = frozenset({0.8, 0.9, 1.0, 1.1, 1.2})
COVER_VNDB_LIMIT_RANGE = range(1, 21)
COVER_LOCAL_LIMIT_RANGE = range(1, 101)


class InvalidConfigError(ValueError):
    """Raised when an existing configuration cannot be safely interpreted."""


class InvalidUiScaleError(ValueError):
    """Raised when a requested UI scale is outside the supported options."""


class InvalidCoverWizardSettingsError(ValueError):
    """Raised when cover wizard settings are outside the supported limits."""


@dataclass(frozen=True)
class AppConfig:
    version: int = 3
    language: str = "zh-CN"
    startup_quick_scan: bool = True
    orphan_scan_exclusions: tuple[str, ...] = ()
    ui_scale: float = 1.0
    cover_online_enabled: bool = False
    cover_vndb_candidate_limit: int = 5
    cover_local_scan_candidate_limit: int = 10

    def to_json(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "language": self.language,
            "startupQuickScan": self.startup_quick_scan,
            "orphanScanExclusions": list(self.orphan_scan_exclusions),
            "uiScale": self.ui_scale,
            "coverOnlineEnabled": self.cover_online_enabled,
            "coverVndbCandidateLimit": self.cover_vndb_candidate_limit,
            "coverLocalScanCandidateLimit": self.cover_local_scan_candidate_limit,
        }


class JsonConfigStore:
    """Load and atomically save the user-editable GameShelf configuration."""

    _ALLOWED_KEYS = {
        "version",
        "language",
        "startupQuickScan",
        "orphanScanExclusions",
        "uiScale",
        "coverOnlineEnabled",
        "coverVndbCandidateLimit",
        "coverLocalScanCandidateLimit",
    }

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> AppConfig:
        if not self._path.exists():
            config = AppConfig()
            self._save_normalized(config)
            return config
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            config, needs_save = self._parse(raw)
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as error:
            if isinstance(error, InvalidConfigError):
                raise
            raise InvalidConfigError(
                f"配置文件无效，已保留原文件供手动恢复：{self._path}"
            ) from error
        if needs_save:
            self._save_normalized(config)
        return config

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
    def _parse(cls, raw: object) -> tuple[AppConfig, bool]:
        if not isinstance(raw, dict) or not set(raw).issubset(cls._ALLOWED_KEYS):
            raise InvalidConfigError("配置文件无效：顶层结构或字段不受支持。")

        version = raw.get("version", 1)
        language = raw.get("language", "zh-CN")
        startup_quick_scan = raw.get("startupQuickScan", True)
        exclusions = raw.get("orphanScanExclusions", [])
        ui_scale = raw.get("uiScale", 1.0)
        cover_online_enabled = raw.get("coverOnlineEnabled", False)
        cover_vndb_candidate_limit = raw.get("coverVndbCandidateLimit", 5)
        cover_local_scan_candidate_limit = raw.get("coverLocalScanCandidateLimit", 10)

        if type(version) is not int or version not in {1, 2, 3}:
            raise InvalidConfigError("配置文件无效：不支持的版本。")
        if not isinstance(language, str) or not language:
            raise InvalidConfigError("配置文件无效：语言必须是非空字符串。")
        if not isinstance(startup_quick_scan, bool):
            raise InvalidConfigError("配置文件无效：启动扫描开关必须是布尔值。")
        if not isinstance(exclusions, list) or not all(
            isinstance(item, str) for item in exclusions
        ):
            raise InvalidConfigError("配置文件无效：孤立存档排除项必须是字符串数组。")

        valid_ui_scale = type(ui_scale) in {int, float} and float(ui_scale) in UI_SCALE_OPTIONS
        normalized_ui_scale = float(ui_scale) if valid_ui_scale else 1.0
        if not valid_ui_scale:
            logger.warning("配置中的 uiScale 无效，已在本次运行中回退到 100%。")
        valid_online_enabled = isinstance(cover_online_enabled, bool)
        normalized_online_enabled = (
            cover_online_enabled if valid_online_enabled else False
        )
        if not valid_online_enabled:
            logger.warning("配置中的 coverOnlineEnabled 无效，已回退为关闭。")

        valid_vndb_limit = (
            type(cover_vndb_candidate_limit) is int
            and cover_vndb_candidate_limit in COVER_VNDB_LIMIT_RANGE
        )
        normalized_vndb_limit = cover_vndb_candidate_limit if valid_vndb_limit else 5
        if not valid_vndb_limit:
            logger.warning("配置中的 coverVndbCandidateLimit 无效，已回退为 5。")

        valid_local_limit = (
            type(cover_local_scan_candidate_limit) is int
            and cover_local_scan_candidate_limit in COVER_LOCAL_LIMIT_RANGE
        )
        normalized_local_limit = (
            cover_local_scan_candidate_limit if valid_local_limit else 10
        )
        if not valid_local_limit:
            logger.warning("配置中的 coverLocalScanCandidateLimit 无效，已回退为 10。")

        config = AppConfig(
            version=3,
            language=language,
            startup_quick_scan=startup_quick_scan,
            orphan_scan_exclusions=tuple(exclusions),
            ui_scale=normalized_ui_scale,
            cover_online_enabled=normalized_online_enabled,
            cover_vndb_candidate_limit=normalized_vndb_limit,
            cover_local_scan_candidate_limit=normalized_local_limit,
        )
        needs_save = (
            version != 3
            or raw.get("uiScale") != normalized_ui_scale
            or raw.get("coverOnlineEnabled") != normalized_online_enabled
            or raw.get("coverVndbCandidateLimit") != normalized_vndb_limit
            or raw.get("coverLocalScanCandidateLimit") != normalized_local_limit
        )
        return config, needs_save

    def _save_normalized(self, config: AppConfig) -> None:
        try:
            self.save(config)
        except OSError:
            logger.warning("无法写回规范化配置，本次运行继续使用内存中的设置。")


class ConfigService:
    """Hold the current portable configuration and persist validated updates."""

    def __init__(self, store: JsonConfigStore) -> None:
        self._store = store
        self._current = store.load()
        self._lock = Lock()

    @property
    def current(self) -> AppConfig:
        with self._lock:
            return self._current

    def set_ui_scale(self, value: object) -> AppConfig:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or float(value) not in UI_SCALE_OPTIONS
        ):
            raise InvalidUiScaleError("界面缩放必须是 80%、90%、100%、110% 或 120%。")
        with self._lock:
            updated = replace(self._current, ui_scale=float(value))
            self._store.save(updated)
            self._current = updated
            return updated

    def set_cover_wizard_settings(
        self,
        *,
        online_enabled: object,
        vndb_candidate_limit: object,
        local_scan_candidate_limit: object,
    ) -> AppConfig:
        if not isinstance(online_enabled, bool):
            raise InvalidCoverWizardSettingsError("封面在线搜索开关必须是布尔值。")
        if (
            type(vndb_candidate_limit) is not int
            or vndb_candidate_limit not in COVER_VNDB_LIMIT_RANGE
        ):
            raise InvalidCoverWizardSettingsError("封面 VNDB 候选数量必须为 1 到 20。")
        if (
            type(local_scan_candidate_limit) is not int
            or local_scan_candidate_limit not in COVER_LOCAL_LIMIT_RANGE
        ):
            raise InvalidCoverWizardSettingsError("封面本地扫描数量必须为 1 到 100。")
        with self._lock:
            updated = replace(
                self._current,
                cover_online_enabled=online_enabled,
                cover_vndb_candidate_limit=vndb_candidate_limit,
                cover_local_scan_candidate_limit=local_scan_candidate_limit,
            )
            self._store.save(updated)
            self._current = updated
            return updated
