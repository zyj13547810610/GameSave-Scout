"""Build and revalidate user-approved guided save monitoring scopes."""

from __future__ import annotations

import hashlib
import ntpath
import os
import stat
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

from gameshelf.library.models import Game
from gameshelf.library.service import GameNotFoundError, LibraryService
from gameshelf.platform.windows.known_folders import KnownFolders
from gameshelf.saves.guided_models import (
    GuidedRegistryTarget,
    GuidedSavePreview,
    GuidedScopeOption,
    GuidedScopeSource,
)
from gameshelf.saves.repository import SaveLocationRepository
from gameshelf.saves.templates import InvalidPathTemplate, PathTemplateResolver
from gameshelf.scanning.path_keys import (
    expand_relative,
    is_same_or_child,
    windows_path_key,
)


class InvalidGuidedScope(ValueError):
    """Raised when a guided monitoring scope is unsafe or no longer available."""


class StaticRegistryTargetProvider(Protocol):
    def registry_targets_for_game(
        self, game_id: str
    ) -> tuple[tuple[str, tuple[str, ...]], ...]: ...


type ReparsePointCheck = Callable[[Path], bool]


class GuidedSaveScopeBuilder:
    def __init__(
        self,
        *,
        library: LibraryService,
        save_repository: SaveLocationRepository,
        resolver: PathTemplateResolver,
        known_folders: KnownFolders,
        static_discovery: StaticRegistryTargetProvider,
        is_reparse_point: ReparsePointCheck | None = None,
    ) -> None:
        self._library = library
        self._save_repository = save_repository
        self._resolver = resolver
        self._known_folders = known_folders
        self._static_discovery = static_discovery
        self._is_reparse_point = is_reparse_point or is_windows_reparse_point

    def preview(self, game_id: str) -> GuidedSavePreview:
        game, game_dir, executable = self._require_launchable_game(game_id)
        scopes = self._build_scopes(game_id, game_dir)
        registry_targets = self._registry_targets(game_id)
        return GuidedSavePreview(
            game_id=game.id,
            game_title=game.title,
            executable=str(executable),
            scopes=scopes,
            registry_targets=registry_targets,
        )

    def resolve_selected(
        self,
        game_id: str,
        selected_scope_ids: Sequence[str],
        additional_directories: Sequence[str],
    ) -> tuple[GuidedScopeOption, ...]:
        _, game_dir, _ = self._require_launchable_game(game_id)
        available_scopes = self._build_scopes(game_id, game_dir)
        by_id = {scope.id: scope for scope in available_scopes}
        selected: list[GuidedScopeOption] = []
        for scope_id in dict.fromkeys(selected_scope_ids):
            scope = by_id.get(scope_id)
            if scope is None:
                raise InvalidGuidedScope(f"未知的监控范围：{scope_id}")
            if not scope.available:
                raise InvalidGuidedScope(
                    f"监控范围在确认后已不可用：{scope.label}。"
                )
            selected.append(scope)

        for raw_directory in dict.fromkeys(additional_directories):
            selected.append(self._resolve_extra(raw_directory, game_dir))
        return _outermost_scopes(selected)

    def _require_launchable_game(self, game_id: str) -> tuple[Game, Path, Path]:
        game = self._library.get_game(game_id)
        if game is None:
            raise GameNotFoundError(game_id)
        if game.status != "installed":
            raise InvalidGuidedScope("只有当前已安装的游戏可以使用引导式寻找。")
        game_dir = self._library.install_directory(game_id)
        if not game_dir.is_dir():
            raise InvalidGuidedScope("游戏安装目录不存在或无法访问。")
        if game.main_exe_relpath is None:
            raise InvalidGuidedScope("游戏尚未配置可启动的主程序。")
        try:
            executable = expand_relative(game_dir, game.main_exe_relpath)
        except ValueError as error:
            raise InvalidGuidedScope("游戏尚未配置可启动的主程序。") from error
        if executable.suffix.casefold() != ".exe" or not executable.is_file():
            raise InvalidGuidedScope("游戏尚未配置可启动的主程序。")
        return game, game_dir, executable

    def _build_scopes(
        self, game_id: str, game_dir: Path
    ) -> tuple[GuidedScopeOption, ...]:
        folders = self._known_folders
        defaults: tuple[tuple[str, str, Path, GuidedScopeSource, bool], ...] = (
            ("default:game", "游戏安装目录", game_dir, "game", True),
            ("default:documents", "Documents", folders.documents, "documents", True),
            (
                "default:saved-games",
                "Saved Games",
                folders.saved_games,
                "saved_games",
                True,
            ),
            ("default:roaming", "AppData Roaming", folders.app_data, "app_data", True),
            (
                "default:local",
                "AppData Local",
                folders.local_app_data,
                "local_app_data",
                True,
            ),
            (
                "default:local-low",
                "AppData LocalLow",
                folders.local_app_data_low,
                "local_app_data_low",
                True,
            ),
            (
                "default:program-data",
                "ProgramData",
                folders.program_data,
                "program_data",
                False,
            ),
        )
        scopes = [
            self._scope_option(
                scope_id,
                label,
                directory,
                source,
                default_selected,
                game_dir,
            )
            for scope_id, label, directory, source, default_selected in defaults
        ]
        for location in self._save_repository.list_for_game(game_id):
            if (
                not location.confirmed
                or not location.enabled
                or location.kind == "registry"
            ):
                continue
            try:
                confirmed_path = self._resolver.expand(location.path_template, game_dir)
            except InvalidPathTemplate:
                continue
            parent = confirmed_path.parent
            scopes.append(
                self._scope_option(
                    f"confirmed:{location.id}",
                    f"已确认位置的父目录：{parent.name or parent}",
                    parent,
                    "confirmed",
                    True,
                    game_dir,
                )
            )
        return _deduplicate_preview_scopes(scopes)

    def _scope_option(
        self,
        scope_id: str,
        label: str,
        directory: Path,
        source: GuidedScopeSource,
        default_selected: bool,
        game_dir: Path,
    ) -> GuidedScopeOption:
        try:
            path_template = self._resolver.collapse(directory, game_dir)
        except InvalidPathTemplate:
            path_template = str(directory)
        unavailable_reason = _unavailable_reason(directory, self._is_reparse_point)
        return GuidedScopeOption(
            id=scope_id,
            label=label,
            display_path=str(directory),
            path_template=path_template,
            source=source,
            default_selected=default_selected,
            available=unavailable_reason is None,
            unavailable_reason=unavailable_reason,
        )

    def _resolve_extra(self, raw_directory: str, game_dir: Path) -> GuidedScopeOption:
        clean = ntpath.normpath(raw_directory.strip())
        if _is_unc(clean):
            raise InvalidGuidedScope("V0.1 不支持网络目录或 UNC 路径。")
        if not clean or not ntpath.isabs(clean):
            raise InvalidGuidedScope("额外目录必须是本机绝对路径。")
        directory = Path(clean)
        unavailable_reason = _unavailable_reason(directory, self._is_reparse_point)
        if unavailable_reason is not None:
            raise InvalidGuidedScope(f"额外目录不可用：{unavailable_reason}")
        try:
            path_template = self._resolver.collapse(directory, game_dir)
        except InvalidPathTemplate as error:
            raise InvalidGuidedScope("额外目录无法表示为便携存档路径。") from error
        key = windows_path_key(directory)
        scope_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        return GuidedScopeOption(
            id=f"extra:{scope_hash}",
            label=f"额外目录：{directory.name or directory}",
            display_path=str(directory),
            path_template=path_template,
            source="extra",
            default_selected=True,
            available=True,
        )

    def _registry_targets(self, game_id: str) -> tuple[GuidedRegistryTarget, ...]:
        targets: dict[str, GuidedRegistryTarget] = {}
        for key, evidence in self._static_discovery.registry_targets_for_game(game_id):
            normalized = key.replace("/", "\\")
            targets.setdefault(
                normalized.casefold(),
                GuidedRegistryTarget(
                    key=normalized,
                    source="；".join(evidence),
                    available=True,
                ),
            )
        for location in self._save_repository.list_for_game(game_id):
            if (
                location.kind != "registry"
                or not location.confirmed
                or not location.enabled
            ):
                continue
            normalized = location.path_template.replace("/", "\\")
            targets.setdefault(
                normalized.casefold(),
                GuidedRegistryTarget(
                    key=normalized,
                    source="已确认存档位置",
                    available=True,
                ),
            )
        return tuple(sorted(targets.values(), key=lambda item: item.key.casefold()))


def is_windows_reparse_point(path: Path) -> bool:
    try:
        metadata = path.stat(follow_symlinks=False)
    except OSError:
        return False
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or bool(attributes & reparse_flag)


def _unavailable_reason(
    directory: Path, is_reparse_point: ReparsePointCheck
) -> str | None:
    if _is_unc(os.fspath(directory)):
        return "V0.1 不支持网络目录或 UNC 路径。"
    if not directory.is_dir():
        return "目录不存在或无法访问。"
    if is_reparse_point(directory):
        return "目录是符号链接、联接或其他重解析点。"
    return None


def _is_unc(path: str) -> bool:
    return path.replace("/", "\\").startswith("\\\\")


def _deduplicate_preview_scopes(
    scopes: Sequence[GuidedScopeOption],
) -> tuple[GuidedScopeOption, ...]:
    retained: list[GuidedScopeOption] = []
    seen: set[str] = set()
    for scope in scopes:
        key = windows_path_key(scope.display_path)
        if key in seen:
            continue
        if scope.source == "confirmed" and any(
            existing.available
            and is_same_or_child(key, windows_path_key(existing.display_path))
            for existing in retained
        ):
            continue
        seen.add(key)
        retained.append(scope)
    return tuple(retained)


def _outermost_scopes(
    scopes: Sequence[GuidedScopeOption],
) -> tuple[GuidedScopeOption, ...]:
    retained: list[tuple[str, GuidedScopeOption]] = []
    ordered = sorted(
        ((windows_path_key(scope.display_path), scope) for scope in scopes),
        key=lambda item: (len(item[0]), item[0], item[1].id),
    )
    for key, scope in ordered:
        if any(is_same_or_child(key, root_key) for root_key, _ in retained):
            continue
        retained.append((key, scope))
    return tuple(scope for _, scope in retained)
