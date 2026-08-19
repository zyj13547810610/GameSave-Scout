from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from gameshelf.db.connection import ConnectionFactory
from gameshelf.db.migrator import Migrator
from gameshelf.db.writer import DbWriter
from gameshelf.saves.batch_models import MatchedBatchCandidate
from gameshelf.saves.batch_repository import BatchSaveRepository
from gameshelf.saves.batch_review import (
    BatchReviewError,
    BatchSaveReviewService,
    SaveOnlyDraft,
)
from gameshelf.saves.batch_scanner import BatchScopeResult
from gameshelf.scanning.path_keys import windows_path_key


@dataclass(frozen=True)
class _Request:
    standard_scope_ids: tuple[str, ...] = ("documents",)
    custom_root_ids: tuple[str, ...] = ()


class _Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 19, tzinfo=UTC)

    def __call__(self) -> str:
        result = self.value.isoformat()
        self.value += timedelta(seconds=1)
        return result


def test_reassociate_and_accept_multiple_candidates_in_one_transaction(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    try:
        candidate_ids = _record_candidates(
            harness.repository,
            (_candidate("One"), _candidate("Two", kind="file")),
        )

        assert harness.review.reassociate_many(candidate_ids, "game-1") == 2
        result = harness.review.accept(candidate_ids, confirm_registry=False)

        assert result.recorded_count == 2
        assert result.unchanged_count == 0
        assert len(result.locations) == 2
        assert {location.game_id for location in result.locations} == {"game-1"}
        assert _candidate_statuses(harness.factory, candidate_ids) == (
            "recorded",
            "recorded",
        )
    finally:
        harness.close()


def test_accept_is_atomic_and_requires_registry_confirmation(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    try:
        directory_id, registry_id = _record_candidates(
            harness.repository,
            (_candidate("Directory"), _candidate("Registry", kind="registry")),
        )
        harness.review.reassociate_many((directory_id, registry_id), "game-1")

        with pytest.raises(BatchReviewError, match="注册表"):
            harness.review.accept(
                (directory_id, registry_id),
                confirm_registry=False,
            )

        assert _table_count(harness.factory, "save_locations") == 0
        assert _candidate_statuses(harness.factory, (directory_id, registry_id)) == (
            "pending",
            "pending",
        )
        with pytest.raises(BatchReviewError, match="不存在"):
            harness.review.accept(
                (directory_id, "missing-candidate"),
                confirm_registry=True,
            )
        assert _table_count(harness.factory, "save_locations") == 0
    finally:
        harness.close()


def test_accept_reports_existing_location_as_unchanged(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    try:
        candidate = _candidate("Existing")
        candidate_id = _record_candidates(harness.repository, (candidate,))[0]
        harness.review.reassociate_many((candidate_id,), "game-1")
        with harness.factory.connect() as connection:
            connection.execute(
                """
                INSERT INTO save_locations(
                    id, game_id, kind, path_template, display_path, path_key,
                    source, confidence, evidence_json, confirmed, enabled
                ) VALUES (
                    'location-existing', 'game-1', 'directory', ?, ?, ?,
                    'manual', 1, '[]', 1, 1
                )
                """,
                (candidate.path_template, candidate.display_path, candidate.path_key),
            )
            connection.commit()

        result = harness.review.accept((candidate_id,), confirm_registry=False)

        assert result.recorded_count == 0
        assert result.unchanged_count == 1
        assert result.locations[0].id == "location-existing"
    finally:
        harness.close()


def test_ignore_restore_and_reassociate_preserve_transaction_boundaries(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    try:
        first, second = _record_candidates(
            harness.repository,
            (_candidate("First"), _candidate("Second")),
        )
        assert harness.review.ignore((first, second)) == 2
        assert _candidate_statuses(harness.factory, (first, second)) == (
            "ignored",
            "ignored",
        )
        assert harness.review.restore((first,)) == 1
        assert harness.review.reassociate_many((first, second), "game-1") == 2
        rows = _candidate_rows(harness.factory, (first, second))
        assert {row["review_game_id"] for row in rows} == {"game-1"}
        assert {row["review_status"] for row in rows} == {"pending"}
    finally:
        harness.close()


def test_create_save_only_creates_game_locations_and_groups_atomically(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    try:
        candidate_ids = _record_candidates(
            harness.repository,
            (_candidate("ArchiveOne"), _candidate("ArchiveTwo", kind="file")),
        )

        game = harness.review.create_save_only(
            SaveOnlyDraft(
                title="  Archived Game  ",
                version=" v1.2 ",
                engine_id="unity",
                group_ids=("group-1",),
                candidate_ids=candidate_ids,
                confirm_registry=False,
            )
        )

        assert game.title == "Archived Game"
        assert game.version == "v1.2"
        assert game.status == "save_only"
        assert game.engine_id == "unity"
        assert game.group_ids == ("group-1",)
        assert _table_count(harness.factory, "save_locations") == 2
        assert _candidate_statuses(harness.factory, candidate_ids) == (
            "save_only",
            "save_only",
        )

        more_ids = _record_candidates(
            harness.repository,
            (_candidate("InvalidGroup"),),
        )
        before_games = _table_count(harness.factory, "games")
        before_locations = _table_count(harness.factory, "save_locations")
        with pytest.raises(BatchReviewError, match="分组"):
            harness.review.create_save_only(
                SaveOnlyDraft(
                    "No Partial Game",
                    None,
                    None,
                    ("missing-group",),
                    more_ids,
                    False,
                )
            )
        assert _table_count(harness.factory, "games") == before_games
        assert _table_count(harness.factory, "save_locations") == before_locations
        assert _candidate_statuses(harness.factory, more_ids) == ("pending",)
    finally:
        harness.close()


def test_clear_unavailable_does_not_delete_disk_or_confirmed_locations(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    protected_file = tmp_path / "real-save.sav"
    protected_file.write_bytes(b"keep")
    try:
        unlinked_id, linked_id = _record_candidates(
            harness.repository,
            (_candidate("Gone"), _candidate("Accepted")),
        )
        harness.review.reassociate_many((linked_id,), "game-1")
        harness.review.accept((linked_id,), confirm_registry=False)
        with harness.factory.connect() as connection:
            connection.execute(
                """
                UPDATE save_scan_candidates
                SET availability = 'unavailable'
                WHERE id IN (?, ?)
                """,
                (unlinked_id, linked_id),
            )
            connection.commit()

        with pytest.raises(BatchReviewError, match="正式存档位置"):
            harness.review.clear_unavailable((linked_id,))
        assert _table_count(harness.factory, "save_locations") == 1
        assert harness.review.clear_unavailable((unlinked_id,)) == 1

        assert protected_file.read_bytes() == b"keep"
        assert _table_count(harness.factory, "save_locations") == 1
    finally:
        harness.close()


@dataclass
class _Harness:
    factory: ConnectionFactory
    writer: DbWriter
    repository: BatchSaveRepository
    review: BatchSaveReviewService

    def close(self) -> None:
        self.writer.close()


def _harness(tmp_path: Path) -> _Harness:
    factory = ConnectionFactory(tmp_path / "data" / "library.db")
    Migrator(factory, tmp_path / "backups").migrate()
    with factory.connect() as connection:
        connection.execute(
            """
            INSERT INTO games(id, title, status, added_at, updated_at)
            VALUES ('game-1', 'Existing Game', 'missing', 'now', 'now')
            """
        )
        connection.execute(
            """
            INSERT INTO game_groups(id, name, normalized_name, created_at, updated_at)
            VALUES ('group-1', 'RPG', 'rpg', 'now', 'now')
            """
        )
        connection.commit()
    writer = DbWriter(factory)
    writer.start()
    repository = BatchSaveRepository(factory, writer, utc_now=_Clock())
    review = BatchSaveReviewService(
        factory,
        writer,
        repository,
        engine_ids=("unity", "renpy"),
        utc_now=_Clock(),
    )
    return _Harness(factory, writer, repository, review)


def _record_candidates(
    repository: BatchSaveRepository,
    candidates: tuple[MatchedBatchCandidate, ...],
) -> tuple[str, ...]:
    session = repository.start_session(_Request(), "rules")
    ids = repository.record_candidates(
        session,
        (
            BatchScopeResult(
                "documents",
                "completed",
                10,
                len(candidates),
                False,
                None,
            ),
        ),
        candidates,
    )
    repository.finish_session(session, status="completed")
    return ids


def _candidate(name: str, *, kind: str = "directory") -> MatchedBatchCandidate:
    if kind == "registry":
        display_path = rf"HKEY_CURRENT_USER\Software\Studio\{name}"
        path_template = display_path
    else:
        suffix = f"{name}.sav" if kind == "file" else f"{name}\\SaveData"
        display_path = rf"D:\Documents\{suffix}"
        path_template = rf"<winDocuments>\{suffix}"
    return MatchedBatchCandidate(
        scope_key="documents",
        kind=kind,  # type: ignore[arg-type]
        path_template=path_template,
        display_path=display_path,
        path_key=windows_path_key(display_path),
        sources=("bounded_scan",),
        evidence=(f"发现 {name}",),
        representative_files=(),
        matched_file_count=1,
        representatives_truncated=False,
        classification="unknown",
        confidence="low",
        suggested_game_id=None,
        suggested_title=None,
        external_product_id=None,
        engine_id=None,
        strong_group_key=None,
        alternatives=(),
    )


def _candidate_rows(
    factory: ConnectionFactory,
    candidate_ids: tuple[str, ...],
) -> tuple[object, ...]:
    placeholders = ",".join("?" for _ in candidate_ids)
    with factory.connect(readonly=True) as connection:
        rows = connection.execute(
            f"SELECT * FROM save_scan_candidates WHERE id IN ({placeholders}) ORDER BY id",
            candidate_ids,
        ).fetchall()
    return tuple(rows)


def _candidate_statuses(
    factory: ConnectionFactory,
    candidate_ids: tuple[str, ...],
) -> tuple[str, ...]:
    rows_by_id = {str(row["id"]): row for row in _candidate_rows(factory, candidate_ids)}
    return tuple(str(rows_by_id[candidate_id]["review_status"]) for candidate_id in candidate_ids)


def _table_count(factory: ConnectionFactory, table: str) -> int:
    assert table in {"games", "save_locations"}
    with factory.connect(readonly=True) as connection:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
