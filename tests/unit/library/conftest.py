from collections.abc import Iterator
from pathlib import Path

import pytest

from gameshelf.db.connection import ConnectionFactory
from gameshelf.db.migrator import Migrator
from gameshelf.db.writer import DbWriter
from gameshelf.library.repository import LibraryRepository
from gameshelf.library.service import LibraryService


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
