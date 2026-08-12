"""Portable, deterministic Windows save-path templates."""

from __future__ import annotations

import ntpath
import os
import re
from pathlib import Path, PureWindowsPath

from gameshelf.platform.windows.known_folders import KnownFolders
from gameshelf.scanning.path_keys import is_same_or_child, windows_path_key


class InvalidPathTemplate(ValueError):
    """Raised when a save path cannot be safely represented or expanded."""


_TEMPLATE_PATTERN = re.compile(r"^(<[^<>\\/]+>)(?:[\\/](.*))?$")


class PathTemplateResolver:
    def __init__(self, known_folders: KnownFolders) -> None:
        self._known_folders = known_folders

    def collapse(self, path: Path, game_dir: Path | None) -> str:
        raw_path = os.fspath(path)
        if not ntpath.isabs(raw_path):
            raise InvalidPathTemplate(f"只允许折叠绝对路径：{path}")

        candidates = list(self._known_folder_roots().items())
        if game_dir is not None:
            game_text = os.fspath(game_dir)
            if not ntpath.isabs(game_text):
                raise InvalidPathTemplate(f"游戏目录必须是绝对路径：{game_dir}")
            candidates.append(("<game>", game_dir))

        path_key = windows_path_key(path)
        matching = [
            (token, root, windows_path_key(root).rstrip("\\"))
            for token, root in candidates
            if is_same_or_child(path_key, windows_path_key(root))
        ]
        if not matching:
            raise InvalidPathTemplate(f"路径不在任何便携根目录内：{path}")

        token, root, _ = max(matching, key=lambda item: len(item[2]))
        relative = ntpath.relpath(raw_path, os.fspath(root))
        return token if relative == "." else f"{token}\\{relative}"

    def expand(self, template: str, game_dir: Path | None) -> Path:
        match = _TEMPLATE_PATTERN.fullmatch(template)
        if match is None:
            raise InvalidPathTemplate(f"无效的存档路径模板：{template}")

        token, suffix = match.groups()
        roots = self._known_folder_roots()
        if token == "<game>":
            if game_dir is None:
                raise InvalidPathTemplate("展开 <game> 时缺少 game 目录。")
            root = game_dir
        else:
            try:
                root = roots[token]
            except KeyError as error:
                raise InvalidPathTemplate(f"未知的路径令牌：{token}") from error

        if suffix is None or suffix == "":
            return root
        if "<" in suffix or ">" in suffix:
            raise InvalidPathTemplate("路径后缀不能包含其他令牌。")

        drive, _ = ntpath.splitdrive(suffix)
        if drive or ntpath.isabs(suffix):
            raise InvalidPathTemplate("路径后缀必须是相对路径。")
        parts = PureWindowsPath(suffix).parts
        if any(part == ".." for part in parts):
            raise InvalidPathTemplate("路径后缀不能离开令牌根目录。")

        expanded = root.joinpath(*parts)
        if not is_same_or_child(windows_path_key(expanded), windows_path_key(root)):
            raise InvalidPathTemplate("展开后的路径离开了令牌根目录。")
        return expanded

    def _known_folder_roots(self) -> dict[str, Path]:
        folders = self._known_folders
        return {
            "<home>": folders.home,
            "<winAppData>": folders.app_data,
            "<winLocalAppData>": folders.local_app_data,
            "<winLocalAppDataLow>": folders.local_app_data_low,
            "<winDocuments>": folders.documents,
            "<winSavedGames>": folders.saved_games,
            "<winProgramData>": folders.program_data,
            "<winPublic>": folders.public,
            "<winDir>": folders.windows,
        }

