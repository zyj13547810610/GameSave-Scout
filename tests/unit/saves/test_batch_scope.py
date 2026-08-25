from pathlib import Path

import pytest

from gamesave_scout.bootstrap.config import AppConfig, BatchSaveCustomRoot
from gamesave_scout.platform.windows.known_folders import KnownFolders
from gamesave_scout.saves.batch_scope import BatchScopeBuilder


def test_scope_builder_selects_enabled_roots_and_keeps_nested_scope(
    tmp_path: Path,
) -> None:
    folders = _folders(tmp_path)
    nested = folders.documents / "Approved"
    config = AppConfig(
        batch_save_custom_roots=(
            BatchSaveCustomRoot("nested", str(nested), True, 8),
            BatchSaveCustomRoot("disabled", str(tmp_path / "Disabled"), False, 4),
        )
    )

    scopes = BatchScopeBuilder(folders, config).build(
        ("documents", "saved_games"),
        ("nested", "disabled"),
    )

    assert [scope.key for scope in scopes] == [
        "documents",
        "saved_games",
        "custom:nested",
    ]
    assert scopes[-1].root == nested
    assert scopes[-1].max_depth == 8


def test_scope_builder_prefers_custom_scope_for_the_same_root(tmp_path: Path) -> None:
    folders = _folders(tmp_path)
    config = AppConfig(
        batch_save_custom_roots=(BatchSaveCustomRoot("same", str(folders.documents), True, 3),)
    )

    scopes = BatchScopeBuilder(folders, config).build(
        ("documents",),
        ("same",),
    )

    assert [scope.key for scope in scopes] == ["custom:same"]


def test_scope_builder_exposes_all_five_standard_roots(tmp_path: Path) -> None:
    folders = _folders(tmp_path)

    scopes = BatchScopeBuilder(folders, AppConfig()).build(
        (
            "documents",
            "saved_games",
            "app_data",
            "local_app_data",
            "local_app_data_low",
        ),
        (),
    )

    assert [scope.key for scope in scopes] == [
        "documents",
        "saved_games",
        "app_data",
        "local_app_data",
        "local_app_data_low",
    ]
    assert all(scope.source == "standard" for scope in scopes)


def test_scope_builder_reads_latest_config_when_building(tmp_path: Path) -> None:
    folders = _folders(tmp_path)
    current = AppConfig()
    builder = BatchScopeBuilder(folders, lambda: current)
    custom = BatchSaveCustomRoot("later", str(tmp_path / "Later"), True, 5)

    current = AppConfig(batch_save_custom_roots=(custom,))
    scopes = builder.build((), ("later",))

    assert [scope.key for scope in scopes] == ["custom:later"]
    assert scopes[0].max_depth == 5


def test_scope_builder_rejects_unknown_ids_and_drive_roots(tmp_path: Path) -> None:
    folders = _folders(tmp_path)
    invalid = AppConfig(batch_save_custom_roots=(BatchSaveCustomRoot("drive", "D:\\", True, 3),))

    with pytest.raises(ValueError, match="盘符根"):
        BatchScopeBuilder(folders, invalid).build((), ("drive",))
    with pytest.raises(ValueError, match="未知"):
        BatchScopeBuilder(folders, AppConfig()).build(("other",), ())


def _folders(tmp_path: Path) -> KnownFolders:
    home = tmp_path / "Profile"
    return KnownFolders(
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
