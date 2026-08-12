import sqlite3
from pathlib import Path

import pytest

from gameshelf.db.connection import ConnectionFactory
from gameshelf.db.migrator import MigrationError, Migrator

V1_TABLES = {
    "scan_roots",
    "games",
    "save_locations",
    "scan_sessions",
    "scan_observations",
    "save_detection_sessions",
    "save_discoveries",
    "settings",
}


def test_migrator_creates_v1_schema_with_foreign_keys_and_wal(tmp_path: Path) -> None:
    factory = ConnectionFactory(tmp_path / "data" / "library.db")

    version = Migrator(factory, tmp_path / "backups").migrate()

    with factory.connect() as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        user_version = connection.execute("PRAGMA user_version").fetchone()[0]

    assert version == user_version == 1
    assert tables >= V1_TABLES
    assert foreign_keys == 1
    assert journal_mode == "wal"


def test_readonly_connection_uses_rows_and_rejects_writes(tmp_path: Path) -> None:
    factory = ConnectionFactory(tmp_path / "library.db")
    Migrator(factory, tmp_path / "backups").migrate()

    with factory.connect(readonly=True) as connection:
        row = connection.execute("SELECT name FROM sqlite_master WHERE name='games'").fetchone()
        assert row["name"] == "games"
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("CREATE TABLE forbidden(value TEXT)")


def test_migrator_backs_up_existing_database_before_upgrade(tmp_path: Path) -> None:
    factory = ConnectionFactory(tmp_path / "library.db")
    with factory.connect() as connection:
        connection.execute("CREATE TABLE legacy(value TEXT)")
        connection.execute("INSERT INTO legacy VALUES ('kept')")
        connection.commit()

    Migrator(factory, tmp_path / "backups").migrate()

    backups = list((tmp_path / "backups").glob("library-before-v1-*.db"))
    assert len(backups) == 1
    backup_factory = ConnectionFactory(backups[0])
    with backup_factory.connect(readonly=True) as connection:
        assert connection.execute("SELECT value FROM legacy").fetchone()[0] == "kept"


def test_failed_migration_preserves_original_and_does_not_advance_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = ConnectionFactory(tmp_path / "library.db")
    with factory.connect() as connection:
        connection.execute("CREATE TABLE legacy(value TEXT)")
        connection.execute("INSERT INTO legacy VALUES ('kept')")
        connection.commit()
    monkeypatch.setattr(Migrator, "migration_sql", lambda *_: "INVALID SQL")

    with pytest.raises(MigrationError) as captured:
        Migrator(factory, tmp_path / "backups").migrate()

    assert captured.value.backup_file is not None
    assert captured.value.backup_file.exists()
    with factory.connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
        assert connection.execute("SELECT value FROM legacy").fetchone()[0] == "kept"
