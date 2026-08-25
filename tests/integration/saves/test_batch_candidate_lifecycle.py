from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from gamesave_scout.db.connection import ConnectionFactory
from gamesave_scout.db.migrator import Migrator
from gamesave_scout.db.writer import DbWriter
from gamesave_scout.saves.batch_models import MatchedBatchCandidate, RepresentativeFile
from gamesave_scout.saves.batch_repository import (
    BatchCandidateQuery,
    BatchSaveRepository,
)
from gamesave_scout.saves.batch_scanner import BatchScopeResult
from gamesave_scout.scanning.path_keys import windows_path_key


@dataclass(frozen=True)
class _Request:
    standard_scope_ids: tuple[str, ...] = ("documents",)
    custom_root_ids: tuple[str, ...] = ()


class _Clock:
    def __init__(self) -> None:
        self._value = datetime(2026, 8, 19, tzinfo=UTC)

    def __call__(self) -> str:
        value = self._value
        self._value += timedelta(seconds=1)
        return value.isoformat()


def test_candidates_keep_identity_and_user_decisions_across_scans(
    tmp_path: Path,
) -> None:
    factory, writer, repository = _repository(tmp_path)
    _insert_games(factory)
    complete = (_scope("completed"),)
    try:
        first_session = repository.start_session(_Request(), "rules-1")
        first_ids = repository.record_candidates(
            first_session,
            complete,
            (
                _candidate("Alice", "high", "game-alice", ("ludusavi",)),
                _candidate("Old", "low", None, ("bounded_scan",)),
            ),
        )
        repository.finish_session(first_session, status="completed")
        first_page = repository.list_candidates(BatchCandidateQuery())
        first_by_title = {item.suggested_title: item for item in first_page.items}
        old_id = first_by_title[None].id
        old_first_seen = first_by_title[None].first_seen_at

        with factory.connect() as connection:
            connection.execute(
                "UPDATE save_scan_candidates SET review_status = 'ignored' WHERE id = ?",
                (old_id,),
            )
            connection.commit()

        second_session = repository.start_session(_Request(), "rules-2")
        second_ids = repository.record_candidates(
            second_session,
            complete,
            (
                _candidate("Alice", "high", "game-alice", ("bounded_scan",)),
                _candidate("New", "low", None, ("bounded_scan",)),
            ),
        )
        repository.finish_session(second_session, status="completed")

        assert second_ids[0] == first_ids[0]
        old = repository.get_candidate(old_id)
        assert old is not None
        assert old.availability == "unavailable"
        assert old.review_status == "ignored"
        assert old.first_seen_at == old_first_seen
        alice = repository.get_candidate(first_ids[0])
        assert alice is not None
        assert alice.first_seen_at != alice.last_seen_at
        assert alice.sources == ("bounded_scan",)
        assert repository.list_candidates(BatchCandidateQuery(source="ludusavi")).total == 0
        assert _observation_count(factory, first_ids[0]) == 2

        third_session = repository.start_session(_Request(), "rules-3")
        repository.record_candidates(
            third_session,
            complete,
            (_candidate("Old", "low", None, ("bounded_scan",)),),
        )
        repository.finish_session(third_session, status="completed")
        old = repository.get_candidate(old_id)
        assert old is not None
        assert old.availability == "available"
        assert old.review_status == "ignored"
    finally:
        writer.close()


def test_incomplete_scopes_do_not_mark_previous_candidates_unavailable(
    tmp_path: Path,
) -> None:
    factory, writer, repository = _repository(tmp_path)
    try:
        first = repository.start_session(_Request(), "rules")
        candidate_id = repository.record_candidates(
            first,
            (_scope("completed"),),
            (_candidate("Old", "low", None, ("bounded_scan",)),),
        )[0]
        repository.finish_session(first, status="completed")

        for status in ("unavailable", "truncated", "cancelled"):
            session = repository.start_session(_Request(), "rules")
            repository.record_candidates(session, (_scope(status),), ())
            repository.finish_session(
                session,
                status="cancelled" if status == "cancelled" else "completed",
            )
            persisted = repository.get_candidate(candidate_id)
            assert persisted is not None
            assert persisted.availability == "available"
    finally:
        writer.close()


def test_new_observations_preserve_all_user_review_outcomes(tmp_path: Path) -> None:
    factory, writer, repository = _repository(tmp_path)
    try:
        first = repository.start_session(_Request(), "rules")
        ids = repository.record_candidates(
            first,
            (_scope("completed"),),
            tuple(
                _candidate(name, "low", None, ("bounded_scan",))
                for name in ("Ignored", "Recorded", "Archive")
            ),
        )
        repository.finish_session(first, status="completed")
        with factory.connect() as connection:
            connection.executemany(
                "UPDATE save_scan_candidates SET review_status = ? WHERE id = ?",
                tuple(zip(("ignored", "recorded", "save_only"), ids, strict=True)),
            )
            connection.commit()

        second = repository.start_session(_Request(), "rules")
        repository.record_candidates(
            second,
            (_scope("completed"),),
            tuple(
                _candidate(name, "high", None, ("ludusavi",))
                for name in ("Ignored", "Recorded", "Archive")
            ),
        )
        repository.finish_session(second, status="completed")

        assert tuple(repository.get_candidate(item).review_status for item in ids) == (
            "ignored",
            "recorded",
            "save_only",
        )
    finally:
        writer.close()


def test_queries_use_latest_observation_and_select_only_safe_candidates(
    tmp_path: Path,
) -> None:
    factory, writer, repository = _repository(tmp_path)
    _insert_games(factory)
    try:
        session = repository.start_session(_Request(), "rules")
        high_id, medium_id, unknown_id = repository.record_candidates(
            session,
            (_scope("completed"),),
            (
                _candidate("Alice", "high", "game-alice", ("ludusavi",)),
                _candidate("Manual", "medium", None, ("user",)),
                _candidate("Unknown", "low", None, ("bounded_scan",)),
            ),
        )
        repository.finish_session(session, status="completed")
        with factory.connect() as connection:
            connection.execute(
                "UPDATE save_scan_candidates SET review_game_id = ? WHERE id = ?",
                ("game-missing", medium_id),
            )
            connection.commit()

        assert repository.selectable_ids(BatchCandidateQuery()) == (
            high_id,
            medium_id,
        )
        assert unknown_id not in repository.selectable_ids(BatchCandidateQuery())
        assert repository.list_candidates(BatchCandidateQuery(status="installed")).total == 1
        assert (
            repository.list_candidates(
                BatchCandidateQuery(keyword="manual", confidence="medium", source="user")
            ).total
            == 1
        )
    finally:
        writer.close()


def test_recover_interrupted_only_changes_running_sessions(tmp_path: Path) -> None:
    factory, writer, repository = _repository(tmp_path)
    try:
        running = repository.start_session(_Request(), "rules")
        complete = repository.start_session(_Request(), "rules")
        repository.finish_session(complete, status="completed")

        assert repository.recover_interrupted() == 1
        with factory.connect(readonly=True) as connection:
            states = {
                row["id"]: row["status"]
                for row in connection.execute(
                    "SELECT id, status FROM scan_sessions WHERE kind = 'save_discovery'"
                )
            }
        assert states[running] == "interrupted"
        assert states[complete] == "completed"
    finally:
        writer.close()


def test_clear_unavailable_removes_only_candidate_observation_history(
    tmp_path: Path,
) -> None:
    factory, writer, repository = _repository(tmp_path)
    try:
        first = repository.start_session(_Request(), "rules")
        candidate_id = repository.record_candidates(
            first,
            (_scope("completed"),),
            (_candidate("Gone", "low", None, ("bounded_scan",)),),
        )[0]
        repository.finish_session(first, status="completed")
        second = repository.start_session(_Request(), "rules")
        repository.record_candidates(second, (_scope("completed"),), ())
        repository.finish_session(second, status="completed")
        assert repository.get_candidate(candidate_id).availability == "unavailable"

        assert repository.clear_unavailable((candidate_id,)) == 1

        assert repository.get_candidate(candidate_id) is None
        assert _observation_count(factory, candidate_id) == 0
        with factory.connect(readonly=True) as connection:
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM scan_sessions WHERE kind = 'save_discovery'"
                ).fetchone()[0]
                == 2
            )
    finally:
        writer.close()


def _repository(
    tmp_path: Path,
) -> tuple[ConnectionFactory, DbWriter, BatchSaveRepository]:
    factory = ConnectionFactory(tmp_path / "data" / "library.db")
    Migrator(factory, tmp_path / "backups").migrate()
    writer = DbWriter(factory)
    writer.start()
    return factory, writer, BatchSaveRepository(factory, writer, utc_now=_Clock())


def _insert_games(factory: ConnectionFactory) -> None:
    with factory.connect() as connection:
        connection.execute(
            """
            INSERT INTO scan_roots(
                id, display_path, path_key, scan_mode, max_depth, created_at
            ) VALUES ('root', 'D:\\Games', 'd:\\games', 'children', 1, 'now')
            """
        )
        connection.executemany(
            """
            INSERT INTO games(
                id, scan_root_id, relative_dir, install_path_key,
                title, status, added_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'now', 'now')
            """,
            (
                (
                    "game-alice",
                    "root",
                    "Alice",
                    "d:\\games\\alice",
                    "Alice",
                    "installed",
                ),
                ("game-missing", None, None, None, "Missing", "missing"),
            ),
        )
        connection.commit()


def _scope(status: str) -> BatchScopeResult:
    return BatchScopeResult(
        scope_key="documents",
        status=status,  # type: ignore[arg-type]
        entries=10,
        candidate_count=1,
        truncated=status == "truncated",
        error=None,
    )


def _candidate(
    name: str,
    confidence: str,
    game_id: str | None,
    sources: tuple[str, ...],
) -> MatchedBatchCandidate:
    display_path = rf"D:\Documents\{name}\SaveData"
    return MatchedBatchCandidate(
        scope_key="documents",
        kind="directory",
        path_template=rf"<winDocuments>\{name}\SaveData",
        display_path=display_path,
        path_key=windows_path_key(display_path),
        sources=sources,  # type: ignore[arg-type]
        evidence=(f"发现 {name}",),
        representative_files=(RepresentativeFile("save01.sav", 10, 100),),
        matched_file_count=1,
        representatives_truncated=False,
        classification=("installed" if game_id == "game-alice" else "unknown"),
        confidence=confidence,  # type: ignore[arg-type]
        suggested_game_id=game_id,
        suggested_title=name if game_id is not None else None,
        external_product_id=None,
        engine_id=None,
        strong_group_key=f"game:{game_id}" if game_id else None,
        alternatives=(),
    )


def _observation_count(factory: ConnectionFactory, candidate_id: str) -> int:
    with factory.connect(readonly=True) as connection:
        return int(
            connection.execute(
                "SELECT COUNT(*) FROM save_scan_observations WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()[0]
        )
