from pathlib import Path

from gameshelf.bootstrap.application import build_application
from gameshelf.bootstrap.paths import AppPaths


def test_application_bootstrap_creates_only_portable_state(tmp_path: Path) -> None:
    paths = AppPaths.from_root(tmp_path / "便携应用")

    application = build_application(paths)
    try:
        assert application.api.bootstrap() == {
            "ok": True,
            "data": {"appName": "GameShelf", "schemaVersion": 1, "portable": True},
        }
        assert paths.database_file.exists()
        assert paths.logs_dir.joinpath("gameshelf.log").exists()
        assert all(
            path == paths.data_dir or paths.data_dir in path.parents
            for path in paths.owned_paths()
        )
    finally:
        application.close()
        application.close()
