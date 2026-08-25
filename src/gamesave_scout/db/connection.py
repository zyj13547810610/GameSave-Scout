"""Create short-lived SQLite connections with one consistent policy."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ConnectionFactory:
    database_file: Path

    def connect(self, *, readonly: bool = False) -> sqlite3.Connection:
        if readonly:
            uri = f"{self.database_file.resolve(strict=False).as_uri()}?mode=ro"
            connection = sqlite3.connect(uri, uri=True, timeout=5.0)
        else:
            self.database_file.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.database_file, timeout=5.0)

        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        if not readonly:
            connection.execute("PRAGMA journal_mode=WAL")
        return connection
