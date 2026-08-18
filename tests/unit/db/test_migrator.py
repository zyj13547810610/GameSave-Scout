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


def test_migrator_creates_v2_schema_with_version_fields_and_wal(tmp_path: Path) -> None:
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
        game_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(games)")
        }
        cache_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(game_analysis_cache)")
        }

    assert version == user_version == 2
    assert tables >= V1_TABLES
    assert {"version", "detected_version", "version_is_manual"} <= game_columns
    assert cache_columns == {
        "game_id",
        "executable_relpath",
        "file_size",
        "modified_time_ns",
        "ranker_rules_version",
        "engine_rules_version",
        "analyzed_at",
    }
    assert foreign_keys == 1
    assert journal_mode == "wal"


def test_new_database_cascades_game_analysis_cache_with_its_game(
    tmp_path: Path,
) -> None:
    factory = ConnectionFactory(tmp_path / "library.db")
    Migrator(factory, tmp_path / "backups").migrate()

    with factory.connect() as connection:
        connection.execute(
            "INSERT INTO games(id, title, status, added_at, updated_at) "
            "VALUES ('game-1', 'Game', 'save_only', 'now', 'now')"
        )
        connection.execute(
            """
            INSERT INTO game_analysis_cache(
                game_id, executable_relpath, file_size, modified_time_ns,
                ranker_rules_version, engine_rules_version, analyzed_at
            ) VALUES ('game-1', 'Game.exe', 10, 20, 'ranker-1', 'engine-1', 'now')
            """
        )
        connection.execute("DELETE FROM games WHERE id = 'game-1'")
        remaining = connection.execute(
            "SELECT COUNT(*) FROM game_analysis_cache"
        ).fetchone()[0]

    assert remaining == 0


def test_migrator_upgrades_v1_without_splitting_existing_titles(
    tmp_path: Path,
) -> None:
    factory = ConnectionFactory(tmp_path / "library.db")
    migrator = Migrator(factory, tmp_path / "backups")
    with factory.connect() as connection:
        connection.executescript(migrator.migration_sql(1))
        connection.execute(
            "INSERT INTO games (id, title, detected_title, status, added_at, updated_at) "
            "VALUES (?, ?, ?, 'save_only', ?, ?)",
            ("game-1", "AoiChan.v1.0.8", "AoiChan.v1.0.8", "now", "now"),
        )
        connection.commit()

    result = migrator.migrate()

    with factory.connect(readonly=True) as connection:
        row = connection.execute(
            "SELECT title, version, detected_version, version_is_manual "
            "FROM games WHERE id = 'game-1'"
        ).fetchone()
    backups = list((tmp_path / "backups").glob("library-before-v2-*.db"))

    assert result == 2
    assert row["title"] == "AoiChan.v1.0.8"
    assert row["version"] is None
    assert row["detected_version"] is None
    assert row["version_is_manual"] == 0
    assert len(backups) == 1


def test_v1_guided_save_schema_has_single_active_slot_and_review_fields(
    tmp_path: Path,
) -> None:
    factory = ConnectionFactory(tmp_path / "library.db")
    Migrator(factory, tmp_path / "backups").migrate()

    with factory.connect() as connection:
        session_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'save_detection_sessions'"
        ).fetchone()[0]
        discovery_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(save_discoveries)")
        }
        indexes = {
            row[1]
            for row in connection.execute("PRAGMA index_list(save_detection_sessions)")
        }

    assert "interrupted" in session_sql
    assert "active_slot" in session_sql
    assert "save_detection_one_active" in indexes
    assert {
        "path_key",
        "representative_files_json",
        "first_changed_at",
        "last_changed_at",
        "mark_offset_ms",
        "affected_by_overflow",
        "affected_by_truncation",
        "preselected",
        "save_location_id",
    } <= discovery_columns


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

    backups = list((tmp_path / "backups").glob("library-before-v2-*.db"))
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
