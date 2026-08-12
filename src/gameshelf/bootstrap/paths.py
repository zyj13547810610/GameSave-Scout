"""Resolve every GameShelf-owned path from the portable application root."""

from __future__ import annotations

import os
import sys
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4


class DataDirectoryError(OSError):
    """Raised when the executable-adjacent data directory is not writable."""


def runtime_root(*, frozen: bool | None = None, executable: Path | None = None) -> Path:
    """Return the application root without consulting the current working directory."""

    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    if is_frozen:
        executable_path = Path(sys.executable) if executable is None else executable
        return executable_path.resolve(strict=False).parent
    return Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class AppPaths:
    """Immutable locations for all application-owned persistent state."""

    app_root: Path
    data_dir: Path
    database_file: Path
    config_file: Path
    covers_original_dir: Path
    covers_thumbs_dir: Path
    manifests_dir: Path
    webview_dir: Path
    backups_dir: Path
    logs_dir: Path
    temp_dir: Path

    @classmethod
    def from_root(cls, app_root: Path) -> AppPaths:
        root = app_root.resolve(strict=False)
        data = root / "data"
        return cls(
            app_root=root,
            data_dir=data,
            database_file=data / "library.db",
            config_file=data / "config.json",
            covers_original_dir=data / "covers" / "original",
            covers_thumbs_dir=data / "covers" / "thumbs",
            manifests_dir=data / "manifests",
            webview_dir=data / "webview",
            backups_dir=data / "db_backups",
            logs_dir=data / "logs",
            temp_dir=data / "temp",
        )

    @classmethod
    def for_runtime(cls) -> AppPaths:
        return cls.from_root(runtime_root())

    def required_directories(self) -> tuple[Path, ...]:
        return (
            self.data_dir,
            self.covers_original_dir,
            self.covers_thumbs_dir,
            self.manifests_dir,
            self.webview_dir,
            self.backups_dir,
            self.logs_dir,
            self.temp_dir,
        )

    def owned_paths(self) -> tuple[Path, ...]:
        return (
            *self.required_directories(),
            self.database_file,
            self.config_file,
        )

    def ensure_writable(self) -> None:
        probe = self.data_dir / f".gameshelf-write-test-{uuid4()}.tmp"
        try:
            self.app_root.mkdir(parents=True, exist_ok=True)
            for directory in self.required_directories():
                directory.mkdir(parents=True, exist_ok=True)
            with probe.open("xb") as stream:
                stream.write(b"GameShelf")
                stream.flush()
                os.fsync(stream.fileno())
            probe.unlink()
        except OSError as error:
            with suppress(OSError):
                probe.unlink(missing_ok=True)
            raise DataDirectoryError(
                f"无法写入程序旁的数据目录：{self.data_dir}。请将整个程序目录移动到可写位置。"
            ) from error
