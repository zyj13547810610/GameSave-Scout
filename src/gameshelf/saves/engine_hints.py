"""Conservative save-location hints backed by engine-specific evidence."""

from __future__ import annotations

import json
import ntpath
import re
from collections import deque
from collections.abc import Mapping
from itertools import islice
from pathlib import Path, PureWindowsPath

from gameshelf.engines.bounded_reader import read_text_limit
from gameshelf.library.models import Game
from gameshelf.saves.models import SaveLocationKind, SaveLocationSuggestion
from gameshelf.saves.templates import InvalidPathTemplate, PathTemplateResolver

_RENPY_SAVE_DIRECTORY = re.compile(
    r"(?m)^\s*(?:define\s+)?config\.save_directory\s*=\s*"
    r"(?P<quote>['\"])(?P<value>[^'\"\r\n]+)(?P=quote)\s*(?:#.*)?$"
)
_GODOT_SECTION = re.compile(r"\[(?P<name>[A-Za-z0-9_./-]+)\]\Z")
_GODOT_SETTING = re.compile(
    r"(?P<key>config/(?:name(?:\.windows)?|use_custom_user_dir|custom_user_dir_name))"
    r"\s*=\s*(?P<value>.+)\Z"
)
_GODOT_STRING_LITERAL = re.compile(r'"(?P<value>[^"\\\r\n]{1,256})"\Z')
_WINDOWS_INVALID_SEGMENT = frozenset('<>:"/\\|?*')
_WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}
class EngineSaveHintProvider:
    def __init__(self, resolver: PathTemplateResolver) -> None:
        self._resolver = resolver

    def suggest(
        self,
        game: Game,
        install_dir: Path,
        engine_metadata: Mapping[str, str],
    ) -> tuple[SaveLocationSuggestion, ...]:
        engine_id = game.engine_id
        if engine_id == "unity":
            return self._unity(install_dir, engine_metadata)
        if engine_id == "unreal":
            return self._unreal(install_dir, engine_metadata)
        if engine_id == "godot":
            return self._godot(install_dir, engine_metadata)
        if engine_id == "wolf_rpg":
            return self._wolf(install_dir)
        if engine_id == "kirikiri":
            return self._kirikiri(install_dir)
        return ()

    def _unity(
        self,
        install_dir: Path,
        metadata: Mapping[str, str],
    ) -> tuple[SaveLocationSuggestion, ...]:
        company = _metadata_value(metadata, "company_name", "companyName")
        product = _metadata_value(metadata, "product_name", "productName")
        if not _safe_windows_segment(company) or not _safe_windows_segment(product):
            return ()
        directory_template = f"<winLocalAppDataLow>\\{company}\\{product}"
        try:
            directory_display = str(
                self._resolver.expand(directory_template, install_dir)
            )
        except InvalidPathTemplate:
            return ()
        registry = f"HKEY_CURRENT_USER\\Software\\{company}\\{product}"
        evidence = ("从 Unity 可靠元数据读取到公司名和产品名",)
        return (
            SaveLocationSuggestion(
                kind="directory",
                path_template=directory_template,
                display_path=directory_display,
                source="engine",
                confidence=0.94,
                evidence=evidence,
                availability=(
                    "found" if Path(directory_display).is_dir() else "predicted"
                ),
            ),
            SaveLocationSuggestion(
                kind="registry",
                path_template=registry,
                display_path=registry,
                source="engine",
                confidence=0.9,
                evidence=("Unity PlayerPrefs 使用公司名和产品名组成注册表键",),
                category="config",
                availability="predicted",
            ),
        )

    def _unreal(
        self,
        install_dir: Path,
        metadata: Mapping[str, str],
    ) -> tuple[SaveLocationSuggestion, ...]:
        project_name = metadata.get("project_name", "")
        if not _safe_windows_segment(project_name):
            return ()
        template = (
            f"<winLocalAppData>\\{project_name}\\Saved\\SaveGames"
        )
        suggestion = self._template_directory_suggestion(
            template,
            install_dir,
            0.92,
            ("从有效 .uproject 项目文件取得 Unreal 项目名",),
        )
        return () if suggestion is None else (suggestion,)

    def _godot(
        self,
        install_dir: Path,
        metadata: Mapping[str, str],
    ) -> tuple[SaveLocationSuggestion, ...]:
        custom_directory = metadata.get("godot_custom_user_dir", "")
        if custom_directory:
            if _safe_relative_segments(custom_directory) is None:
                return ()
            template = f"<winAppData>\\{custom_directory}"
            evidence = ("从 project.godot 读取到安全的自定义 user:// 目录",)
        else:
            project_name = metadata.get("project_name", "")
            if not _safe_windows_segment(project_name):
                return ()
            template = f"<winAppData>\\Godot\\app_userdata\\{project_name}"
            evidence = ("从 project.godot 读取项目名并应用官方默认 user:// 路径",)
        suggestion = self._template_directory_suggestion(
            template,
            install_dir,
            0.94,
            evidence,
        )
        return () if suggestion is None else (suggestion,)

    def _template_directory_suggestion(
        self,
        template: str,
        install_dir: Path,
        confidence: float,
        evidence: tuple[str, ...],
    ) -> SaveLocationSuggestion | None:
        try:
            display = str(self._resolver.expand(template, install_dir))
        except InvalidPathTemplate:
            return None
        return SaveLocationSuggestion(
            kind="directory",
            path_template=template,
            display_path=display,
            source="engine",
            confidence=confidence,
            evidence=evidence,
            availability="found" if Path(display).is_dir() else "predicted",
        )

    def _wolf(self, install_dir: Path) -> tuple[SaveLocationSuggestion, ...]:
        candidates = (
            install_dir / "Save",
            install_dir / "save",
            install_dir / "Data" / "Save",
            install_dir / "Data" / "save",
            install_dir / "Save" / "Data",
        )
        save_dir = next(
            (
                path
                for path in candidates
                if path.is_dir() and _contains_wolf_save(path)
            ),
            None,
        )
        if save_dir is None:
            for directory in _bounded_directories(install_dir):
                if _contains_wolf_save(directory):
                    save_dir = directory
                    break
        if save_dir is None:
            return ()
        suggestion = self._filesystem_suggestion(
            "directory",
            save_dir,
            install_dir,
            0.88,
            ("发现 WOLF 游戏目录下已有的存档目录或存档文件",),
        )
        return () if suggestion is None else (suggestion,)

    def _kirikiri(self, install_dir: Path) -> tuple[SaveLocationSuggestion, ...]:
        for directory in _bounded_directories(install_dir):
            if directory.name.casefold() not in {"save", "savedata"}:
                continue
            if not any(
                child.is_file() and child.suffix.casefold() in {".sav", ".data"}
                for child in _safe_iterdir(directory)
            ):
                continue
            suggestion = self._filesystem_suggestion(
                "directory",
                directory,
                install_dir,
                0.9,
                ("在 save/savedata 目录中发现 KiriKiri .sav/.data 文件",),
            )
            return () if suggestion is None else (suggestion,)
        return ()

    def _filesystem_suggestion(
        self,
        kind: SaveLocationKind,
        path: Path,
        install_dir: Path,
        confidence: float,
        evidence: tuple[str, ...],
    ) -> SaveLocationSuggestion | None:
        try:
            template = self._resolver.collapse(path, install_dir)
            display = str(self._resolver.expand(template, install_dir))
        except InvalidPathTemplate:
            return None
        return SaveLocationSuggestion(
            kind=kind,
            path_template=template,
            display_path=display,
            source="engine",
            confidence=confidence,
            evidence=evidence,
            availability="found",
        )


def _safe_windows_segment(value: str) -> bool:
    base_name = value.split(".", 1)[0].casefold()
    return bool(
        value
        and value == value.strip()
        and value not in {".", ".."}
        and len(value) <= 128
        and not value.endswith((" ", "."))
        and not any(character in _WINDOWS_INVALID_SEGMENT for character in value)
        and not any(ord(character) < 32 for character in value)
        and base_name not in _WINDOWS_RESERVED_NAMES
    )


def _contains_wolf_save(directory: Path) -> bool:
    return any(
        child.is_file()
        and child.name.casefold().startswith("save")
        and child.suffix.casefold() in {".sav", ".dat", ".data"}
        for child in _safe_iterdir(directory)
    )


def _safe_relative_segments(value: str) -> tuple[str, ...] | None:
    normalized = value.replace("/", "\\")
    drive, _ = ntpath.splitdrive(normalized)
    if (
        drive
        or ntpath.isabs(normalized)
        or len(normalized) > 256
        or normalized.startswith("\\")
        or normalized.endswith("\\")
        or "\\\\" in normalized
    ):
        return None
    parts = PureWindowsPath(normalized).parts
    if not 1 <= len(parts) <= 8:
        return None
    if any(not _safe_windows_segment(part) for part in parts):
        return None
    return parts


def _metadata_value(metadata: Mapping[str, str], *keys: str) -> str:
    for key in keys:
        value = metadata.get(key, "").strip()
        if value:
            return value
    return ""


def _bounded_directories(root: Path) -> tuple[Path, ...]:
    pending: deque[tuple[Path, int]] = deque([(root, 0)])
    result: list[Path] = []
    while pending and len(result) < 256:
        current, depth = pending.popleft()
        result.append(current)
        if depth >= 3:
            continue
        for child in _safe_iterdir(current):
            if child.is_dir():
                pending.append((child, depth + 1))
    return tuple(result)


def _safe_iterdir(directory: Path) -> tuple[Path, ...]:
    try:
        return tuple(islice(directory.iterdir(), 256))
    except OSError:
        return ()


def load_engine_metadata(game: Game, install_dir: Path) -> Mapping[str, str]:
    """Read the small, engine-owned metadata files used by save hints."""

    if game.engine_id == "renpy":
        return _load_renpy_metadata(install_dir)
    if game.engine_id == "unity":
        return _load_unity_metadata(game, install_dir)
    if game.engine_id == "unreal":
        return _load_unreal_metadata(install_dir)
    if game.engine_id == "godot":
        return _load_godot_metadata(install_dir)
    return {}


def _load_renpy_metadata(install_dir: Path) -> Mapping[str, str]:
    scripts_dir = install_dir / "game"
    for candidate in _bounded_files(scripts_dir, ".rpy"):
        try:
            text = read_text_limit(candidate)
        except OSError:
            continue
        for match in _RENPY_SAVE_DIRECTORY.finditer(text):
            segment = match.group("value")
            if _safe_windows_segment(segment):
                return {"renpy_save_directory": segment}
    return {}


def _load_unity_metadata(game: Game, install_dir: Path) -> Mapping[str, str]:
    candidates: list[Path] = []
    if game.main_exe_relpath:
        candidates.append(
            install_dir / f"{Path(game.main_exe_relpath).stem}_Data" / "app.info"
        )
    candidates.extend(sorted(install_dir.glob("*_Data/app.info")))
    for candidate in dict.fromkeys(candidates):
        if not candidate.is_file():
            continue
        try:
            lines = [line.strip() for line in read_text_limit(candidate).splitlines()]
        except OSError:
            continue
        if len(lines) >= 2 and lines[0] and lines[1]:
            if not _safe_windows_segment(lines[0]) or not _safe_windows_segment(
                lines[1]
            ):
                continue
            return {"company_name": lines[0], "product_name": lines[1]}
    return {}


def _load_unreal_metadata(install_dir: Path) -> Mapping[str, str]:
    for candidate in _bounded_files(install_dir, ".uproject"):
        project_name = candidate.stem
        if not _safe_windows_segment(project_name):
            continue
        try:
            raw = json.loads(read_text_limit(candidate))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict):
            continue
        file_version = raw.get("FileVersion")
        if not isinstance(file_version, int) or isinstance(file_version, bool):
            continue
        return {"project_name": project_name}
    return {}


def _load_godot_metadata(install_dir: Path) -> Mapping[str, str]:
    for candidate in _bounded_named_files(install_dir, "project.godot"):
        try:
            settings = _godot_application_settings(read_text_limit(candidate))
        except OSError:
            continue
        project_name = _godot_string(
            settings.get("config/name.windows")
            or settings.get("config/name", "")
        )
        if project_name is None or not _safe_windows_segment(project_name):
            continue
        custom_enabled = settings.get("config/use_custom_user_dir", "false")
        if custom_enabled not in {"true", "false"}:
            continue
        if custom_enabled == "false":
            return {"project_name": project_name}
        custom_name = _godot_string(
            settings.get("config/custom_user_dir_name", "")
        )
        relative = custom_name or project_name
        parts = _safe_relative_segments(relative)
        if parts is None:
            continue
        return {"godot_custom_user_dir": "\\".join(parts)}
    return {}


def _bounded_files(root: Path, suffix: str) -> tuple[Path, ...]:
    result: list[Path] = []
    for directory in _bounded_directories(root):
        for child in _safe_iterdir(directory):
            if child.is_file() and child.suffix.casefold() == suffix.casefold():
                result.append(child)
                if len(result) >= 256:
                    return tuple(result)
    return tuple(result)


def _bounded_named_files(root: Path, name: str) -> tuple[Path, ...]:
    expected = name.casefold()
    result: list[Path] = []
    for directory in _bounded_directories(root):
        for child in _safe_iterdir(directory):
            if child.is_file() and child.name.casefold() == expected:
                result.append(child)
                if len(result) >= 256:
                    return tuple(result)
    return tuple(result)


def _godot_application_settings(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    section = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith((";", "#")):
            continue
        section_match = _GODOT_SECTION.fullmatch(line)
        if section_match is not None:
            section = section_match.group("name")
            continue
        if section != "application":
            continue
        setting_match = _GODOT_SETTING.fullmatch(line)
        if setting_match is not None:
            result[setting_match.group("key")] = setting_match.group("value")
    return result


def _godot_string(raw: str) -> str | None:
    if not raw:
        return None
    match = _GODOT_STRING_LITERAL.fullmatch(raw)
    return None if match is None else match.group("value")
