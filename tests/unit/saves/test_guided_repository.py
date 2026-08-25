from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import FrozenInstanceError, dataclass
from pathlib import Path

import pytest

from gamesave_scout.db.connection import ConnectionFactory
from gamesave_scout.db.migrator import Migrator
from gamesave_scout.db.writer import DbWriter
from gamesave_scout.saves.guided_models import GuidedDiscoveryDraft, GuidedScopeOption
from gamesave_scout.saves.guided_repository import (
    ActiveGuidedSessionError,
    GuidedSaveRepository,
    InvalidGuidedSessionState,
)


@dataclass(frozen=True)
class GuidedRepositoryHarness:
    factory: ConnectionFactory
    repository: GuidedSaveRepository


@pytest.fixture
def guided_repository(tmp_path: Path) -> Iterator[GuidedRepositoryHarness]:
    factory = ConnectionFactory(tmp_path / "data" / "library.db")
    Migrator(factory, tmp_path / "backups").migrate()
    with factory.connect() as connection:
        _insert_game(connection, "game-1", "Alice")
        _insert_game(connection, "game-2", "Bob")
        connection.commit()
    writer = DbWriter(factory)
    writer.start()
    try:
        yield GuidedRepositoryHarness(factory, GuidedSaveRepository(factory, writer))
    finally:
        writer.close()


def test_repository_round_trips_session_transitions_and_immutable_json(
    guided_repository: GuidedRepositoryHarness,
) -> None:
    repository = guided_repository.repository
    scope = _scope("default:game", r"C:\Games\Alice", r"<game>")

    created = repository.create_session(
        "session-1",
        "game-1",
        "2026-08-15T00:00:00+00:00",
        (scope,),
        ("Saved Games 不可用",),
    )
    monitoring = repository.set_monitoring(
        created.id,
        "2026-08-15T00:00:01+00:00",
        root_pid=123,
    )
    monitoring = repository.set_process_tracking_degraded(created.id)
    settling = repository.mark_settling(
        created.id, "2026-08-15T00:01:00+00:00"
    )

    assert created.status == "preparing"
    assert created.approved_scopes == (scope,)
    assert created.unavailable_scopes == ("Saved Games 不可用",)
    assert monitoring.status == "monitoring"
    assert monitoring.root_pid == 123
    assert monitoring.process_tracking_degraded is True
    assert settling.status == "settling"
    assert settling.save_marked_at == "2026-08-15T00:01:00+00:00"
    with pytest.raises(FrozenInstanceError):
        settling.status = "completed"  # type: ignore[misc]


def test_repository_rejects_a_second_active_session(
    guided_repository: GuidedRepositoryHarness,
) -> None:
    repository = guided_repository.repository
    repository.create_session(
        "session-1", "game-1", "2026-08-15T00:00:00+00:00", ()
    )

    with pytest.raises(ActiveGuidedSessionError):
        repository.create_session(
            "session-2", "game-2", "2026-08-15T00:00:01+00:00", ()
        )

    assert repository.active() is not None
    assert repository.active().id == "session-1"  # type: ignore[union-attr]


def test_complete_atomically_persists_candidates_and_releases_active_slot(
    guided_repository: GuidedRepositoryHarness,
) -> None:
    repository = guided_repository.repository
    repository.create_session(
        "session-1", "game-1", "2026-08-15T00:00:00+00:00", ()
    )
    repository.set_monitoring(
        "session-1", "2026-08-15T00:00:01+00:00", root_pid=456
    )

    completed = repository.complete(
        "session-1",
        "2026-08-15T00:02:00+00:00",
        (_draft(r"<localAppDataLow>\Studio\Alice", 0.91),),
        overflowed_scopes=("default:local",),
        truncated_scopes=("default:local",),
        result_summary={"candidateCount": 1, "filteredCount": 4},
    )
    discoveries = repository.list_discoveries("session-1")

    assert completed.status == "completed"
    assert completed.overflowed_scopes == ("default:local",)
    assert completed.truncated_scopes == ("default:local",)
    assert completed.result_summary == {"candidateCount": 1, "filteredCount": 4}
    assert repository.active() is None
    assert repository.latest_reviewable() == completed
    assert repository.latest_reviewable("game-1") == completed
    assert repository.latest_reviewable("game-2") is None
    assert len(discoveries) == 1
    assert discoveries[0].candidate_template == r"<localAppDataLow>\Studio\Alice"
    assert discoveries[0].preselected is True
    with guided_repository.factory.connect(readonly=True) as connection:
        active_slot = connection.execute(
            "SELECT active_slot FROM save_detection_sessions WHERE id = 'session-1'"
        ).fetchone()[0]
    assert active_slot is None


def test_complete_rolls_back_all_candidates_when_one_is_invalid(
    guided_repository: GuidedRepositoryHarness,
) -> None:
    repository = guided_repository.repository
    repository.create_session(
        "session-1", "game-1", "2026-08-15T00:00:00+00:00", ()
    )
    repository.set_monitoring(
        "session-1", "2026-08-15T00:00:01+00:00", root_pid=456
    )
    duplicate = _draft(r"<home>\Saves", 0.9)

    with pytest.raises(sqlite3.IntegrityError):
        repository.complete(
            "session-1",
            "2026-08-15T00:02:00+00:00",
            (duplicate, duplicate),
        )

    assert repository.get_session("session-1").status == "monitoring"  # type: ignore[union-attr]
    assert repository.list_discoveries("session-1") == ()


def test_discard_hides_completed_session_from_reviewable_queries(
    guided_repository: GuidedRepositoryHarness,
) -> None:
    repository = guided_repository.repository
    repository.create_session(
        "session-1", "game-1", "2026-08-15T00:00:00+00:00", ()
    )
    repository.set_monitoring(
        "session-1", "2026-08-15T00:00:01+00:00", root_pid=1
    )
    repository.complete(
        "session-1",
        "2026-08-15T00:02:00+00:00",
        (_draft(r"<home>\Saves", 0.8),),
    )

    discarded = repository.discard("session-1")

    assert discarded == 1
    assert repository.latest_reviewable() is None
    assert repository.list_discoveries("session-1")[0].review_status == "ignored"


def test_recover_interrupted_releases_all_residual_active_sessions(
    guided_repository: GuidedRepositoryHarness,
) -> None:
    repository = guided_repository.repository
    repository.create_session(
        "session-1", "game-1", "2026-08-15T00:00:00+00:00", ()
    )

    recovered = repository.recover_interrupted("2026-08-15T00:03:00+00:00")

    session = repository.get_session("session-1")
    assert recovered == 1
    assert session is not None
    assert session.status == "interrupted"
    assert session.finished_at == "2026-08-15T00:03:00+00:00"
    assert repository.active() is None


def test_repository_rejects_invalid_state_transition(
    guided_repository: GuidedRepositoryHarness,
) -> None:
    repository = guided_repository.repository
    repository.create_session(
        "session-1", "game-1", "2026-08-15T00:00:00+00:00", ()
    )

    with pytest.raises(InvalidGuidedSessionState):
        repository.mark_settling("session-1", "2026-08-15T00:01:00+00:00")


def _insert_game(connection: sqlite3.Connection, game_id: str, title: str) -> None:
    connection.execute(
        """
        INSERT INTO games(id, title, status, added_at, updated_at)
        VALUES (?, ?, 'save_only', '2026-08-15T00:00:00+00:00',
                '2026-08-15T00:00:00+00:00')
        """,
        (game_id, title),
    )


def _scope(scope_id: str, display_path: str, path_template: str) -> GuidedScopeOption:
    return GuidedScopeOption(
        id=scope_id,
        label="游戏目录",
        display_path=display_path,
        path_template=path_template,
        source="game",
        default_selected=True,
        available=True,
    )


def _draft(path_template: str, confidence: float) -> GuidedDiscoveryDraft:
    display_path = path_template.replace("<home>", r"C:\Users\Alice").replace(
        "<localAppDataLow>", r"C:\Users\Alice\AppData\LocalLow"
    )
    return GuidedDiscoveryDraft(
        candidate_template=path_template,
        display_path=display_path,
        path_key=display_path.casefold(),
        kind="directory",
        confidence=confidence,
        evidence=("保存标记前后发生协调变化",),
        representative_files=(str(Path(display_path) / "slot1.sav"),),
        first_changed_at="2026-08-15T00:00:59+00:00",
        last_changed_at="2026-08-15T00:01:01+00:00",
        mark_offset_ms=1000,
        affected_by_overflow=False,
        affected_by_truncation=False,
        preselected=confidence >= 0.85,
    )
