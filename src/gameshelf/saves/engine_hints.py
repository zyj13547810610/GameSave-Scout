"""Conservative save-location hints backed by engine-specific evidence."""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Mapping
from itertools import islice
from pathlib import Path

from gameshelf.engines.bounded_reader import read_text_limit
from gameshelf.library.models import Game
from gameshelf.saves.models import SaveLocationKind, SaveLocationSuggestion
from gameshelf.saves.templates import InvalidPathTemplate, PathTemplateResolver

_RENPY_SAVE_DIRECTORY = re.compile(
    r"(?m)^\s*(?:define\s+)?config\.save_directory\s*=\s*"
    r"(?P<quote>['\"])(?P<value>[^'\"\r\n]+)(?P=quote)\s*(?:#.*)?$"
)
_WINDOWS_INVALID_SEGMENT = frozenset('<>:"/\\|?*')
_RGSS_PATTERNS = {
    "rpg_maker_2k": ("Save*.lsd",),
    "rpg_maker_xp": ("Save*.rxdata",),
    "rpg_maker_vx": ("Save*.rvdata",),
    "rpg_maker_vx_ace": ("Save*.rvdata2",),
}
_JS_RPG_PATTERNS = {
    "rpg_maker_mv": ("save/*.rpgsave", "www/save/*.rpgsave"),
    "rpg_maker_mz": ("save/*.rmmzsave", "www/save/*.rmmzsave"),
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
        if engine_id == "renpy":
            return self._renpy(install_dir)
        if engine_id == "unity":
            return self._unity(install_dir, engine_metadata)
        if engine_id in _RGSS_PATTERNS:
            return self._existing_globs(
                install_dir,
                _RGSS_PATTERNS[engine_id],
                "发现对应 RPG Maker 世代的现有存档文件",
            )
        if engine_id in _JS_RPG_PATTERNS:
            return self._existing_globs(
                install_dir,
                _JS_RPG_PATTERNS[engine_id],
                "发现 RPG Maker save 目录中的现有存档文件",
            )
        if engine_id == "wolf_rpg":
            return self._wolf(install_dir)
        if engine_id == "kirikiri":
            return self._kirikiri(install_dir)
        if engine_id == "nscripter":
            return self._nscripter(install_dir)
        return ()

    def _renpy(self, install_dir: Path) -> tuple[SaveLocationSuggestion, ...]:
        scripts_dir = install_dir / "game"
        if not scripts_dir.is_dir():
            return ()
        for script in islice(sorted(scripts_dir.rglob("*.rpy")), 256):
            try:
                text = read_text_limit(script)
            except OSError:
                continue
            for match in _RENPY_SAVE_DIRECTORY.finditer(text):
                segment = match.group("value").strip()
                if not _safe_windows_segment(segment):
                    continue
                template = f"<winAppData>\\RenPy\\{segment}"
                try:
                    display = str(self._resolver.expand(template, install_dir))
                except InvalidPathTemplate:
                    continue
                return (
                    SaveLocationSuggestion(
                        kind="directory",
                        path_template=template,
                        display_path=display,
                        source="engine",
                        confidence=0.96,
                        evidence=(
                            f"{script.relative_to(install_dir).as_posix()} 中存在 "
                            "config.save_directory 字符串字面量",
                        ),
                    ),
                )
        return ()

    def _unity(
        self,
        install_dir: Path,
        metadata: Mapping[str, str],
    ) -> tuple[SaveLocationSuggestion, ...]:
        company = metadata.get("companyName", "").strip()
        product = metadata.get("productName", "").strip()
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
            ),
            SaveLocationSuggestion(
                kind="registry",
                path_template=registry,
                display_path=registry,
                source="engine",
                confidence=0.9,
                evidence=("Unity PlayerPrefs 使用公司名和产品名组成注册表键",),
            ),
        )

    def _existing_globs(
        self,
        install_dir: Path,
        patterns: tuple[str, ...],
        evidence: str,
    ) -> tuple[SaveLocationSuggestion, ...]:
        suggestions: list[SaveLocationSuggestion] = []
        for pattern in patterns:
            if not any(path.is_file() for path in islice(install_dir.glob(pattern), 1)):
                continue
            candidate = install_dir.joinpath(*Path(pattern).parts)
            suggestion = self._filesystem_suggestion(
                "glob",
                candidate,
                install_dir,
                0.96,
                (evidence, f"匹配模式：{pattern}"),
            )
            if suggestion is not None:
                suggestions.append(suggestion)
        return tuple(suggestions)

    def _wolf(self, install_dir: Path) -> tuple[SaveLocationSuggestion, ...]:
        candidates = (
            install_dir / "Save",
            install_dir / "save",
            install_dir / "Data" / "Save",
            install_dir / "Data" / "save",
            install_dir / "Save" / "Data",
        )
        save_dir = next((path for path in candidates if path.is_dir()), None)
        if save_dir is None:
            for directory in _bounded_directories(install_dir):
                if any(
                    child.is_file()
                    and child.name.casefold().startswith("save")
                    and child.suffix.casefold() in {".sav", ".dat", ".data"}
                    for child in _safe_iterdir(directory)
                ):
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

    def _nscripter(self, install_dir: Path) -> tuple[SaveLocationSuggestion, ...]:
        suggestions: list[SaveLocationSuggestion] = []
        if any(path.is_file() for path in islice(install_dir.glob("save*.dat"), 1)):
            suggestion = self._filesystem_suggestion(
                "glob",
                install_dir / "save*.dat",
                install_dir,
                0.94,
                ("游戏根目录存在 NScripter save*.dat",),
            )
            if suggestion is not None:
                suggestions.append(suggestion)
        for name in ("envdata", "kidoku.dat"):
            path = install_dir / name
            if not path.is_file():
                continue
            suggestion = self._filesystem_suggestion(
                "file",
                path,
                install_dir,
                0.92,
                (f"游戏根目录存在 NScripter {name}",),
            )
            if suggestion is not None:
                suggestions.append(suggestion)
        return tuple(suggestions)

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
        )


def _safe_windows_segment(value: str) -> bool:
    return bool(
        value
        and value not in {".", ".."}
        and len(value) <= 128
        and not value.endswith((" ", "."))
        and not any(character in _WINDOWS_INVALID_SEGMENT for character in value)
        and not any(ord(character) < 32 for character in value)
    )


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
        return tuple(directory.iterdir())
    except OSError:
        return ()
