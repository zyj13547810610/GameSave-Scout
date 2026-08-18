"""Apply ordered SQLite migrations with pre-upgrade backups."""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from gameshelf.db.connection import ConnectionFactory

LATEST_SCHEMA_VERSION = 2
_BACKUP_PATTERN = re.compile(
    r"^library-before-v\d+-\d{8}T\d{6}Z-[0-9a-f]{8}\.db$"
)


class MigrationError(RuntimeError):
    def __init__(self, message: str, *, backup_file: Path | None) -> None:
        super().__init__(message)
        self.backup_file = backup_file


class Migrator:
    def __init__(self, factory: ConnectionFactory, backups_dir: Path) -> None:
        self._factory = factory
        self._backups_dir = backups_dir

    def migrate(self) -> int:
        backup_file: Path | None = None
        with self._factory.connect() as connection:
            current = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if current > LATEST_SCHEMA_VERSION:
                raise MigrationError(
                    f"数据库版本 {current} 高于当前程序支持的版本 {LATEST_SCHEMA_VERSION}。",
                    backup_file=None,
                )
            if current == LATEST_SCHEMA_VERSION:
                return current

            if self._has_user_tables(connection):
                backup_file = self._backup(connection, LATEST_SCHEMA_VERSION)

            try:
                for version in range(current + 1, LATEST_SCHEMA_VERSION + 1):
                    sql = self.migration_sql(version)
                    connection.executescript(f"BEGIN IMMEDIATE;\n{sql}\nCOMMIT;")
            except (OSError, sqlite3.Error) as error:
                if connection.in_transaction:
                    connection.rollback()
                location = f"，迁移前备份位于：{backup_file}" if backup_file else ""
                raise MigrationError(
                    f"数据库迁移失败，原数据库未升级{location}", backup_file=backup_file
                ) from error

            return int(connection.execute("PRAGMA user_version").fetchone()[0])

    def migration_sql(self, version: int) -> str:
        migration = Path(__file__).parent / "migrations" / f"{version:04d}_initial.sql"
        if not migration.is_file():
            raise MigrationError(f"缺少数据库迁移文件：{migration.name}", backup_file=None)
        return migration.read_text(encoding="utf-8")

    @staticmethod
    def _has_user_tables(connection: sqlite3.Connection) -> bool:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' LIMIT 1"
        ).fetchone()
        return row is not None

    def _backup(self, connection: sqlite3.Connection, target_version: int) -> Path:
        self._backups_dir.mkdir(parents=True, exist_ok=True)
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup_file = self._backups_dir / (
            f"library-before-v{target_version}-{timestamp}-{uuid4().hex[:8]}.db"
        )
        with sqlite3.connect(backup_file) as destination:
            connection.backup(destination)
        self._prune_backups()
        return backup_file

    def _prune_backups(self) -> None:
        backups = sorted(
            (
                path
                for path in self._backups_dir.iterdir()
                if path.is_file() and _BACKUP_PATTERN.fullmatch(path.name)
            ),
            key=lambda path: (path.stat().st_mtime_ns, path.name),
            reverse=True,
        )
        for old_backup in backups[5:]:
            old_backup.unlink()
