from pathlib import Path

import pytest

from gamesave_scout.engines.base import DetectionContext
from gamesave_scout.engines.detectors import runtime_frameworks
from gamesave_scout.engines.detectors.runtime_frameworks import RuntimeFrameworkDetector


@pytest.mark.parametrize(
    ("engine_id", "files"),
    [
        (
            "source2",
            {
                "game/csgo/gameinfo.gi": b"GameInfo\n{\n FileSystem2 {}\n}",
                "game/bin/win64/engine2.dll": b"MZ",
            },
        ),
        (
            "source",
            {
                "portal/gameinfo.txt": b'GameInfo\n{\n game "Portal"\n}',
                "bin/engine.dll": b"MZ",
            },
        ),
        (
            "monogame",
            {"MonoGame.Framework.dll": b"MZ", "Content/game.xnb": b"XNBw"},
        ),
        (
            "fna",
            {"FNA.dll": b"MZ", "FNA3D.dll": b"MZ", "Content/game.xnb": b"XNBw"},
        ),
        (
            "xna",
            {
                "Microsoft.Xna.Framework.dll": b"MZ",
                "Content/game.xnb": b"XNBw",
            },
        ),
        (
            "love",
            {"love.dll": b"MZ", "SDL2.dll": b"MZ", "OpenAL32.dll": b"MZ"},
        ),
        (
            "construct2",
            {
                "index.html": b"<html></html>",
                "c2runtime.js": b"cr_createRuntime",
                "data.js": b"project data",
            },
        ),
        (
            "construct3",
            {
                "index.html": b"<html></html>",
                "scripts/c3runtime.js": b"C3.Runtime",
                "scripts/main.js": b"runOnStartup",
            },
        ),
    ],
)
def test_runtime_framework_requires_a_distinctive_file_combination(
    tmp_path: Path,
    engine_id: str,
    files: dict[str, bytes],
) -> None:
    for relative, content in files.items():
        path = tmp_path.joinpath(*relative.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    match = RuntimeFrameworkDetector().inspect(DetectionContext(tmp_path, None))

    assert match is not None
    assert match.engine_id == engine_id
    assert match.confidence >= 0.8


@pytest.mark.parametrize(
    "files",
    [
        {"game/csgo/gameinfo.gi": b"GameInfo"},
        {"portal/gameinfo.txt": b"GameInfo"},
        {"MonoGame.Framework.dll": b"MZ"},
        {"FNA.dll": b"MZ", "FNA3D.dll": b"MZ"},
        {"Microsoft.Xna.Framework.dll": b"MZ"},
        {"love.dll": b"MZ", "SDL2.dll": b"MZ"},
        {"index.html": b"html", "c2runtime.js": b"runtime"},
        {"index.html": b"html", "scripts/c3runtime.js": b"runtime"},
    ],
)
def test_runtime_framework_rejects_partial_or_generic_layouts(
    tmp_path: Path,
    files: dict[str, bytes],
) -> None:
    for relative, content in files.items():
        path = tmp_path.joinpath(*relative.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    assert RuntimeFrameworkDetector().inspect(DetectionContext(tmp_path, None)) is None


def test_runtime_framework_stops_when_the_total_entry_budget_is_consumed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for index in range(8):
        (tmp_path / f"empty-{index}").mkdir()
    visited_directories: list[Path] = []
    real_iterdir = Path.iterdir

    def tracked_iterdir(path: Path):  # type: ignore[no-untyped-def]
        visited_directories.append(path)
        return real_iterdir(path)

    monkeypatch.setattr(runtime_frameworks, "_MAX_ENTRIES", 4)
    monkeypatch.setattr(Path, "iterdir", tracked_iterdir)

    assert RuntimeFrameworkDetector().inspect(DetectionContext(tmp_path, None)) is None
    assert visited_directories == [tmp_path]


def test_runtime_framework_skips_reparse_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reparse = tmp_path / "junction"
    reparse.mkdir()
    for name in ("love.dll", "SDL2.dll", "OpenAL32.dll"):
        (reparse / name).write_bytes(b"MZ")
    monkeypatch.setattr(
        runtime_frameworks,
        "_is_link_or_reparse",
        lambda path: path == reparse,
        raising=False,
    )

    assert RuntimeFrameworkDetector().inspect(DetectionContext(tmp_path, None)) is None
