"""Create the current SQLite schema and reject legacy development databases."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from gamesave_scout.db.connection import ConnectionFactory

LATEST_SCHEMA_VERSION = 4


class MigrationError(RuntimeError):
    def __init__(self, message: str, *, backup_file: Path | None) -> None:
        super().__init__(message)
        self.backup_file = backup_file


class Migrator:
    def __init__(self, factory: ConnectionFactory, backups_dir: Path) -> None:
        self._factory = factory
        self._backups_dir = backups_dir

    def migrate(self) -> int:
        with self._factory.connect() as connection:
            current = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if current > LATEST_SCHEMA_VERSION:
                raise MigrationError(
                    f"数据库版本 {current} 高于当前程序支持的版本 {LATEST_SCHEMA_VERSION}。",
                    backup_file=None,
                )
            if current == LATEST_SCHEMA_VERSION:
                return current

            if current != 0 or self._has_user_tables(connection):
                raise MigrationError(
                    "检测到旧版 GameSave Scout 数据库。V0.2 开发版不执行数据库迁移，"
                    "请退出程序后手动移动或删除 data/library.db，再重新启动。"
                    "程序没有修改原数据库。",
                    backup_file=None,
                )

            try:
                for version in range(1, LATEST_SCHEMA_VERSION + 1):
                    sql = self.migration_sql(version)
                    connection.executescript(f"BEGIN IMMEDIATE;\n{sql}\nCOMMIT;")
            except (OSError, sqlite3.Error) as error:
                if connection.in_transaction:
                    connection.rollback()
                raise MigrationError(
                    "新数据库创建失败，未完成初始化。", backup_file=None
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
