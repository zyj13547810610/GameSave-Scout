from pathlib import Path

import pytest

from gameshelf.bootstrap.paths import AppPaths, DataDirectoryError, runtime_root


def test_from_root_places_every_persistent_path_under_data(tmp_path: Path) -> None:
    paths = AppPaths.from_root(tmp_path / "GameShelf")
    paths.ensure_writable()

    assert paths.database_file == paths.data_dir / "library.db"
    assert paths.config_file == paths.data_dir / "config.json"
    assert paths.covers_original_dir == paths.data_dir / "covers" / "original"
    assert paths.covers_thumbs_dir == paths.data_dir / "covers" / "thumbs"
    assert paths.rules_dir == paths.data_dir / "rules"
    assert paths.user_engine_rules_dir == paths.data_dir / "rules" / "user" / "engines"
    assert paths.user_save_rules_dir == paths.data_dir / "rules" / "user" / "saves"
    assert paths.ludusavi_active_dir == paths.data_dir / "rules" / "ludusavi"
    assert paths.rule_settings_file == paths.data_dir / "rules" / "settings.json"
    assert paths.webview_dir == paths.data_dir / "webview"
    assert all(path.exists() for path in paths.required_directories())
    assert not (paths.data_dir / "manifests").exists()
    assert all(
        path == paths.data_dir or paths.data_dir in path.parents for path in paths.owned_paths()
    )


def test_legacy_manifests_path_is_probe_only_and_is_not_owned(tmp_path: Path) -> None:
    paths = AppPaths.from_root(tmp_path / "GameShelf")

    assert paths.legacy_manifests_dir == paths.data_dir / "manifests"
    assert paths.legacy_manifests_dir not in paths.required_directories()
    assert paths.legacy_manifests_dir not in paths.owned_paths()


def test_runtime_root_uses_executable_parent_when_frozen(tmp_path: Path) -> None:
    executable = tmp_path / "便携版" / "GameShelf.exe"

    assert runtime_root(frozen=True, executable=executable) == executable.parent


def test_runtime_root_uses_repository_root_during_source_development() -> None:
    expected = Path(__file__).resolve().parents[3]

    assert runtime_root(frozen=False) == expected


def test_ensure_writable_wraps_os_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = AppPaths.from_root(tmp_path)

    def deny(*args: object, **kwargs: object) -> None:
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "mkdir", deny)

    with pytest.raises(DataDirectoryError, match="无法写入"):
        paths.ensure_writable()
