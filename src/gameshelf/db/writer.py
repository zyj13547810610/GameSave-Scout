"""Serialize all mutable SQLite work onto one connection-owning thread."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from queue import Queue
from threading import Lock, Thread
from typing import Any, cast

from gameshelf.db.connection import ConnectionFactory

type WriteOperation[T] = Callable[[sqlite3.Connection], T]


class WriterClosedError(RuntimeError):
    """Raised when work is submitted after the writer has closed."""


class WriterNotStartedError(RuntimeError):
    """Raised when work is submitted before the writer starts."""


@dataclass(frozen=True)
class _WriteJob[T]:
    operation: WriteOperation[T]
    future: Future[T]


_SENTINEL = object()


class DbWriter:
    def __init__(self, factory: ConnectionFactory) -> None:
        self._factory = factory
        self._queue: Queue[_WriteJob[Any] | object] = Queue()
        self._state_lock = Lock()
        self._thread: Thread | None = None
        self._started = False
        self._closed = False

    def start(self) -> None:
        with self._state_lock:
            if self._closed:
                raise WriterClosedError("数据库写入器已经关闭。")
            if self._started:
                return
            self._thread = Thread(target=self._run, name="gameshelf-db-writer", daemon=True)
            self._started = True
            self._thread.start()

    def submit[T](self, operation: WriteOperation[T]) -> Future[T]:
        with self._state_lock:
            if self._closed:
                raise WriterClosedError("数据库写入器已经关闭。")
            if not self._started:
                raise WriterNotStartedError("数据库写入器尚未启动。")
            future: Future[T] = Future()
            self._queue.put(_WriteJob(operation, future))
            return future

    def close(self, timeout: float = 5.0) -> None:
        with self._state_lock:
            if self._closed:
                thread = self._thread
            else:
                self._closed = True
                thread = self._thread
                if self._started:
                    self._queue.put(_SENTINEL)
        if thread is not None:
            thread.join(timeout)
            if thread.is_alive():
                raise TimeoutError("数据库写入线程未能在限定时间内停止。")

    def _run(self) -> None:
        with self._factory.connect() as connection:
            while True:
                item = self._queue.get()
                try:
                    if item is _SENTINEL:
                        return
                    job = cast(_WriteJob[Any], item)
                    if not job.future.set_running_or_notify_cancel():
                        continue
                    self._execute(connection, job)
                finally:
                    self._queue.task_done()

    @staticmethod
    def _execute(connection: sqlite3.Connection, job: _WriteJob[Any]) -> None:
        try:
            connection.execute("BEGIN IMMEDIATE")
            result = job.operation(connection)
            connection.commit()
        except Exception as error:
            connection.rollback()
            job.future.set_exception(error)
        else:
            job.future.set_result(result)
