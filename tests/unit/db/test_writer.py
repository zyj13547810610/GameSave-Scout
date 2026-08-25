from concurrent.futures import Future
from pathlib import Path

import pytest

from gamesave_scout.db.connection import ConnectionFactory
from gamesave_scout.db.writer import DbWriter, WriterClosedError


def test_writer_commits_operations_in_submission_order(tmp_path: Path) -> None:
    factory = _event_database(tmp_path)
    writer = DbWriter(factory)
    writer.start()
    futures: list[Future[int]] = []
    for sequence in range(20):
        futures.append(
            writer.submit(
                lambda connection, n=sequence: connection.execute(
                    "INSERT INTO events(sequence, value) VALUES (?, ?)", (n, str(n))
                ).rowcount
            )
        )

    assert [future.result(timeout=2) for future in futures] == [1] * 20
    writer.close()

    with factory.connect(readonly=True) as connection:
        rows = connection.execute("SELECT sequence FROM events ORDER BY sequence")
        assert [row[0] for row in rows] == list(range(20))


def test_writer_rolls_back_failed_operation_and_continues(tmp_path: Path) -> None:
    factory = _event_database(tmp_path)
    writer = DbWriter(factory)
    writer.start()

    def fail_after_insert(connection: object) -> None:
        connection.execute("INSERT INTO events VALUES (1, 'rolled back')")
        raise ValueError("planned failure")

    failed = writer.submit(fail_after_insert)
    succeeded = writer.submit(
        lambda connection: connection.execute("INSERT INTO events VALUES (2, 'kept')").rowcount
    )

    with pytest.raises(ValueError, match="planned failure"):
        failed.result(timeout=2)
    assert succeeded.result(timeout=2) == 1
    writer.close()

    with factory.connect(readonly=True) as connection:
        assert [tuple(row) for row in connection.execute("SELECT * FROM events")] == [(2, "kept")]


def test_writer_rejects_work_after_close(tmp_path: Path) -> None:
    writer = DbWriter(_event_database(tmp_path))
    writer.start()
    writer.close()

    with pytest.raises(WriterClosedError):
        writer.submit(lambda connection: None)


def _event_database(tmp_path: Path) -> ConnectionFactory:
    factory = ConnectionFactory(tmp_path / "library.db")
    with factory.connect() as connection:
        connection.execute("CREATE TABLE events(sequence INTEGER PRIMARY KEY, value TEXT)")
        connection.commit()
    return factory
