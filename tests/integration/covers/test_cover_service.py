from concurrent.futures import Future
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from gamesave_scout.bootstrap.paths import AppPaths
from gamesave_scout.covers.service import CoverService
from gamesave_scout.db.connection import ConnectionFactory
from gamesave_scout.db.migrator import Migrator
from gamesave_scout.db.writer import DbWriter
from gamesave_scout.library.repository import LibraryRepository
from gamesave_scout.library.service import LibraryService


class MutableCoverPolicy:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def __call__(self) -> bool:
        return self.enabled


@pytest.fixture
def cover_harness(tmp_path: Path):
    paths = AppPaths.from_root(tmp_path / "portable")
    paths.ensure_writable()
    factory = ConnectionFactory(paths.database_file)
    Migrator(factory, paths.backups_dir).migrate()
    writer = DbWriter(factory)
    writer.start()
    repository = LibraryRepository(factory)
    library = LibraryService(repository, writer)
    root_path = tmp_path / "games"
    (root_path / "Alice").mkdir(parents=True)
    root = library.add_root(str(root_path), "children", 1, [])
    game = library.create_game_for_test(root.id, "Alice", "Alice")
    policy = MutableCoverPolicy(True)
    service = CoverService(paths, repository, writer, policy)
    try:
        yield paths, factory, writer, service, game.id, policy
    finally:
        writer.close()


def test_clipboard_import_survives_source_lifetime_and_remove_cleans_managed_files(
    cover_harness,
) -> None:
    paths, factory, _, service, game_id, _ = cover_harness
    cover = service.import_clipboard_png(game_id, _png("red"))

    assert (paths.data_dir / cover.original_relpath).is_file()
    assert (paths.data_dir / cover.thumb_relpath).is_file()
    service.remove(game_id)

    assert not (paths.data_dir / cover.original_relpath).exists()
    assert not (paths.data_dir / cover.thumb_relpath).exists()
    with factory.connect(readonly=True) as connection:
        row = connection.execute(
            "SELECT cover_original_relpath, cover_revision FROM games WHERE id = ?",
            (game_id,),
        ).fetchone()
    assert row[0] is None
    assert row[1] == 2


def test_failed_database_update_keeps_old_cover_and_removes_new_files(
    cover_harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, factory, writer, service, game_id, _ = cover_harness
    old = service.import_clipboard_png(game_id, _png("red"))
    original_submit = writer.submit

    def fail_once(_operation):
        failed: Future[object] = Future()
        failed.set_exception(RuntimeError("planned database failure"))
        monkeypatch.setattr(writer, "submit", original_submit)
        return failed

    monkeypatch.setattr(writer, "submit", fail_once)
    with pytest.raises(RuntimeError, match="planned"):
        service.import_clipboard_png(game_id, _png("blue"))

    managed = {
        path.relative_to(paths.data_dir).as_posix()
        for folder in (paths.covers_original_dir, paths.covers_thumbs_dir)
        for path in folder.iterdir()
    }
    assert managed == {old.original_relpath, old.thumb_relpath}
    with factory.connect(readonly=True) as connection:
        row = connection.execute(
            "SELECT cover_original_relpath, cover_thumb_relpath FROM games WHERE id = ?",
            (game_id,),
        ).fetchone()
    assert tuple(row) == (old.original_relpath, old.thumb_relpath)


def test_import_file_never_modifies_or_deletes_external_source(cover_harness) -> None:
    paths, _, _, service, game_id, _ = cover_harness
    source = paths.app_root.parent / "external.png"
    payload = _png("green")
    source.write_bytes(payload)

    service.import_file(game_id, source)
    service.remove(game_id)

    assert source.read_bytes() == payload


def test_cleanup_managed_files_deletes_only_direct_managed_cover_files(
    cover_harness,
) -> None:
    paths, _, _, service, _, _ = cover_harness
    removable = paths.covers_original_dir / "remove.png"
    stuck = paths.covers_thumbs_dir / "stuck.webp"
    external = paths.data_dir.parent / "external.png"
    removable.write_bytes(b"managed")
    stuck.mkdir()
    external.write_bytes(b"external")

    warnings = service.cleanup_managed_files(
        (
            "covers/original/remove.png",
            "covers/thumbs/stuck.webp",
            "../external.png",
        )
    )

    assert warnings == 2
    assert not removable.exists()
    assert stuck.is_dir()
    assert external.read_bytes() == b"external"


def test_service_reads_the_current_optimization_policy_for_each_import(
    cover_harness,
) -> None:
    paths, _, _, service, game_id, policy = cover_harness

    optimized = service.import_clipboard_png(game_id, _png_size((2560, 1440)))
    with Image.open(paths.data_dir / optimized.original_relpath) as image:
        assert image.size == (1920, 1080)
        assert image.format == "JPEG"

    policy.enabled = False
    preserved = service.import_clipboard_png(game_id, _png_size((2560, 1440)))
    with Image.open(paths.data_dir / preserved.original_relpath) as image:
        assert image.size == (2560, 1440)
        assert image.format == "PNG"


def _png(color: str) -> bytes:
    stream = BytesIO()
    Image.new("RGBA", (30, 45), color).save(stream, format="PNG")
    return stream.getvalue()


def _png_size(size: tuple[int, int]) -> bytes:
    stream = BytesIO()
    Image.new("RGB", size, "#336699").save(stream, format="PNG")
    return stream.getvalue()
