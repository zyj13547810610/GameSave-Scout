"""只读诊断 Ludusavi 索引的冷、热查询耗时。"""

from __future__ import annotations

import json
import sys
from argparse import ArgumentParser
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, cast

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from gamesave_scout.library.models import Game  # noqa: E402
from gamesave_scout.platform.windows.known_folders import KnownFolders  # noqa: E402
from gamesave_scout.saves.ludusavi_index import LudusaviIndex  # noqa: E402
from gamesave_scout.saves.ludusavi_index_matcher import IndexedLudusaviMatcher  # noqa: E402
from gamesave_scout.saves.templates import PathTemplateResolver  # noqa: E402


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    games: int
    names: int
    path_rules: int
    cold_seconds: float
    warm_seconds: float
    exact_matches: int
    fuzzy_matches: int


def benchmark_directory(directory: Path) -> BenchmarkResult:
    digest = _metadata_digest(directory / "manifest-meta.json")
    resolver = _resolver(directory)
    exact_game = _game("Clair Obscur: Expedition 33", "Expedition 33")
    fuzzy_game = _game("Clair Obscur Expedition 3", "Unrelated")

    cold_started = perf_counter()
    index = LudusaviIndex.open(
        directory / "manifest-index.sqlite",
        manifest_sha256=digest,
    )
    matcher = IndexedLudusaviMatcher(index, resolver)
    exact_matches = matcher.find(
        exact_game,
        directory / "Games" / "Expedition 33",
    )
    cold_seconds = perf_counter() - cold_started

    warm_started = perf_counter()
    fuzzy_matches = matcher.find(
        fuzzy_game,
        directory / "Games" / "Unrelated",
    )
    warm_seconds = perf_counter() - warm_started
    return BenchmarkResult(
        games=index.metadata.game_count,
        names=index.metadata.name_count,
        path_rules=index.metadata.path_rule_count,
        cold_seconds=cold_seconds,
        warm_seconds=warm_seconds,
        exact_matches=len(exact_matches),
        fuzzy_matches=len(fuzzy_matches),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = ArgumentParser(description="测量 Ludusavi SQLite 索引查询性能。")
    parser.add_argument(
        "--directory",
        type=Path,
        default=REPOSITORY_ROOT / "resources" / "rules" / "ludusavi",
        help="包含 manifest-meta.json 和 manifest-index.sqlite 的目录。",
    )
    arguments = parser.parse_args(argv)
    result = benchmark_directory(arguments.directory)
    print(json.dumps(asdict(result), ensure_ascii=False, separators=(",", ":")))
    return 0


def _game(title: str, relative_dir: str) -> Game:
    return Game(
        id=f"benchmark-{relative_dir.casefold()}",
        scan_root_id="benchmark-root",
        relative_dir=relative_dir,
        install_path_key=f"benchmark\\{relative_dir.casefold()}",
        title=title,
        detected_title=None,
        status="installed",
        detected_engine_id=None,
        detected_engine_variant=None,
        engine_id=None,
        engine_variant=None,
        engine_is_manual=False,
        engine_confidence=None,
        engine_evidence=(),
        engine_rules_version=None,
        main_exe_relpath="Unrelated.exe",
        main_exe_is_manual=False,
        working_dir_relpath=None,
        launch_args=(),
        environment={},
        exe_arch="unknown",
        cover_original_relpath=None,
        cover_thumb_relpath=None,
        cover_revision=0,
        last_launched_at=None,
        missing_since=None,
    )


def _resolver(directory: Path) -> PathTemplateResolver:
    home = directory / "benchmark-profile"
    return PathTemplateResolver(
        KnownFolders(
            home=home,
            app_data=home / "AppData" / "Roaming",
            local_app_data=home / "AppData" / "Local",
            local_app_data_low=home / "AppData" / "LocalLow",
            documents=home / "Documents",
            saved_games=home / "Saved Games",
            program_data=directory / "ProgramData",
            public=directory / "Public",
            windows=directory / "Windows",
        )
    )


def _metadata_digest(path: Path) -> str:
    loaded: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise RuntimeError("Ludusavi 元数据必须是 JSON 对象。")
    digest = cast(dict[str, Any], loaded).get("sha256")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise RuntimeError("Ludusavi 元数据中的 SHA-256 无效。")
    return digest


if __name__ == "__main__":
    raise SystemExit(main())
