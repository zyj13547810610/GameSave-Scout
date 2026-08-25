from pathlib import Path

from gamesave_scout.scanning.executable_ranker import (
    is_potential_game_executable_name,
    rank_executables,
)
from gamesave_scout.scanning.pe_metadata import PeMetadata, read_pe_metadata


def test_ranker_rejects_installers_and_prefers_title_match(
    tmp_path: Path, monkeypatch
) -> None:
    game = tmp_path / "Alice"
    game.mkdir()
    for name in ["Alice.exe", "setup.exe", "unins000.exe", "crashreporter.exe"]:
        (game / name).write_bytes(b"MZ")
    monkeypatch.setattr(
        "gamesave_scout.scanning.executable_ranker.read_pe_metadata",
        lambda path: PeMetadata(
            product_name="Alice" if path.name == "Alice.exe" else "",
            file_description="",
            company_name="",
            architecture="x64",
        ),
    )

    ranked = rank_executables(game)

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
    for name in [
        "setup.exe",
        "CONFIG.EXE",
        "UnityCrashHandler32.exe",
        "crashpad_handler.exe",
        "UnrealCEFSubProcess.exe",
        "delfile.exe",
        "chromedriver.exe",
        "Textractor.exe",
        "TextractorCLI.exe",
        "EasyAntiCheat_EOS_Setup.exe",
        "readme.txt",
    ]:
        assert is_potential_game_executable_name(name) is False


def test_ranker_skips_the_entire_mods_subtree(tmp_path: Path, monkeypatch) -> None:
    game = tmp_path / "RimWorld.v1.4.3901 HSK"
    mod_tool = game / "Mods" / "1" / "Source" / "TextExtractor.exe"
    mod_tool.parent.mkdir(parents=True)
    mod_tool.write_bytes(b"MZ")
    (game / "RimWorldWin64.exe").write_bytes(b"MZ")
    monkeypatch.setattr(
        "gamesave_scout.scanning.executable_ranker.read_pe_metadata",
        lambda _: PeMetadata("", "", "", "unknown"),
    )

    assert [item.relative_path for item in rank_executables(game)] == [
        "RimWorldWin64.exe"
    ]


def test_ranker_penalizes_nested_developer_tools_and_ignores_self_metadata(
    tmp_path: Path, monkeypatch
) -> None:
    game = tmp_path / "RimWorld.v1.4.3901 HSK"
    tool = game / "Developer" / "Source" / "Tool" / "bin" / "Debug"
    tool.mkdir(parents=True)
    (game / "RimWorldWin64.exe").write_bytes(b"MZ")
    (tool / "ModAssetCompiler.exe").write_bytes(b"MZ")
    monkeypatch.setattr(
        "gamesave_scout.scanning.executable_ranker.read_pe_metadata",
        lambda path: PeMetadata(
            product_name=path.stem if path.name == "ModAssetCompiler.exe" else "",
            file_description=path.stem if path.name == "ModAssetCompiler.exe" else "",
            company_name="",
            architecture="unknown",
        ),
    )

    ranked = rank_executables(game)

    assert [item.relative_path for item in ranked] == [
        "RimWorldWin64.exe",
        "Developer/Source/Tool/bin/Debug/ModAssetCompiler.exe",
    ]
    assert "nested_executable" in ranked[1].evidence
    assert "auxiliary_directory" in ranked[1].evidence
    assert "product_name_matches_directory" not in ranked[1].evidence
    assert "file_description_matches_directory" not in ranked[1].evidence


def test_ranker_prefers_a_title_segment_over_a_larger_generic_engine(
    tmp_path: Path, monkeypatch
) -> None:
    game = tmp_path / "Summer Pockets REFLECTION BLUE"
    game.mkdir()
    (game / "SiglusEngine.exe").write_bytes(b"MZ" + b"\0" * 1024 * 1024)
    (game / "SummerPockets（枫笛汉化组）.exe").write_bytes(b"MZ")
    monkeypatch.setattr(
        "gamesave_scout.scanning.executable_ranker.read_pe_metadata",
        lambda _: PeMetadata("", "", "", "x86"),
    )

    ranked = rank_executables(game)

    assert ranked[0].relative_path == "SummerPockets（枫笛汉化组）.exe"
    assert "filename_matches_title_segment" in ranked[0].evidence


def test_ranker_prefers_a_nested_unity_player_layout(
    tmp_path: Path, monkeypatch
) -> None:
    game = tmp_path / "Legend.of.Mortal"
    build = game / "Build"
    data = build / "Mortal_Data"
    data.mkdir(parents=True)
    (game / "GameLauncher.exe").write_bytes(b"MZ")
    (build / "Mortal.exe").write_bytes(b"MZ")
    (build / "UnityPlayer.dll").write_bytes(b"MZ")
    (data / "globalgamemanagers").write_bytes(b"unity")
    (build / "UnityCrashHandler64.exe").write_bytes(b"MZ")
    monkeypatch.setattr(
        "gamesave_scout.scanning.executable_ranker.read_pe_metadata",
        lambda _: PeMetadata("", "", "", "x64"),
    )

    ranked = rank_executables(game)

    assert ranked[0].relative_path == "Build/Mortal.exe"
    assert "unity_player_layout" in ranked[0].evidence
    assert all("UnityCrashHandler" not in item.relative_path for item in ranked)


def test_ranker_prefers_an_unreal_bootstrap_executable(
    tmp_path: Path, monkeypatch
) -> None:
    game = tmp_path / "Operation.Lovecraft.Fallen.Doll.v0.4.9"
    engine_bin = game / "Engine" / "Binaries" / "Win64"
    project_bin = game / "Paralogue" / "Binaries" / "Win64"
    engine_bin.mkdir(parents=True)
    project_bin.mkdir(parents=True)
    (game / "FallenDoll.exe").write_bytes(b"MZ")
    (engine_bin / "UnrealCEFSubProcess.exe").write_bytes(b"MZ")
    (project_bin / "Paralogue-Win64-Shipping.exe").write_bytes(b"MZ")
    monkeypatch.setattr(
        "gamesave_scout.scanning.executable_ranker.read_pe_metadata",
        lambda path: PeMetadata(
            "BootstrapPackagedGame" if path.name == "FallenDoll.exe" else "",
            "",
            "",
            "x64",
        ),
    )

    ranked = rank_executables(game)

    assert ranked[0].relative_path == "FallenDoll.exe"
    assert "unreal_bootstrap_layout" in ranked[0].evidence
    assert all("UnrealCEFSubProcess" not in item.relative_path for item in ranked)


def test_ranker_uses_unreal_shipping_executable_as_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    game = tmp_path / "UnrealGame"
    engine_bin = game / "Engine" / "Binaries" / "Win64"
    project_bin = game / "ProjectName" / "Binaries" / "Win64"
    engine_bin.mkdir(parents=True)
    project_bin.mkdir(parents=True)
    shipping = project_bin / "ProjectName-Win64-Shipping.exe"
    shipping.write_bytes(b"MZ")
    monkeypatch.setattr(
        "gamesave_scout.scanning.executable_ranker.read_pe_metadata",
        lambda _: PeMetadata("", "", "", "x64"),
    )

    ranked = rank_executables(game)

    assert ranked[0].relative_path == (
        "ProjectName/Binaries/Win64/ProjectName-Win64-Shipping.exe"
    )
    assert "unreal_shipping_binary" in ranked[0].evidence


def test_ranker_excludes_known_auxiliary_executables(
    tmp_path: Path, monkeypatch
) -> None:
    for name in ["HENPRI.exe", "delfile.exe", "UnityCrashHandler32.exe"]:
        (tmp_path / name).write_bytes(b"MZ")
    monkeypatch.setattr(
        "gamesave_scout.scanning.executable_ranker.read_pe_metadata",
        lambda path: PeMetadata(
            product_name=path.stem,
            file_description=path.stem,
            company_name="",
            architecture="x86",
        ),
    )

    assert [item.relative_path for item in rank_executables(tmp_path)] == [
        "HENPRI.exe"
    ]


def test_ranker_excludes_support_directories_and_auxiliary_executables(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "helper.exe").write_bytes(b"MZ")
    (tmp_path / "Game.exe").write_bytes(b"MZ")
    (tmp_path / "config.exe").write_bytes(b"MZ")
    monkeypatch.setattr(
        "gamesave_scout.scanning.executable_ranker.read_pe_metadata",
        lambda _: PeMetadata("", "", "", "x86"),
    )

    ranked = rank_executables(tmp_path)

    assert [item.relative_path for item in ranked] == ["Game.exe"]


def test_ranking_is_deterministic_for_equal_candidates(tmp_path: Path, monkeypatch) -> None:
    for name in ["z.exe", "A.exe"]:
        (tmp_path / name).write_bytes(b"MZ")
    monkeypatch.setattr(
        "gamesave_scout.scanning.executable_ranker.read_pe_metadata",
        lambda _: PeMetadata("", "", "", "unknown"),
    )

    assert [item.relative_path for item in rank_executables(tmp_path)] == [
        "A.exe",
        "z.exe",
    ]
