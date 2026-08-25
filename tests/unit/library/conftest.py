from collections.abc import Iterator
from pathlib import Path

import pytest

from gamesave_scout.db.connection import ConnectionFactory
from gamesave_scout.db.migrator import Migrator
from gamesave_scout.db.writer import DbWriter
from gamesave_scout.library.repository import LibraryRepository
from gamesave_scout.library.service import LibraryService


@pytest.fixture
def library_service(tmp_path: Path) -> Iterator[LibraryService]:
    factory = ConnectionFactory(tmp_path / "data" / "library.db")
    Migrator(factory, tmp_path / "backups").migrate()
    writer = DbWriter(factory)
    writer.start()
    service = LibraryService(LibraryRepository(factory), writer)
    try:
        yield service
    finally:
        writer.close()
