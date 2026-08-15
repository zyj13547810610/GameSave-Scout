from logging.handlers import RotatingFileHandler
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
        assert application.guided_saves.current() is None
        assert application.api.current_guided_save_detection() == {
            "ok": True,
            "data": None,
        }
        assert all(
            path == paths.data_dir or paths.data_dir in path.parents
            for path in paths.owned_paths()
        )
    finally:
        application.close()
        application.close()


def test_application_close_releases_its_logging_handler(tmp_path: Path) -> None:
    application = build_application(AppPaths.from_root(tmp_path / "便携应用"))
    logger = application.logger

    application.close()

    assert logger.propagate is True
    assert not any(isinstance(handler, RotatingFileHandler) for handler in logger.handlers)


def test_application_closes_guided_session_before_shared_writer(
    tmp_path: Path, monkeypatch
) -> None:
    application = build_application(AppPaths.from_root(tmp_path / "便携应用"))
    order: list[str] = []
    original_guided_close = application.guided_saves.close
    original_writer_close = application.writer.close

    def close_guided() -> None:
        order.append("guided")
        original_guided_close()

    def close_writer(timeout: float = 5.0) -> None:
        order.append("writer")
        original_writer_close(timeout)

    monkeypatch.setattr(application.guided_saves, "close", close_guided)
    monkeypatch.setattr(application.writer, "close", close_writer)

    application.close()
    application.close()

    assert order == ["guided", "writer"]
