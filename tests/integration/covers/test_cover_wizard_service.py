from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from threading import Event, Thread

import pytest
from PIL import Image

from gamesave_scout.bootstrap.paths import AppPaths
from gamesave_scout.bridge.tasks import TaskCancelled
from gamesave_scout.covers.candidate_images import stage_candidate_file
from gamesave_scout.covers.candidates import (
    CandidateFileRef,
    CoverCandidate,
    SharedCoverCandidate,
)
from gamesave_scout.covers.local_discovery import (
    DirectoryImportSummary,
    LocalDiscoverySummary,
)
from gamesave_scout.covers.service import CoverService
from gamesave_scout.covers.wizard_service import (
    ActiveCoverWizardError,
    CandidateSourceChangedError,
    CoverCandidateNotFoundError,
    CoverWizardBusyError,
    CoverWizardService,
)
from gamesave_scout.db.connection import ConnectionFactory
from gamesave_scout.db.migrator import Migrator
from gamesave_scout.db.writer import DbWriter
from gamesave_scout.library.repository import LibraryRepository
from gamesave_scout.library.service import LibraryService


class _Progress:
    def report(self, *args: object, **kwargs: object) -> None:
        del args, kwargs

    def raise_if_cancelled(self) -> None:
        return None


@dataclass
class _RecordingProgress:
    reports: list[tuple[int, int | None, str, object]] = field(default_factory=list)

    def report(
        self,
        completed: int,
        total: int | None,
        message: str,
        *,
        details: object = None,
    ) -> None:
        self.reports.append((completed, total, message, details))

    def raise_if_cancelled(self) -> None:
        return None


class _LocalDiscovery:
    def __init__(self) -> None:
        self.shallow: dict[str, LocalDiscoverySummary] = {}
        self.directory_summary = DirectoryImportSummary((), 0, 0, 0, False, ())
        self.directory_failure: Exception | None = None

    def scan_game_directory(self, game, install, root, limit, depth, context):
        del install, root, limit, depth, context
        return self.shallow.get(game.id, _summary())

    def import_cover_directory(
        self,
        directory,
        root,
        known_sha256s,
        capacity,
        context,
    ):
        del directory, root, known_sha256s, capacity, context
        if self.directory_failure is not None:
            raise self.directory_failure
        return self.directory_summary


class _Vndb:
    def __init__(self) -> None:
        self.candidates: dict[str, tuple[CoverCandidate, ...]] = {}
        self.failure: Exception | None = None
        self.queries: list[str] = []

    def search(self, title, limit, root, game_id, context):
        del limit, root
        self.queries.append(title)
        if self.failure is not None:
            raise self.failure
        context.report(
            1,
            5,
            "正在获取 VNDB 封面：内部候选",
            details={"gameId": game_id, "vndbId": "v-test"},
        )
        return self.candidates.get(game_id, ())


@dataclass
class _Harness:
    paths: AppPaths
    writer: DbWriter
    library: LibraryService
    covers: CoverService
    local: _LocalDiscovery
    vndb: _Vndb
    alice_id: str
    bob_id: str
    save_only_id: str

    def service(self) -> CoverWizardService:
        return CoverWizardService(
            self.paths, self.library, self.covers, self.local, self.vndb
        )


@pytest.fixture
def harness(tmp_path: Path) -> _Harness:
    paths = AppPaths.from_root(tmp_path / "portable")
    paths.ensure_writable()
    factory = ConnectionFactory(paths.database_file)
    Migrator(factory, paths.backups_dir).migrate()
    writer = DbWriter(factory)
    writer.start()
    repository = LibraryRepository(factory)
    library = LibraryService(repository, writer)
    games = tmp_path / "games"
    for name in ("Alice", "Bob", "Archive"):
        (games / name).mkdir(parents=True)
    root = library.add_root(str(games), "children", 1, [])
    alice = library.create_game_for_test(root.id, "Alice", "Alice")
    bob = library.create_game_for_test(root.id, "Bob", "Bob")
    archive = library.create_game_for_test(root.id, "Archive", "Archive")

    def mark_save_only(connection):
        connection.execute(
            "UPDATE games SET status = 'save_only' WHERE id = ?", (archive.id,)
        )

    writer.submit(mark_save_only).result()
    covers = CoverService(paths, repository, writer, lambda: True)
    covers.import_clipboard_png(bob.id, _png("blue"))
    result = _Harness(
        paths,
        writer,
        library,
        covers,
        _LocalDiscovery(),
        _Vndb(),
        alice.id,
        bob.id,
        archive.id,
    )
    try:
        yield result
    finally:
        writer.close()


def test_single_session_and_include_existing_queue(harness: _Harness) -> None:
    service = harness.service()

    snapshot = service.start()

    assert [item.game_id for item in snapshot.queue] == [
        harness.alice_id,
        harness.save_only_id,
    ]
    assert snapshot.current_game_id == harness.alice_id
    with pytest.raises(ActiveCoverWizardError):
        service.start()

    expanded = service.set_include_existing(snapshot.id, True)
    assert [item.game_id for item in expanded.queue] == [
        harness.alice_id,
        harness.save_only_id,
        harness.bob_id,
    ]
    assert expanded.queue[-1].initial_has_cover is True


def test_four_sources_merge_by_hash_without_crossing_games(harness: _Harness) -> None:
    service = harness.service()
    session = service.start()
    payload = _png("green")
    dropped = service.add_candidate_bytes(
        session.id,
        harness.alice_id,
        file_name="drop.png",
        payload=payload,
        source="drop",
    )
    other = service.add_candidate_bytes(
        session.id,
        harness.save_only_id,
        file_name="other.png",
        payload=payload,
        source="clipboard",
    )
    vndb_source = harness.paths.temp_dir / "fake-vndb.png"
    vndb_preview = harness.paths.temp_dir / "fake-vndb.webp"
    vndb_source.write_bytes(payload)
    vndb_preview.write_bytes(b"preview")
    harness.vndb.candidates[harness.alice_id] = (
        _candidate(
            "vndb",
            harness.alice_id,
            vndb_source,
            vndb_preview,
            dropped.sha256,
            "vndb",
            "VNDB",
        ),
    )

    service.collect_vndb(session.id, [harness.alice_id], 5, _Progress())

    alice = service.list_candidates(session.id, harness.alice_id, False)
    assert len(alice) == 1
    assert alice[0].source == "vndb"
    assert alice[0].evidence == ("VNDB", "拖放")
    assert service.list_candidates(session.id, harness.save_only_id, False) == (other,)
    with pytest.raises(ValueError):
        service.add_candidate_bytes(
            session.id,
            harness.alice_id,
            file_name="bad.png",
            payload=payload,
            source="vndb",  # type: ignore[arg-type]
        )


def test_shared_directory_candidates_keep_ids_and_sort_for_each_game(
    harness: _Harness,
    tmp_path: Path,
) -> None:
    service = harness.service()
    session = service.start()
    directory = tmp_path / "screenshots"
    directory.mkdir()
    alice_source = directory / "Alice cover.png"
    hash_source = directory / "86025945_p10.png"
    alice_source.write_bytes(_png("red"))
    hash_source.write_bytes(_png("purple"))
    preview_root = (
        harness.paths.temp_dir / "cover-wizard" / session.id / "shared-previews"
    )
    harness.local.directory_summary = _directory_summary(
        _shared_candidate("shared-alice", alice_source, preview_root / "alice.webp"),
        _shared_candidate("shared-hash", hash_source, preview_root / "hash.webp"),
    )

    service.collect_directory(session.id, directory, _Progress())

    alice = service.list_candidates(session.id, harness.alice_id, False)
    archive = service.list_candidates(session.id, harness.save_only_id, False)
    assert [item.id for item in alice] == ["shared-alice", "shared-hash"]
    assert {item.id for item in archive} == {"shared-alice", "shared-hash"}
    assert all(item.shared for item in alice)
    assert {item.preview_path for item in alice} == {
        item.preview_path for item in archive
    }
    snapshot = service.snapshot(session.id)
    visible = {
        item.game_id: (item.status, item.candidate_count)
        for item in snapshot.queue
    }
    assert visible[harness.alice_id] == ("ready", 2)
    assert visible[harness.save_only_id] == ("ready", 2)


def test_shared_candidate_hides_after_adoption_and_can_be_reused(
    harness: _Harness,
    tmp_path: Path,
) -> None:
    external = tmp_path / "screenshots" / "86025945_p10.png"
    external.parent.mkdir()
    external.write_bytes(_png("purple"))
    original_sha256 = hashlib.sha256(external.read_bytes()).hexdigest()
    service = harness.service()
    session = service.start(include_existing=True)
    preview = (
        harness.paths.temp_dir
        / "cover-wizard"
        / session.id
        / "shared-previews"
        / "shared-1.webp"
    )
    harness.local.directory_summary = _directory_summary(
        _shared_candidate("shared-1", external, preview)
    )
    service.collect_directory(session.id, external.parent, _Progress())

    service.adopt(session.id, harness.alice_id, "shared-1")
    assert service.list_candidates(session.id, harness.save_only_id, False) == ()
    visible = service.list_candidates(session.id, harness.save_only_id, True)
    assert visible[0].used_by[0].game_id == harness.alice_id

    service.adopt(session.id, harness.save_only_id, "shared-1")
    reused = service.list_candidates(session.id, harness.bob_id, True)[0]
    assert {item.game_id for item in reused.used_by} == {
        harness.alice_id,
        harness.save_only_id,
    }
    assert external.exists()
    assert hashlib.sha256(external.read_bytes()).hexdigest() == original_sha256
    assert preview.exists()

    service.close(session.id)
    assert not preview.parent.parent.exists()
    assert external.exists()
    assert hashlib.sha256(external.read_bytes()).hexdigest() == original_sha256


def test_dedicated_candidate_cannot_be_adopted_for_another_game(
    harness: _Harness,
) -> None:
    service = harness.service()
    session = service.start()
    candidate = service.add_candidate_bytes(
        session.id,
        harness.alice_id,
        file_name="candidate.png",
        payload=_png("red"),
        source="drop",
    )

    with pytest.raises(CoverCandidateNotFoundError):
        service.adopt(session.id, harness.save_only_id, candidate.id)

    assert service.list_candidates(session.id, harness.alice_id, False) == (
        candidate,
    )


def test_adopting_same_hash_dedicated_candidate_marks_shared_copy_used(
    harness: _Harness,
    tmp_path: Path,
) -> None:
    external = tmp_path / "screenshots" / "shared.png"
    external.parent.mkdir()
    payload = _png("green")
    external.write_bytes(payload)
    service = harness.service()
    session = service.start()
    preview = (
        harness.paths.temp_dir
        / "cover-wizard"
        / session.id
        / "shared-previews"
        / "shared.webp"
    )
    shared = _shared_candidate("shared-1", external, preview)
    harness.local.directory_summary = _directory_summary(shared)
    service.collect_directory(session.id, external.parent, _Progress())
    dedicated = service.add_candidate_bytes(
        session.id,
        harness.alice_id,
        file_name="drop.png",
        payload=payload,
        source="drop",
    )
    assert service.list_candidates(session.id, harness.alice_id, False)[0].id == (
        dedicated.id
    )

    service.adopt(session.id, harness.alice_id, dedicated.id)

    assert service.list_candidates(session.id, harness.save_only_id, False) == ()
    used = service.list_candidates(session.id, harness.save_only_id, True)[0]
    assert [item.game_id for item in used.used_by] == [harness.alice_id]
    assert external.exists()


def test_directory_imports_merge_atomically_and_cancellation_preserves_pool(
    harness: _Harness,
    tmp_path: Path,
) -> None:
    directory = tmp_path / "screenshots"
    directory.mkdir()
    sources = []
    for name, color in (("a.png", "red"), ("b.png", "blue"), ("c.png", "green")):
        source = directory / name
        source.write_bytes(_png(color))
        sources.append(source)
    service = harness.service()
    session = service.start()
    preview_root = (
        harness.paths.temp_dir / "cover-wizard" / session.id / "shared-previews"
    )
    first_a = _shared_candidate("a", sources[0], preview_root / "a.webp")
    first_b = _shared_candidate("b", sources[1], preview_root / "b.webp")
    harness.local.directory_summary = _directory_summary(first_a, first_b)
    first = service.collect_directory(session.id, directory, _Progress())
    assert len(first.candidates) == 2

    duplicate_a = _shared_candidate(
        "duplicate-a",
        sources[0],
        preview_root / "duplicate-a.webp",
    )
    second_c = _shared_candidate("c", sources[2], preview_root / "c.webp")
    harness.local.directory_summary = _directory_summary(duplicate_a, second_c)
    second = service.collect_directory(session.id, directory, _Progress())

    assert [item.id for item in second.candidates] == ["c"]
    assert second.duplicates == 1
    before_cancel = service.list_candidates(session.id, harness.alice_id, False)
    assert {item.id for item in before_cancel} == {"a", "b", "c"}
    assert not duplicate_a.preview_path.exists()

    harness.local.directory_failure = TaskCancelled("user")
    with pytest.raises(TaskCancelled):
        service.collect_directory(session.id, directory, _Progress())

    after_cancel = service.list_candidates(session.id, harness.alice_id, False)
    assert {item.id for item in after_cancel} == {"a", "b", "c"}
    assert all(item.preview_path.exists() for item in after_cancel)
    assert service.snapshot(session.id).source_operation_active is False


def test_failed_shared_import_does_not_record_usage(
    harness: _Harness,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    external = tmp_path / "shared.png"
    external.write_bytes(_png("orange"))
    service = harness.service()
    session = service.start()
    preview = (
        harness.paths.temp_dir
        / "cover-wizard"
        / session.id
        / "shared-previews"
        / "shared.webp"
    )
    shared = _shared_candidate("shared", external, preview)
    harness.local.directory_summary = _directory_summary(shared)
    service.collect_directory(session.id, external.parent, _Progress())
    monkeypatch.setattr(
        harness.covers,
        "import_file",
        lambda *_: (_ for _ in ()).throw(RuntimeError("planned import failure")),
    )

    with pytest.raises(RuntimeError, match="planned"):
        service.adopt(session.id, harness.alice_id, shared.id)

    candidate = service.list_candidates(session.id, harness.alice_id, False)[0]
    assert candidate.used_by == ()
    item = next(
        item
        for item in service.snapshot(session.id).queue
        if item.game_id == harness.alice_id
    )
    assert item.status == "ready"


def test_adopt_revalidates_source_and_cleans_only_temporary_files(
    harness: _Harness,
) -> None:
    service = harness.service()
    session = service.start()
    adopted_candidate = service.add_candidate_bytes(
        session.id,
        harness.alice_id,
        file_name="clipboard.png",
        payload=_png("red"),
        source="clipboard",
    )

    game = service.adopt(session.id, harness.alice_id, adopted_candidate.id)

    assert game.cover_original_relpath is not None
    assert not adopted_candidate.file_ref.path.exists()
    assert not adopted_candidate.preview_path.exists()
    snapshot = service.snapshot(session.id)
    alice = next(item for item in snapshot.queue if item.game_id == harness.alice_id)
    assert alice.status == "adopted"
    assert snapshot.current_game_id == harness.save_only_id

    external = harness.paths.app_root.parent / "external.png"
    external.write_bytes(_png("yellow"))
    external_candidate = _candidate(
        "external",
        harness.save_only_id,
        external,
        harness.paths.temp_dir / "external-preview.webp",
        hashlib.sha256(external.read_bytes()).hexdigest(),
        "shallow_scan",
        "游戏目录浅层扫描",
        temporary=False,
    )
    external_candidate.preview_path.write_bytes(b"preview")
    harness.local.shallow[harness.save_only_id] = _summary((external_candidate,))
    service.collect_shallow(session.id, harness.save_only_id, 10, 2, _Progress())
    external.write_bytes(_png("purple"))

    with pytest.raises(CandidateSourceChangedError):
        service.adopt(
            session.id,
            harness.save_only_id,
            external_candidate.id,
        )
    assert external.exists()
    assert service.list_candidates(session.id, harness.save_only_id, False)


def test_failed_import_preserves_candidate_and_queue_state(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = harness.service()
    session = service.start()
    candidate = service.add_candidate_bytes(
        session.id,
        harness.alice_id,
        file_name="candidate.png",
        payload=_png("red"),
        source="drop",
    )
    monkeypatch.setattr(
        harness.covers,
        "import_file",
        lambda *_: (_ for _ in ()).throw(RuntimeError("planned import failure")),
    )

    with pytest.raises(RuntimeError, match="planned"):
        service.adopt(session.id, harness.alice_id, candidate.id)

    assert candidate.file_ref.path.exists()
    assert service.list_candidates(session.id, harness.alice_id, False) == (candidate,)
    item = next(
        item
        for item in service.snapshot(session.id).queue
        if item.game_id == harness.alice_id
    )
    assert item.status == "ready"


def test_existing_cover_can_be_replaced_when_explicitly_included(
    harness: _Harness,
) -> None:
    service = harness.service()
    session = service.start(include_existing=True)
    before = harness.library.get_game(harness.bob_id)
    assert before is not None
    candidate = service.add_candidate_bytes(
        session.id,
        harness.bob_id,
        file_name="replacement.png",
        payload=_png("orange"),
        source="drop",
    )

    replaced = service.adopt(session.id, harness.bob_id, candidate.id)

    assert replaced.cover_revision == before.cover_revision + 1
    item = next(
        item
        for item in service.snapshot(session.id).queue
        if item.game_id == harness.bob_id
    )
    assert item.initial_has_cover is True
    assert item.status == "adopted"


def test_vndb_cancellation_propagates_instead_of_becoming_game_failure(
    harness: _Harness,
) -> None:
    service = harness.service()
    session = service.start()
    harness.vndb.failure = TaskCancelled("cancelled")

    with pytest.raises(TaskCancelled):
        service.collect_vndb(
            session.id, [harness.alice_id], 5, _Progress()
        )

    assert service.snapshot(session.id).source_operation_active is False


def test_vndb_batch_progress_stays_game_based(harness: _Harness) -> None:
    service = harness.service()
    session = service.start()
    progress = _RecordingProgress()

    service.collect_vndb(
        session.id,
        [harness.alice_id, harness.save_only_id],
        5,
        progress,
    )

    assert {total for _, total, _, _ in progress.reports} == {2}
    completed_values = [completed for completed, _, _, _ in progress.reports]
    assert completed_values == sorted(completed_values)
    assert progress.reports[-1][:2] == (2, 2)
    assert any(
        "正在搜索 1/2：Alice" in message
        for _, _, message, _ in progress.reports
    )


def test_vndb_current_search_uses_pure_title_and_keeps_version_in_local_ui(
    harness: _Harness,
) -> None:
    harness.library.set_game_metadata(harness.alice_id, "Alice", "v1.0.8")
    service = harness.service()
    session = service.start()
    progress = _RecordingProgress()

    service.collect_vndb(session.id, [harness.alice_id], 5, progress)

    alice = next(item for item in session.queue if item.game_id == harness.alice_id)
    assert harness.vndb.queries == ["Alice"]
    assert alice.title == "Alice"
    assert alice.version == "v1.0.8"
    assert any(
        "Alice v1.0.8" in message for _, _, message, _ in progress.reports
    )


def test_vndb_batch_search_never_appends_versions_to_queries(
    harness: _Harness,
) -> None:
    harness.library.set_game_metadata(harness.alice_id, "Alice", "v1.0.8")
    harness.library.set_game_metadata(harness.save_only_id, "Archive", "Build 2048")
    service = harness.service()
    session = service.start()

    service.collect_vndb(
        session.id,
        [harness.alice_id, harness.save_only_id],
        5,
        _Progress(),
    )

    assert harness.vndb.queries == ["Alice", "Archive"]


def test_busy_close_and_stale_cleanup_are_bounded(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    wizard_root = harness.paths.temp_dir / "cover-wizard"
    old = wizard_root / "old-session"
    fake_reparse = wizard_root / "fake-reparse"
    keep = harness.paths.temp_dir / "keep"
    old.mkdir(parents=True)
    fake_reparse.mkdir()
    keep.mkdir()
    monkeypatch.setattr(
        "gamesave_scout.covers.wizard_service._is_reparse_path",
        lambda path: path.name == "fake-reparse",
    )
    service = harness.service()
    assert not old.exists()
    assert fake_reparse.exists()
    assert keep.exists()

    entered = Event()
    release = Event()

    def blocking_scan(*args, **kwargs):
        del args, kwargs
        entered.set()
        assert release.wait(5)
        return _summary()

    monkeypatch.setattr(harness.local, "scan_game_directory", blocking_scan)
    session = service.start()
    worker = Thread(
        target=service.collect_shallow,
        args=(session.id, harness.alice_id, 10, 2, _Progress()),
    )
    worker.start()
    assert entered.wait(5)
    with pytest.raises(CoverWizardBusyError):
        service.close(session.id)
    release.set()
    worker.join(5)

    service.close(session.id)
    assert not (wizard_root / session.id).exists()


def _summary(
    candidates: tuple[CoverCandidate, ...] = (),
) -> LocalDiscoverySummary:
    return LocalDiscoverySummary(candidates, len(candidates), 0, False, ())


def _shared_candidate(
    candidate_id: str,
    source_path: Path,
    preview_path: Path,
) -> SharedCoverCandidate:
    staged = stage_candidate_file(source_path, preview_path)
    return SharedCoverCandidate(
        id=candidate_id,
        display_name=source_path.name,
        width=staged.width,
        height=staged.height,
        sha256=staged.sha256,
        quality_score=35.0,
        file_ref=staged.file_ref,
        preview_path=staged.preview_path,
    )


def _directory_summary(
    *candidates: SharedCoverCandidate,
    inspected: int | None = None,
    duplicates: int = 0,
    invalid: int = 0,
    truncated: bool = False,
) -> DirectoryImportSummary:
    return DirectoryImportSummary(
        candidates=tuple(candidates),
        inspected=len(candidates) if inspected is None else inspected,
        duplicates=duplicates,
        invalid=invalid,
        truncated=truncated,
        warnings=(),
    )


def _candidate(
    candidate_id: str,
    game_id: str,
    source_path: Path,
    preview_path: Path,
    sha256: str,
    source: str,
    source_label: str,
    *,
    temporary: bool = True,
) -> CoverCandidate:
    return CoverCandidate(
        id=candidate_id,
        game_id=game_id,
        source=source,  # type: ignore[arg-type]
        source_label=source_label,
        display_name=source_path.name,
        width=30,
        height=45,
        sha256=sha256,
        match_kind="manual",
        score=100,
        evidence=(source_label,),
        file_ref=CandidateFileRef(source_path, temporary, sha256),
        preview_path=preview_path,
        vndb_id="v1" if source == "vndb" else None,
    )


def _png(color: str) -> bytes:
    stream = BytesIO()
    Image.new("RGBA", (30, 45), color).save(stream, "PNG")
    return stream.getvalue()
