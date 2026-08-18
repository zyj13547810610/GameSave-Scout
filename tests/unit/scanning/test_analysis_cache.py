from pathlib import Path

from gameshelf.db.connection import ConnectionFactory
from gameshelf.db.migrator import Migrator
from gameshelf.scanning.analysis_cache import (
    AnalysisCacheEntry,
    AnalysisCacheRepository,
    PendingAnalysisCache,
    delete_analysis_cache,
    upsert_analysis_cache,
)


def _database(tmp_path: Path) -> ConnectionFactory:
    factory = ConnectionFactory(tmp_path / "data" / "library.db")
    Migrator(factory, tmp_path / "backups").migrate()
    with factory.connect() as connection:
        connection.execute(
            "INSERT INTO games(id, title, status, added_at, updated_at) "
            "VALUES ('game-1', 'Game', 'save_only', 'now', 'now')"
        )
    return factory


def test_cache_repository_returns_none_for_an_unknown_game(tmp_path: Path) -> None:
    factory = _database(tmp_path)

    assert AnalysisCacheRepository(factory).get("missing") is None


def test_cache_repository_maps_every_persisted_field(tmp_path: Path) -> None:
    factory = _database(tmp_path)
    pending = PendingAnalysisCache(
        executable_relpath="bin/Game.exe",
        file_size=123,
        modified_time_ns=456,
        ranker_rules_version="ranker-1",
        engine_rules_version="engine-1",
    )
    with factory.connect() as connection:
        upsert_analysis_cache(connection, "game-1", pending, "2026-08-18T01:02:03Z")

    assert AnalysisCacheRepository(factory).get("game-1") == AnalysisCacheEntry(
        game_id="game-1",
        executable_relpath="bin/Game.exe",
        file_size=123,
        modified_time_ns=456,
        ranker_rules_version="ranker-1",
        engine_rules_version="engine-1",
        analyzed_at="2026-08-18T01:02:03Z",
    )


def test_upsert_replaces_the_existing_fingerprint(tmp_path: Path) -> None:
    factory = _database(tmp_path)
    first = PendingAnalysisCache("Game.exe", 10, 20, "ranker-1", "engine-1")
    second = PendingAnalysisCache("bin/Game.exe", 30, 40, "ranker-2", "engine-2")
    with factory.connect() as connection:
        upsert_analysis_cache(connection, "game-1", first, "first")
        upsert_analysis_cache(connection, "game-1", second, "second")

    entry = AnalysisCacheRepository(factory).get("game-1")

    assert entry is not None
    assert entry.executable_relpath == "bin/Game.exe"
    assert entry.file_size == 30
    assert entry.modified_time_ns == 40
    assert entry.ranker_rules_version == "ranker-2"
    assert entry.engine_rules_version == "engine-2"
    assert entry.analyzed_at == "second"


def test_cache_write_helpers_leave_transaction_control_to_the_caller(
    tmp_path: Path,
) -> None:
    factory = _database(tmp_path)
    pending = PendingAnalysisCache("Game.exe", 10, 20, "ranker-1", "engine-1")
    with factory.connect() as connection:
        upsert_analysis_cache(connection, "game-1", pending, "now")
        connection.rollback()

    assert AnalysisCacheRepository(factory).get("game-1") is None


def test_delete_analysis_cache_is_idempotent(tmp_path: Path) -> None:
    factory = _database(tmp_path)
    pending = PendingAnalysisCache("Game.exe", 10, 20, "ranker-1", "engine-1")
    with factory.connect() as connection:
        upsert_analysis_cache(connection, "game-1", pending, "now")
        delete_analysis_cache(connection, "game-1")
        delete_analysis_cache(connection, "game-1")

    assert AnalysisCacheRepository(factory).get("game-1") is None
