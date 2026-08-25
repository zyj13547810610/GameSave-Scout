from pathlib import Path

import pytest

from gameshelf.library.models import Game
from gameshelf.platform.windows.known_folders import KnownFolders
from gameshelf.saves.engine_hints import EngineSaveHintProvider, load_engine_metadata
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


def test_renpy_metadata_reads_literal_save_directory(tmp_path: Path) -> None:
    root = tmp_path / "Game"
    script = root / "game" / "options.rpy"
    script.parent.mkdir(parents=True)
    script.write_text('define config.save_directory = "Alice-123"', encoding="utf-8")

    assert load_engine_metadata(_game("renpy"), root) == {
        "renpy_save_directory": "Alice-123"
    }


@pytest.mark.parametrize(
    "assignment",
    [
        "config.save_directory = make_save_dir()",
        'config.save_directory = "../Alice"',
        'config.save_directory = "CON"',
        'config.save_directory = "Alice."',
        'config.save_directory = "Alice "',
        f'config.save_directory = "{"A" * 129}"',
    ],
)
def test_renpy_metadata_never_executes_or_accepts_unsafe_segment(
    tmp_path: Path,
    assignment: str,
) -> None:
    root = tmp_path / "Game"
    script = root / "game" / "options.rpy"
    script.parent.mkdir(parents=True)
    script.write_text(assignment, encoding="utf-8")

    assert load_engine_metadata(_game("renpy"), root) == {}


def test_renpy_metadata_scan_is_depth_and_read_bounded(tmp_path: Path) -> None:
    root = tmp_path / "Game"
    too_deep = root / "game" / "one" / "two" / "three" / "four" / "options.rpy"
    too_deep.parent.mkdir(parents=True)
    too_deep.write_text('config.save_directory = "TooDeep"', encoding="utf-8")

    oversized = root / "game" / "oversized.rpy"
    oversized.write_text(
        "#" * (256 * 1024) + '\nconfig.save_directory = "PastLimit"',
        encoding="utf-8",
    )

    assert load_engine_metadata(_game("renpy"), root) == {}


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
    assert [item.availability for item in suggestions] == ["predicted", "predicted"]

    Path(suggestions[0].display_path).mkdir(parents=True)
    assert hint_provider.suggest(
        _game("unity"),
        tmp_path / "Game",
        {"company_name": "Studio", "product_name": "作品"},
    )[0].availability == "found"


@pytest.mark.parametrize(
    ("engine_id", "relative"),
    [
        ("renpy", "game/options.rpy"),
        ("rpg_maker_2k", "Save01.lsd"),
        ("rpg_maker_xp", "Save1.rxdata"),
        ("rpg_maker_vx", "Save2.rvdata"),
        ("rpg_maker_vx_ace", "Save3.rvdata2"),
        ("rpg_maker_mv", "save/slot1.rpgsave"),
        ("rpg_maker_mz", "www/save/file1.rmmzsave"),
        ("nscripter", "save1.dat"),
    ],
)
def test_migrated_engines_no_longer_emit_code_suggestions(
    tmp_path: Path,
    hint_provider: EngineSaveHintProvider,
    engine_id: str,
    relative: str,
) -> None:
    root = tmp_path / engine_id
    evidence = root.joinpath(*relative.split("/"))
    evidence.parent.mkdir(parents=True)
    if engine_id == "renpy":
        evidence.write_text(
            'define config.save_directory = "Migrated"', encoding="utf-8"
        )
    else:
        evidence.write_bytes(b"save")

    assert hint_provider.suggest(_game(engine_id), root, {}) == ()


def test_wolf_and_kirikiri_require_existing_layout_evidence(
    tmp_path: Path,
    hint_provider: EngineSaveHintProvider,
) -> None:
    wolf = tmp_path / "Wolf"
    wolf_save = wolf / "Data" / "Save"
    wolf_save.mkdir(parents=True)
    assert hint_provider.suggest(_game("wolf_rpg"), wolf, {}) == ()
    (wolf_save / "SaveData01.sav").write_bytes(b"save")
    kirikiri = tmp_path / "KiriKiri"
    kiri_save = kirikiri / "savedata"
    kiri_save.mkdir(parents=True)
    (kiri_save / "slot.sav").write_bytes(b"save")
    assert hint_provider.suggest(_game("wolf_rpg"), wolf, {})[0].kind == "directory"
    assert hint_provider.suggest(_game("kirikiri"), kirikiri, {})[0].kind == "directory"


def test_unreal_requires_a_valid_project_file_and_never_guesses_from_directory(
    tmp_path: Path,
    hint_provider: EngineSaveHintProvider,
) -> None:
    root = tmp_path / "GuessedProject"
    root.mkdir()
    game = _game("unreal")

    assert load_engine_metadata(game, root) == {}
    assert hint_provider.suggest(game, root, {}) == ()

    (root / "Broken.uproject").write_text("{}", encoding="utf-8")
    assert load_engine_metadata(game, root) == {}


def test_unreal_reads_bounded_project_metadata_and_predicts_savegames(
    tmp_path: Path,
    hint_provider: EngineSaveHintProvider,
) -> None:
    root = tmp_path / "UnrealGame"
    project = root / "Project" / "ReliableName.uproject"
    project.parent.mkdir(parents=True)
    project.write_text('{"FileVersion": 3}', encoding="utf-8")
    game = _game("unreal")

    metadata = load_engine_metadata(game, root)
    suggestions = hint_provider.suggest(game, root, metadata)

    assert metadata == {"project_name": "ReliableName"}
    assert suggestions[0].path_template == (
        r"<winLocalAppData>\ReliableName\Saved\SaveGames"
    )
    assert suggestions[0].availability == "predicted"

    Path(suggestions[0].display_path).mkdir(parents=True)
    assert hint_provider.suggest(game, root, metadata)[0].availability == "found"


def test_godot_reads_only_literal_project_settings_and_supports_default_path(
    tmp_path: Path,
    hint_provider: EngineSaveHintProvider,
) -> None:
    root = tmp_path / "GodotGame"
    root.mkdir()
    project = root / "project.godot"
    project.write_text(
        '[application]\nconfig/name="Project 作品"\n'
        "config/use_custom_user_dir=false\n",
        encoding="utf-8",
    )
    game = _game("godot")

    metadata = load_engine_metadata(game, root)
    suggestions = hint_provider.suggest(game, root, metadata)

    assert metadata == {"project_name": "Project 作品"}
    assert suggestions[0].path_template == (
        r"<winAppData>\Godot\app_userdata\Project 作品"
    )
    assert suggestions[0].availability == "predicted"

    project.write_text(
        '[application]\nconfig/name=tr("Project")\n', encoding="utf-8"
    )
    assert load_engine_metadata(game, root) == {}
    assert hint_provider.suggest(game, root, {}) == ()


def test_godot_custom_user_directory_accepts_only_safe_relative_segments(
    tmp_path: Path,
    hint_provider: EngineSaveHintProvider,
) -> None:
    root = tmp_path / "GodotGame"
    root.mkdir()
    project = root / "project.godot"
    game = _game("godot")
    project.write_text(
        '[application]\nconfig/name="Project"\n'
        "config/use_custom_user_dir=true\n"
        'config/custom_user_dir_name="Studio/Game"\n',
        encoding="utf-8",
    )

    metadata = load_engine_metadata(game, root)
    suggestions = hint_provider.suggest(game, root, metadata)

    assert metadata == {"godot_custom_user_dir": r"Studio\Game"}
    assert suggestions[0].path_template == r"<winAppData>\Studio\Game"

    project.write_text(
        '[application]\nconfig/name="Project"\n'
        "config/use_custom_user_dir=true\n"
        'config/custom_user_dir_name="../Escape"\n',
        encoding="utf-8",
    )
    assert load_engine_metadata(game, root) == {}


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
