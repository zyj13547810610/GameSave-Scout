from pathlib import Path

import pytest

from gameshelf.library.models import Game
from gameshelf.platform.windows.known_folders import KnownFolders
from gameshelf.saves.engine_hints import EngineSaveHintProvider
from gameshelf.saves.templates import PathTemplateResolver


@pytest.fixture
def hint_provider(tmp_path: Path) -> EngineSaveHintProvider:
    home = tmp_path / "Profile"
    folders = KnownFolders(
        home=home,
        app_data=home / "AppData" / "Roaming",
        local_app_data=home / "AppData" / "Local",
        local_app_data_low=home / "AppData" / "LocalLow",
        documents=home / "Documents",
        saved_games=home / "Saved Games",
        program_data=tmp_path / "ProgramData",
        public=tmp_path / "Public",
        windows=tmp_path / "Windows",
    )
    return EngineSaveHintProvider(PathTemplateResolver(folders))


def test_renpy_reads_literal_save_directory_and_suggests_appdata(
    tmp_path: Path,
    hint_provider: EngineSaveHintProvider,
) -> None:
    root = tmp_path / "Game"
    script = root / "game" / "options.rpy"
    script.parent.mkdir(parents=True)
    script.write_text('define config.save_directory = "Alice-123"', encoding="utf-8")

    suggestions = hint_provider.suggest(_game("renpy"), root, {})

    assert suggestions[0].path_template == r"<winAppData>\RenPy\Alice-123"
    assert suggestions[0].confidence >= 0.9


def test_renpy_never_executes_expression_or_accepts_unsafe_segment(
    tmp_path: Path,
    hint_provider: EngineSaveHintProvider,
) -> None:
    root = tmp_path / "Game"
    script = root / "game" / "options.rpy"
    script.parent.mkdir(parents=True)
    script.write_text(
        'config.save_directory = make_save_dir()\nconfig.save_directory = "../Alice"',
        encoding="utf-8",
    )

    assert hint_provider.suggest(_game("renpy"), root, {}) == ()


def test_unity_requires_company_and_product_before_local_low_hint(
    tmp_path: Path,
    hint_provider: EngineSaveHintProvider,
) -> None:
    assert hint_provider.suggest(_game("unity"), tmp_path / "Game", {}) == ()
    assert (
        hint_provider.suggest(
            _game("unity"),
            tmp_path / "Game",
            {"companyName": "Bad/Studio", "productName": "Alice"},
        )
        == ()
    )


def test_unity_suggests_local_low_and_player_prefs_from_reliable_metadata(
    tmp_path: Path,
    hint_provider: EngineSaveHintProvider,
) -> None:
    suggestions = hint_provider.suggest(
        _game("unity"),
        tmp_path / "Game",
        {"companyName": "Studio", "productName": "作品"},
    )

    assert [item.path_template for item in suggestions] == [
        r"<winLocalAppDataLow>\Studio\作品",
        r"HKEY_CURRENT_USER\Software\Studio\作品",
    ]
    assert suggestions[1].kind == "registry"


@pytest.mark.parametrize(
    ("engine_id", "filename", "expected"),
    [
        ("rpg_maker_2k", "Save01.lsd", r"<game>\Save*.lsd"),
        ("rpg_maker_xp", "Save1.rxdata", r"<game>\Save*.rxdata"),
        ("rpg_maker_vx", "Save2.rvdata", r"<game>\Save*.rvdata"),
        ("rpg_maker_vx_ace", "Save3.rvdata2", r"<game>\Save*.rvdata2"),
    ],
)
def test_rgss_hint_requires_existing_generation_specific_file(
    tmp_path: Path,
    hint_provider: EngineSaveHintProvider,
    engine_id: str,
    filename: str,
    expected: str,
) -> None:
    root = tmp_path / engine_id
    root.mkdir()
    assert hint_provider.suggest(_game(engine_id), root, {}) == ()
    (root / filename).write_bytes(b"save")

    assert hint_provider.suggest(_game(engine_id), root, {})[0].path_template == expected


@pytest.mark.parametrize(
    ("engine_id", "relative", "expected"),
    [
        ("rpg_maker_mv", "save/slot1.rpgsave", r"<game>\save\*.rpgsave"),
        ("rpg_maker_mz", "www/save/file1.rmmzsave", r"<game>\www\save\*.rmmzsave"),
    ],
)
def test_javascript_rpg_maker_hint_requires_existing_save_file(
    tmp_path: Path,
    hint_provider: EngineSaveHintProvider,
    engine_id: str,
    relative: str,
    expected: str,
) -> None:
    root = tmp_path / engine_id
    save = root.joinpath(*relative.split("/"))
    save.parent.mkdir(parents=True)
    save.write_bytes(b"save")

    assert hint_provider.suggest(_game(engine_id), root, {})[0].path_template == expected


def test_wolf_kirikiri_and_nscripter_require_existing_layout_evidence(
    tmp_path: Path,
    hint_provider: EngineSaveHintProvider,
) -> None:
    wolf = tmp_path / "Wolf"
    wolf_save = wolf / "Data" / "Save"
    wolf_save.mkdir(parents=True)
    kirikiri = tmp_path / "KiriKiri"
    kiri_save = kirikiri / "savedata"
    kiri_save.mkdir(parents=True)
    (kiri_save / "slot.sav").write_bytes(b"save")
    nscripter = tmp_path / "NScripter"
    nscripter.mkdir()
    (nscripter / "save1.dat").write_bytes(b"save")
    (nscripter / "kidoku.dat").write_bytes(b"read")

    assert hint_provider.suggest(_game("wolf_rpg"), wolf, {})[0].kind == "directory"
    assert hint_provider.suggest(_game("kirikiri"), kirikiri, {})[0].kind == "directory"
    nscripter_hints = hint_provider.suggest(_game("nscripter"), nscripter, {})
    assert {item.path_template for item in nscripter_hints} == {
        r"<game>\save*.dat",
        r"<game>\kidoku.dat",
    }


def test_unsupported_engine_returns_no_guessed_hint(
    tmp_path: Path,
    hint_provider: EngineSaveHintProvider,
) -> None:
    assert hint_provider.suggest(_game("siglus"), tmp_path / "Game", {}) == ()


def _game(engine_id: str) -> Game:
    return Game(
        id="game-1",
        scan_root_id="root-1",
        relative_dir="Game",
        install_path_key=r"d:\games\game",
        title="Alice",
        detected_title="Alice",
        status="installed",
        detected_engine_id=engine_id,
        detected_engine_variant=None,
        engine_id=engine_id,
        engine_variant=None,
        engine_is_manual=False,
        engine_confidence=0.96,
        engine_evidence=(),
        engine_rules_version="test",
        main_exe_relpath="Game.exe",
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
