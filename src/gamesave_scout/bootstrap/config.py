"""Versioned JSON configuration stored beneath the portable data directory."""

from __future__ import annotations

import json
import logging
import ntpath
import os
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from gamesave_scout.scanning.path_keys import windows_path_key

logger = logging.getLogger(__name__)
UI_SCALE_OPTIONS = frozenset({0.8, 0.9, 1.0, 1.1, 1.2})
COVER_VNDB_LIMIT_RANGE = range(1, 21)
COVER_LOCAL_LIMIT_RANGE = range(1, 101)
SCAN_CONCURRENCY_RANGE = range(1, 5)
BATCH_SAVE_DEPTH_RANGE = range(1, 13)
MAX_BATCH_SAVE_CUSTOM_ROOTS = 32


class InvalidConfigError(ValueError):
    """Raised when an existing configuration cannot be safely interpreted."""


class InvalidUiScaleError(ValueError):
    """Raised when a requested UI scale is outside the supported options."""


class InvalidCoverWizardSettingsError(ValueError):
    """Raised when cover wizard settings are outside the supported limits."""


class InvalidLibraryScanSettingsError(ValueError):
    """Raised when library scan settings are outside the supported limits."""


class InvalidBatchSaveSettingsError(ValueError):
    """Raised when batch save discovery roots are invalid."""


@dataclass(frozen=True, slots=True)
class BatchSaveCustomRoot:
    id: str
    display_path: str
    enabled: bool
    max_depth: int


@dataclass(frozen=True)
class AppConfig:
    version: int = 5
    language: str = "zh-CN"
    startup_quick_scan: bool = True
    scan_concurrency: int = 1
    orphan_scan_exclusions: tuple[str, ...] = ()
    ui_scale: float = 1.0
    cover_online_enabled: bool = False
    cover_vndb_candidate_limit: int = 5
    cover_local_scan_candidate_limit: int = 10
    batch_save_custom_roots: tuple[BatchSaveCustomRoot, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "language": self.language,
            "startupQuickScan": self.startup_quick_scan,
            "scanConcurrency": self.scan_concurrency,
            "orphanScanExclusions": list(self.orphan_scan_exclusions),
            "uiScale": self.ui_scale,
            "coverOnlineEnabled": self.cover_online_enabled,
            "coverVndbCandidateLimit": self.cover_vndb_candidate_limit,
            "coverLocalScanCandidateLimit": self.cover_local_scan_candidate_limit,
            "batchSaveCustomRoots": [
                {
                    "id": root.id,
                    "displayPath": root.display_path,
                    "enabled": root.enabled,
                    "maxDepth": root.max_depth,
                }
                for root in self.batch_save_custom_roots
            ],
        }


class JsonConfigStore:
    """Load and atomically save the user-editable GameSave Scout configuration."""

    _ALLOWED_KEYS = {
        "version",
        "language",
        "startupQuickScan",
        "scanConcurrency",
        "orphanScanExclusions",
        "uiScale",
        "coverOnlineEnabled",
        "coverVndbCandidateLimit",
        "coverLocalScanCandidateLimit",
        "batchSaveCustomRoots",
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
        scan_concurrency = raw.get("scanConcurrency", 1)
        exclusions = raw.get("orphanScanExclusions", [])
        ui_scale = raw.get("uiScale", 1.0)
        cover_online_enabled = raw.get("coverOnlineEnabled", False)
        cover_vndb_candidate_limit = raw.get("coverVndbCandidateLimit", 5)
        cover_local_scan_candidate_limit = raw.get("coverLocalScanCandidateLimit", 10)
        batch_save_custom_roots = _parse_batch_save_custom_roots(
            raw.get("batchSaveCustomRoots", [])
        )

        if type(version) is not int or version not in {1, 2, 3, 4, 5}:
            raise InvalidConfigError("配置文件无效：不支持的版本。")
        if not isinstance(language, str) or not language:
            raise InvalidConfigError("配置文件无效：语言必须是非空字符串。")
        if not isinstance(startup_quick_scan, bool):
            raise InvalidConfigError("配置文件无效：启动扫描开关必须是布尔值。")
        valid_scan_concurrency = (
            type(scan_concurrency) is int
            and scan_concurrency in SCAN_CONCURRENCY_RANGE
        )
        normalized_scan_concurrency = scan_concurrency if valid_scan_concurrency else 1
        if not valid_scan_concurrency:
            logger.warning("配置中的 scanConcurrency 无效，已回退为 1。")
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
            version=5,
            language=language,
            startup_quick_scan=startup_quick_scan,
            scan_concurrency=normalized_scan_concurrency,
            orphan_scan_exclusions=tuple(exclusions),
            ui_scale=normalized_ui_scale,
            cover_online_enabled=normalized_online_enabled,
            cover_vndb_candidate_limit=normalized_vndb_limit,
            cover_local_scan_candidate_limit=normalized_local_limit,
            batch_save_custom_roots=batch_save_custom_roots,
        )
        needs_save = (
            version != 5
            or raw.get("scanConcurrency") != normalized_scan_concurrency
            or raw.get("uiScale") != normalized_ui_scale
            or raw.get("coverOnlineEnabled") != normalized_online_enabled
            or raw.get("coverVndbCandidateLimit") != normalized_vndb_limit
            or raw.get("coverLocalScanCandidateLimit") != normalized_local_limit
            or raw.get("batchSaveCustomRoots")
            != config.to_json()["batchSaveCustomRoots"]
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

    def set_library_scan_settings(
        self,
        *,
        startup_quick_scan: object,
        scan_concurrency: object,
    ) -> AppConfig:
        if not isinstance(startup_quick_scan, bool):
            raise InvalidLibraryScanSettingsError("启动时快速核验开关必须是布尔值。")
        if (
            type(scan_concurrency) is not int
            or scan_concurrency not in SCAN_CONCURRENCY_RANGE
        ):
            raise InvalidLibraryScanSettingsError("扫描并发数必须为 1 到 4。")
        with self._lock:
            updated = replace(
                self._current,
                startup_quick_scan=startup_quick_scan,
                scan_concurrency=scan_concurrency,
            )
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

    def add_batch_save_custom_root(
        self,
        display_path: object,
        *,
        enabled: object,
        max_depth: object,
    ) -> BatchSaveCustomRoot:
        root = _normalize_batch_save_custom_root(
            root_id=str(uuid4()),
            display_path=display_path,
            enabled=enabled,
            max_depth=max_depth,
            error_type=InvalidBatchSaveSettingsError,
        )
        with self._lock:
            current_roots = self._current.batch_save_custom_roots
            if len(current_roots) >= MAX_BATCH_SAVE_CUSTOM_ROOTS:
                raise InvalidBatchSaveSettingsError("批量存档自定义目录最多保存 32 个。")
            if any(
                windows_path_key(item.display_path)
                == windows_path_key(root.display_path)
                for item in current_roots
            ):
                raise InvalidBatchSaveSettingsError("批量存档自定义目录不能重复。")
            updated = replace(
                self._current,
                batch_save_custom_roots=(*current_roots, root),
            )
            self._store.save(updated)
            self._current = updated
            return root

    def update_batch_save_custom_root(
        self,
        root_id: object,
        *,
        enabled: object,
        max_depth: object,
    ) -> BatchSaveCustomRoot:
        if not isinstance(root_id, str) or not root_id.strip() or "\x00" in root_id:
            raise InvalidBatchSaveSettingsError("批量存档自定义目录 ID 无效。")
        with self._lock:
            try:
                existing = next(
                    item
                    for item in self._current.batch_save_custom_roots
                    if item.id == root_id
                )
            except StopIteration as error:
                raise InvalidBatchSaveSettingsError(
                    "没有找到对应的批量存档自定义目录。"
                ) from error
            replacement = _normalize_batch_save_custom_root(
                root_id=existing.id,
                display_path=existing.display_path,
                enabled=enabled,
                max_depth=max_depth,
                error_type=InvalidBatchSaveSettingsError,
            )
            updated = replace(
                self._current,
                batch_save_custom_roots=tuple(
                    replacement if item.id == root_id else item
                    for item in self._current.batch_save_custom_roots
                ),
            )
            self._store.save(updated)
            self._current = updated
            return replacement

    def remove_batch_save_custom_root(self, root_id: object) -> bool:
        if not isinstance(root_id, str) or not root_id.strip() or "\x00" in root_id:
            raise InvalidBatchSaveSettingsError("批量存档自定义目录 ID 无效。")
        with self._lock:
            remaining = tuple(
                item
                for item in self._current.batch_save_custom_roots
                if item.id != root_id
            )
            if len(remaining) == len(self._current.batch_save_custom_roots):
                raise InvalidBatchSaveSettingsError(
                    "没有找到对应的批量存档自定义目录。"
                )
            updated = replace(self._current, batch_save_custom_roots=remaining)
            self._store.save(updated)
            self._current = updated
            return True


def _parse_batch_save_custom_roots(raw: object) -> tuple[BatchSaveCustomRoot, ...]:
    if not isinstance(raw, list) or len(raw) > MAX_BATCH_SAVE_CUSTOM_ROOTS:
        raise InvalidConfigError("配置文件无效：批量存档自定义目录必须是最多 32 项的数组。")
    roots: list[BatchSaveCustomRoot] = []
    ids: set[str] = set()
    path_keys: set[str] = set()
    for item in raw:
        if not isinstance(item, dict) or set(item) != {
            "id",
            "displayPath",
            "enabled",
            "maxDepth",
        }:
            raise InvalidConfigError("配置文件无效：批量存档自定义目录字段不完整。")
        root = _normalize_batch_save_custom_root(
            root_id=item["id"],
            display_path=item["displayPath"],
            enabled=item["enabled"],
            max_depth=item["maxDepth"],
            error_type=InvalidConfigError,
        )
        path_key = windows_path_key(root.display_path)
        if root.id in ids or path_key in path_keys:
            raise InvalidConfigError("配置文件无效：批量存档自定义目录存在重复项。")
        ids.add(root.id)
        path_keys.add(path_key)
        roots.append(root)
    return tuple(roots)


def _normalize_batch_save_custom_root(
    *,
    root_id: object,
    display_path: object,
    enabled: object,
    max_depth: object,
    error_type: type[ValueError],
) -> BatchSaveCustomRoot:
    if not isinstance(root_id, str) or not root_id.strip() or "\x00" in root_id:
        raise error_type("批量存档自定义目录 ID 无效。")
    if (
        not isinstance(display_path, str)
        or not display_path.strip()
        or "\x00" in display_path
    ):
        raise error_type("批量存档自定义目录路径无效。")
    clean_path = ntpath.normpath(display_path.strip())
    drive, tail = ntpath.splitdrive(clean_path)
    if not ntpath.isabs(clean_path) or not drive or tail in {"", "\\", "/"}:
        raise error_type("批量存档自定义目录必须是非盘符根的绝对路径。")
    if not isinstance(enabled, bool):
        raise error_type("批量存档自定义目录启用状态必须是布尔值。")
    if type(max_depth) is not int or max_depth not in BATCH_SAVE_DEPTH_RANGE:
        raise error_type("批量存档自定义目录深度必须为 1 到 12。")
    return BatchSaveCustomRoot(
        id=root_id.strip(),
        display_path=clean_path,
        enabled=enabled,
        max_depth=max_depth,
    )
