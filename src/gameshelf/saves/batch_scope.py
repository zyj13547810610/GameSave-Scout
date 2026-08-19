"""Build the user-selected roots for bounded batch save discovery."""

from __future__ import annotations

import ntpath
from collections.abc import Sequence
from pathlib import Path

from gameshelf.bootstrap.config import AppConfig, BatchSaveCustomRoot
from gameshelf.platform.windows.known_folders import KnownFolders
from gameshelf.saves.batch_models import BatchScanScope
from gameshelf.scanning.path_keys import windows_path_key

_STANDARD_SCOPES = {
    "documents": ("Documents", "documents", 6),
    "saved_games": ("Saved Games", "saved_games", 6),
    "app_data": ("AppData Roaming", "app_data", 6),
    "local_app_data": ("AppData Local", "local_app_data", 6),
    "local_app_data_low": ("AppData LocalLow", "local_app_data_low", 6),
}


class BatchScopeBuilder:
    """Resolve stable scope IDs without silently widening the scan boundary."""

    def __init__(self, known_folders: KnownFolders, config: AppConfig) -> None:
        self._known_folders = known_folders
        self._config = config

    def build(
        self,
        standard_scope_ids: Sequence[str],
        custom_root_ids: Sequence[str],
    ) -> tuple[BatchScanScope, ...]:
        standard_ids = tuple(dict.fromkeys(standard_scope_ids))
        custom_ids = tuple(dict.fromkeys(custom_root_ids))
        unknown_standard = [
            scope_id for scope_id in standard_ids if scope_id not in _STANDARD_SCOPES
        ]
        if unknown_standard:
            raise ValueError(f"未知的批量存档标准范围：{unknown_standard[0]}")

        custom_by_id = {item.id: item for item in self._config.batch_save_custom_roots}
        unknown_custom = [root_id for root_id in custom_ids if root_id not in custom_by_id]
        if unknown_custom:
            raise ValueError(f"未知的批量存档自定义目录：{unknown_custom[0]}")

        selected_custom = tuple(
            custom_by_id[root_id] for root_id in custom_ids if custom_by_id[root_id].enabled
        )
        for root in selected_custom:
            _validate_custom_root(root)

        custom_path_keys = {windows_path_key(root.display_path) for root in selected_custom}
        scopes: list[BatchScanScope] = []
        for scope_id in standard_ids:
            label, attribute, max_depth = _STANDARD_SCOPES[scope_id]
            path = getattr(self._known_folders, attribute)
            if windows_path_key(path) in custom_path_keys:
                continue
            scopes.append(
                BatchScanScope(
                    key=scope_id,
                    label=label,
                    root=path,
                    source="standard",
                    max_depth=max_depth,
                    custom_root_id=None,
                )
            )

        scopes.extend(
            BatchScanScope(
                key=f"custom:{root.id}",
                label=Path(root.display_path).name or root.display_path,
                root=Path(root.display_path),
                source="custom",
                max_depth=root.max_depth,
                custom_root_id=root.id,
            )
            for root in selected_custom
        )
        return tuple(scopes)


def _validate_custom_root(root: BatchSaveCustomRoot) -> None:
    clean_path = ntpath.normpath(root.display_path.strip())
    drive, tail = ntpath.splitdrive(clean_path)
    if not ntpath.isabs(clean_path) or not drive or tail in {"", "\\", "/"}:
        raise ValueError("批量存档自定义目录不能是盘符根，且必须使用绝对路径。")
