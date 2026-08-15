from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from gameshelf.db.connection import ConnectionFactory
from gameshelf.db.migrator import Migrator
from gameshelf.db.writer import DbWriter
from gameshelf.library.repository import LibraryRepository
from gameshelf.library.service import LibraryService
from gameshelf.platform.windows.known_folders import KnownFolders
from gameshelf.saves.guided_models import GuidedDiscoveryDraft
from gameshelf.saves.guided_repository import GuidedSaveRepository
from gameshelf.saves.guided_review import GuidedReviewError, GuidedSaveReviewService
from gameshelf.saves.repository import SaveLocationRepository
from gameshelf.saves.service import SaveLocationService
from gameshelf.saves.templates import PathTemplateResolver


class _UnusedShell:
    def open_directory(self, _path: Path) -> None:
        raise AssertionError("审核候选时不应打开目录")

    def reveal_file(self, _path: Path) -> None:
        raise AssertionError("审核候选时不应定位文件")


class _Registry:
    def key_exists(self, _key: str) -> bool:
        return True

    def open_key(self, _key: str) -> None:
        raise AssertionError("审核候选时不应打开注册表")


@dataclass(frozen=True)
class ReviewHarness:
    factory: ConnectionFactory
    repository: GuidedSaveRepository
    review: GuidedSaveReviewService


@pytest.fixture
def review_harness(tmp_path: Path) -> Iterator[ReviewHarness]:
    factory = ConnectionFactory(tmp_path / "data" / "library.db")
    Migrator(factory, tmp_path / "backups").migrate()
    with factory.connect() as connection:
        _insert_game(connection, "game-1", "Alice")
        _insert_game(connection, "game-2", "Bob")
        connection.commit()
    writer = DbWriter(factory)
    writer.start()
    library = LibraryService(LibraryRepository(factory), writer)
    repository = GuidedSaveRepository(factory, writer)
    folders = _known_folders(tmp_path)
    save_locations = SaveLocationService(
        SaveLocationRepository(factory),
        writer,
        PathTemplateResolver(folders),
        library,
        _UnusedShell(),
        _Registry(),
    )
    review = GuidedSaveReviewService(factory, writer, repository, save_locations)
    try:
        yield ReviewHarness(factory, repository, review)
    finally:
        writer.close()


def test_accept_rolls_back_every_location_when_one_discovery_belongs_to_another_session(
    review_harness: ReviewHarness,
) -> None:
    first = _completed_discovery(
        review_harness.repository,
        "session-1",
        "game-1",
        _directory_draft(r"<home>\Alice"),
    )
    other = _completed_discovery(
        review_harness.repository,
        "session-2",
        "game-2",
        _directory_draft(r"<home>\Bob"),
    )

    with pytest.raises(GuidedReviewError) as raised:
        review_harness.review.accept("session-1", (first, other), False)

    assert raised.value.code == "guided_discovery_invalid"
    with review_harness.factory.connect(readonly=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM save_locations").fetchone()[0] == 0
        assert connection.execute(
            "SELECT review_status FROM save_discoveries WHERE id = ?", (first,)
        ).fetchone()[0] == "unreviewed"


def test_repeating_a_legal_accept_is_idempotent(review_harness: ReviewHarness) -> None:
    discovery_id = _completed_discovery(
        review_harness.repository,
        "session-1",
        "game-1",
        _directory_draft(r"<home>\Alice"),
    )

    first = review_harness.review.accept("session-1", (discovery_id,), False)
    second = review_harness.review.accept("session-1", (discovery_id,), False)

    assert len(first) == 1
    assert second[0].id == first[0].id
    with review_harness.factory.connect(readonly=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM save_locations").fetchone()[0] == 1
        row = connection.execute(
            "SELECT review_status, save_location_id FROM save_discoveries WHERE id = ?",
            (discovery_id,),
        ).fetchone()
    assert tuple(row) == ("accepted", first[0].id)


def test_registry_discovery_requires_explicit_confirmation(
    review_harness: ReviewHarness,
) -> None:
    discovery_id = _completed_discovery(
        review_harness.repository,
        "session-1",
        "game-1",
        _registry_draft(r"HKEY_CURRENT_USER\Software\Studio\Alice"),
    )

    with pytest.raises(GuidedReviewError) as raised:
        review_harness.review.accept("session-1", (discovery_id,), False)

    assert raised.value.code == "registry_confirmation_required"
    assert review_harness.review.accept("session-1", (discovery_id,), True)[0].kind == "registry"


def _completed_discovery(
    repository: GuidedSaveRepository,
    session_id: str,
    game_id: str,
    draft: GuidedDiscoveryDraft,
) -> str:
    repository.create_session(
        session_id, game_id, "2026-08-15T00:00:00+00:00", ()
    )
    repository.set_monitoring(
        session_id, "2026-08-15T00:00:01+00:00", root_pid=123
    )
    repository.complete(
        session_id, "2026-08-15T00:01:00+00:00", (draft,)
    )
    return repository.list_discoveries(session_id)[0].id


def _directory_draft(template: str) -> GuidedDiscoveryDraft:
    return GuidedDiscoveryDraft(
        candidate_template=template,
        display_path=template.replace("<home>", r"C:\Users\Alice"),
        path_key=template.casefold(),
        kind="directory",
        confidence=0.91,
        evidence=("保存标记前后发生协调变化",),
        representative_files=("slot1.sav",),
        first_changed_at="2026-08-15T00:00:10+00:00",
        last_changed_at="2026-08-15T00:00:20+00:00",
        mark_offset_ms=500,
        affected_by_overflow=False,
        affected_by_truncation=False,
        preselected=True,
    )


def _registry_draft(key: str) -> GuidedDiscoveryDraft:
    return GuidedDiscoveryDraft(
        candidate_template=key,
        display_path=key,
        path_key=key.casefold(),
        kind="registry",
        confidence=0.8,
        evidence=("定向注册表键的元数据发生变化",),
        representative_files=(),
        first_changed_at=None,
        last_changed_at=None,
        mark_offset_ms=None,
        affected_by_overflow=False,
        affected_by_truncation=False,
        preselected=False,
    )


def _insert_game(connection: sqlite3.Connection, game_id: str, title: str) -> None:
    connection.execute(
        """
        INSERT INTO games(id, title, status, added_at, updated_at)
        VALUES (?, ?, 'save_only', '2026-08-15T00:00:00+00:00',
                '2026-08-15T00:00:00+00:00')
        """,
        (game_id, title),
    )


def _known_folders(tmp_path: Path) -> KnownFolders:
    home = tmp_path / "Profile"
    return KnownFolders(
        home=home,
        app_data=home / "AppData" / "Roaming",
        local_app_data=home / "AppData" / "Local",
        local_app_data_low=home / "AppData" / "LocalLow",
        documents=home / "Documents",
        saved_games=home / "Saved Games",
        program_data=tmp_path / "ProgramData",
        public=tmp_path / "Public",
        windows=tmp_path / "Windows",
    )
