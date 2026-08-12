from concurrent.futures import Future
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from gameshelf.bootstrap.paths import AppPaths
from gameshelf.covers.service import CoverService
from gameshelf.db.connection import ConnectionFactory
from gameshelf.db.migrator import Migrator
from gameshelf.db.writer import DbWriter
from gameshelf.library.repository import LibraryRepository
from gameshelf.library.service import LibraryService


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
    service = CoverService(paths, repository, writer)
    try:
        yield paths, factory, writer, service, game.id
    finally:
        writer.close()


def test_clipboard_import_survives_source_lifetime_and_remove_cleans_managed_files(
    cover_harness,
) -> None:
    paths, factory, _, service, game_id = cover_harness
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
    paths, factory, writer, service, game_id = cover_harness
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
    paths, _, _, service, game_id = cover_harness
    source = paths.app_root.parent / "external.png"
    payload = _png("green")
    source.write_bytes(payload)

    service.import_file(game_id, source)
    service.remove(game_id)

    assert source.read_bytes() == payload


def _png(color: str) -> bytes:
    stream = BytesIO()
    Image.new("RGBA", (30, 45), color).save(stream, format="PNG")
    return stream.getvalue()
