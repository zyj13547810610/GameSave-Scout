from pathlib import Path

from gameshelf.bootstrap.application import build_application
from gameshelf.bootstrap.paths import AppPaths


def test_application_bootstrap_creates_only_portable_state(tmp_path: Path) -> None:
    paths = AppPaths.from_root(tmp_path / "便携应用")

    application = build_application(paths)
    try:
        bootstrap = application.api.bootstrap()
        assert bootstrap["ok"] is True
        assert bootstrap["data"]["appName"] == "GameShelf"
        assert bootstrap["data"]["uiScale"] == 1.0
        assert isinstance(bootstrap["data"]["assetSessionToken"], str)
        assert paths.config_file.exists()
        assert paths.database_file.exists()
        assert paths.logs_dir.joinpath("gameshelf.log").exists()
        assert all(
            path == paths.data_dir or paths.data_dir in path.parents
            for path in paths.owned_paths()
        )
    finally:
        application.close()
        application.close()
