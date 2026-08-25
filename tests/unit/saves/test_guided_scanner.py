from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from gamesave_scout.saves.guided_scanner import BoundedMetadataScanner


def test_scanner_returns_only_files_changed_inside_the_session_window(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    old_file = root / "old.sav"
    old_file.write_bytes(b"old")
    old_timestamp = time.time() - 60
    os.utime(old_file, (old_timestamp, old_timestamp))
    old_created_ns = old_file.stat().st_ctime_ns
    deadline = time.monotonic() + 1.0
    while (started_ns := time.time_ns()) <= old_created_ns:
        if time.monotonic() >= deadline:
            pytest.fail("The system clock did not advance before the deadline.")
        time.sleep(0.001)
    new_file = root / "slot1.sav"
    new_file.write_bytes(b"new-save")
    finished_ns = time.time_ns()

    result = BoundedMetadataScanner().scan(
        root, started_ns=started_ns, finished_ns=finished_ns
    )

    assert [item.display_path for item in result.files] == [str(new_file)]
    assert result.files[0].size == len(b"new-save")
    assert result.truncated_by is None


def test_scanner_stops_descending_at_the_depth_limit(tmp_path: Path) -> None:
    root = tmp_path / "root"
    current = root
    for depth in range(4):
        current = current / f"level-{depth}"
        current.mkdir(parents=True)
        (current / f"slot-{depth}.sav").write_bytes(b"save")
    started_ns = 0
    finished_ns = time.time_ns() + 1_000_000_000

    result = BoundedMetadataScanner(max_depth=2).scan(
        root, started_ns=started_ns, finished_ns=finished_ns
    )

    assert result.truncated_by == "depth"
    assert all("level-2" not in item.display_path for item in result.files)


def test_scanner_stops_at_the_entry_limit(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    for index in range(4):
        (root / f"slot-{index}.sav").write_bytes(b"save")

    result = BoundedMetadataScanner(max_entries=2).scan(
        root, started_ns=0, finished_ns=time.time_ns() + 1_000_000_000
    )

    assert result.entries_examined == 2
    assert result.truncated_by == "entries"
    assert len(result.files) <= 2


def test_scanner_stops_when_the_injected_deadline_expires(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "slot.sav").write_bytes(b"save")
    clock = ExpiringClock()

    result = BoundedMetadataScanner(max_seconds=1.0, monotonic=clock).scan(
        root, started_ns=0, finished_ns=time.time_ns() + 1_000_000_000
    )

    assert result.truncated_by == "deadline"
    assert result.entries_examined == 0


def test_scanner_skips_reparse_directories_without_reading_their_files(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    skipped = root / "junction"
    skipped.mkdir(parents=True)
    (skipped / "secret.sav").write_bytes(b"secret")
    visible = root / "slot.sav"
    visible.write_bytes(b"visible")

    result = BoundedMetadataScanner(
        is_reparse_point=lambda path: path == skipped
    ).scan(root, started_ns=0, finished_ns=time.time_ns() + 1_000_000_000)

    assert [item.display_path for item in result.files] == [str(visible)]
    assert result.skipped_reparse_points == 1


class ExpiringClock:
    def __init__(self) -> None:
        self._calls = 0

    def __call__(self) -> float:
        self._calls += 1
        return 0.0 if self._calls == 1 else 2.0
