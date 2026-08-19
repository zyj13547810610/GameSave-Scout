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


def test_migrator_creates_v3_schema_with_groups_version_fields_and_wal(
    tmp_path: Path,
) -> None:
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

    assert version == user_version == 3
    assert tables >= V1_TABLES
    assert {"game_groups", "game_group_memberships"} <= tables
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


@pytest.mark.parametrize("version", [1, 2])
def test_migrator_rejects_legacy_schema_without_modifying_database(
    tmp_path: Path, version: int
) -> None:
    factory = ConnectionFactory(tmp_path / "library.db")
    migrator = Migrator(factory, tmp_path / "backups")
    with factory.connect() as connection:
        for target_version in range(1, version + 1):
            connection.executescript(migrator.migration_sql(target_version))
        connection.execute(
            "INSERT INTO games (id, title, detected_title, status, added_at, updated_at) "
            "VALUES (?, ?, ?, 'save_only', ?, ?)",
            ("game-1", "AoiChan.v1.0.8", "AoiChan.v1.0.8", "now", "now"),
        )
        connection.commit()
    database_before = factory.database_file.read_bytes()

    with pytest.raises(MigrationError, match="手动移动或删除.*library.db") as captured:
        migrator.migrate()

    with factory.connect(readonly=True) as connection:
        row = connection.execute(
            "SELECT title FROM games WHERE id = 'game-1'"
        ).fetchone()

    assert captured.value.backup_file is None
    assert factory.database_file.read_bytes() == database_before
    assert row["title"] == "AoiChan.v1.0.8"
    assert not (tmp_path / "backups").exists()


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


def test_migrator_rejects_version_zero_database_with_user_tables(
    tmp_path: Path,
) -> None:
    factory = ConnectionFactory(tmp_path / "library.db")
    with factory.connect() as connection:
        connection.execute("CREATE TABLE legacy(value TEXT)")
        connection.execute("INSERT INTO legacy VALUES ('kept')")
        connection.commit()
    database_before = factory.database_file.read_bytes()

    with pytest.raises(MigrationError, match="手动移动或删除.*library.db") as captured:
        Migrator(factory, tmp_path / "backups").migrate()

    assert captured.value.backup_file is None
    assert factory.database_file.read_bytes() == database_before
    assert not (tmp_path / "backups").exists()
    with factory.connect(readonly=True) as connection:
        assert connection.execute("SELECT value FROM legacy").fetchone()[0] == "kept"


def test_failed_blank_database_creation_does_not_advance_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = ConnectionFactory(tmp_path / "library.db")
    monkeypatch.setattr(Migrator, "migration_sql", lambda *_: "INVALID SQL")

    with pytest.raises(MigrationError) as captured:
        Migrator(factory, tmp_path / "backups").migrate()

    assert captured.value.backup_file is None
    with factory.connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchone()[0] == 0
