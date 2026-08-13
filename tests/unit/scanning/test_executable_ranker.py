from pathlib import Path

from gameshelf.scanning.executable_ranker import (
    is_potential_game_executable_name,
    rank_executables,
)
from gameshelf.scanning.pe_metadata import PeMetadata, read_pe_metadata


def test_ranker_rejects_installers_and_prefers_title_match(
    tmp_path: Path, monkeypatch
) -> None:
    for name in ["Alice.exe", "setup.exe", "unins000.exe", "crashreporter.exe"]:
        (tmp_path / name).write_bytes(b"MZ")
    monkeypatch.setattr(
        "gameshelf.scanning.executable_ranker.read_pe_metadata",
        lambda path: PeMetadata(
            product_name="Alice" if path.name == "Alice.exe" else "",
            file_description="",
            company_name="",
            architecture="x64",
        ),
    )

    ranked = rank_executables(tmp_path)

    assert [item.relative_path for item in ranked] == ["Alice.exe"]
    assert "product_name_matches_directory" in ranked[0].evidence
    assert ranked[0].architecture == "x64"


def test_malformed_pe_is_never_executed_and_remains_low_confidence(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "Mystery.exe"
    executable.write_bytes(b"not-a-pe")

    ranked = rank_executables(tmp_path)

    assert ranked[0].relative_path == "Mystery.exe"
    assert ranked[0].architecture == "unknown"
    assert read_pe_metadata(executable) == PeMetadata("", "", "", "unknown")


def test_auxiliary_executable_names_are_not_potential_games() -> None:
    assert is_potential_game_executable_name("Game.exe") is True
    assert is_potential_game_executable_name("setup.exe") is False
    assert is_potential_game_executable_name("CONFIG.EXE") is False
    assert is_potential_game_executable_name("readme.txt") is False


def test_ranker_excludes_support_directories_and_auxiliary_executables(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "helper.exe").write_bytes(b"MZ")
    (tmp_path / "Game.exe").write_bytes(b"MZ")
    (tmp_path / "config.exe").write_bytes(b"MZ")
    monkeypatch.setattr(
        "gameshelf.scanning.executable_ranker.read_pe_metadata",
        lambda _: PeMetadata("", "", "", "x86"),
    )

    ranked = rank_executables(tmp_path)

    assert [item.relative_path for item in ranked] == ["Game.exe"]


def test_ranking_is_deterministic_for_equal_candidates(tmp_path: Path, monkeypatch) -> None:
    for name in ["z.exe", "A.exe"]:
        (tmp_path / name).write_bytes(b"MZ")
    monkeypatch.setattr(
        "gameshelf.scanning.executable_ranker.read_pe_metadata",
        lambda _: PeMetadata("", "", "", "unknown"),
    )

    assert [item.relative_path for item in rank_executables(tmp_path)] == [
        "A.exe",
        "z.exe",
    ]
