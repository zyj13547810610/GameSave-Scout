import os
from pathlib import Path
from threading import Event

import pytest

from gameshelf.bridge.tasks import TaskCancelled, TaskContext
from gameshelf.library.models import ScanRoot
from gameshelf.scanning.discovery import RootUnavailableError, enumerate_candidates
from gameshelf.scanning.path_keys import windows_path_key


@pytest.fixture
def task_context() -> TaskContext:
    return TaskContext(Event(), lambda *_: None)


def test_children_mode_keeps_every_direct_directory_even_without_exe(
    tmp_path: Path, task_context: TaskContext
) -> None:
    root_path = tmp_path / "games"
    (root_path / "NoExeYet").mkdir(parents=True)
    (root_path / "WithExe").mkdir()
    (root_path / "WithExe" / "Game.exe").write_bytes(b"MZ")
    root = make_root(root_path, mode="children", depth=1)

    assert [item.relative_dir for item in enumerate_candidates(root, task_context)] == [
        "NoExeYet",
        "WithExe",
    ]


def test_recursive_mode_finds_nested_exe_and_stops_below_game(
    tmp_path: Path, task_context: TaskContext
) -> None:
    root_path = tmp_path / "games"
    game = root_path / "group" / "GameC"
    (game / "tools").mkdir(parents=True)
    (game / "Game.exe").write_bytes(b"MZ")
    (game / "tools" / "helper.exe").write_bytes(b"MZ")
    root = make_root(root_path, mode="recursive", depth=2)

    candidates = tuple(enumerate_candidates(root, task_context))

    assert [item.relative_dir for item in candidates] == ["group/GameC"]
    assert candidates[0].reason == "generic_executable"
    assert candidates[0].depth == 2


def test_recursive_mode_continues_below_directory_with_only_auxiliary_exes(
    tmp_path: Path, task_context: TaskContext
) -> None:
    root_path = tmp_path / "games"
    container = root_path / "group"
    game = container / "GameC"
    game.mkdir(parents=True)
    (container / "setup.exe").write_bytes(b"MZ")
    (container / "config.exe").write_bytes(b"MZ")
    (container / "UnityCrashHandler32.exe").write_bytes(b"MZ")
    (game / "Game.exe").write_bytes(b"MZ")
    root = make_root(root_path, mode="recursive", depth=2)

    assert [item.relative_dir for item in enumerate_candidates(root, task_context)] == [
        "group/GameC"
    ]


def test_recursive_mode_stops_when_auxiliary_and_game_exes_are_mixed(
    tmp_path: Path, task_context: TaskContext
) -> None:
    root_path = tmp_path / "games"
    container = root_path / "group"
    nested = container / "Nested"
    nested.mkdir(parents=True)
    (container / "setup.exe").write_bytes(b"MZ")
    (container / "Game.exe").write_bytes(b"MZ")
    (nested / "Nested.exe").write_bytes(b"MZ")
    root = make_root(root_path, mode="recursive", depth=2)

    assert [item.relative_dir for item in enumerate_candidates(root, task_context)] == [
        "group"
    ]


def test_recursive_results_are_sorted_and_exclusions_ignore_case(
    tmp_path: Path, task_context: TaskContext
) -> None:
    root_path = tmp_path / "games"
    for relative in ["zeta/GameZ", "Alpha/GameA", "Group/CACHE"]:
        directory = root_path / Path(relative)
        directory.mkdir(parents=True)
        (directory / "game.EXE").write_bytes(b"MZ")
    root = make_root(root_path, mode="recursive", depth=2, exclusions=("**/cache",))

    assert [item.relative_dir for item in enumerate_candidates(root, task_context)] == [
        "Alpha/GameA",
        "zeta/GameZ",
    ]


def test_unavailable_child_warns_and_scan_continues(
    tmp_path: Path,
    task_context: TaskContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_path = tmp_path / "games"
    blocked = root_path / "Blocked"
    blocked.mkdir(parents=True)
    (root_path / "Visible").mkdir()
    original_scandir = os.scandir
    warnings: list[str] = []

    def fake_scandir(path: os.PathLike[str] | str):  # type: ignore[no-untyped-def]
        if Path(path) == blocked:
            raise PermissionError("blocked for test")
        return original_scandir(path)

    monkeypatch.setattr("gameshelf.scanning.discovery.os.scandir", fake_scandir)
    monkeypatch.setattr(
        "gameshelf.scanning.discovery.logger.warning",
        lambda message, path, _error: warnings.append(message % (path, _error)),
    )
    root = make_root(root_path, mode="children", depth=1)

    assert [item.relative_dir for item in enumerate_candidates(root, task_context)] == [
        "Visible"
    ]
    assert any("Blocked" in warning for warning in warnings)


def test_link_or_reparse_directory_is_skipped(
    tmp_path: Path, task_context: TaskContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    root_path = tmp_path / "games"
    skipped = root_path / "Linked"
    skipped.mkdir(parents=True)
    (root_path / "Normal").mkdir()
    monkeypatch.setattr(
        "gameshelf.scanning.discovery._is_link_or_reparse",
        lambda entry: entry.name == "Linked",
    )
    root = make_root(root_path, mode="children", depth=1)

    assert [item.relative_dir for item in enumerate_candidates(root, task_context)] == [
        "Normal"
    ]


def test_cancellation_after_enumeration_starts_stops_promptly(tmp_path: Path) -> None:
    root_path = tmp_path / "games"
    for name in ["A", "B"]:
        (root_path / name).mkdir(parents=True)
    cancel_event = Event()
    context = TaskContext(cancel_event, lambda *_: None)
    candidates = enumerate_candidates(
        make_root(root_path, mode="children", depth=1), context
    )

    assert next(candidates).relative_dir == "A"
    cancel_event.set()
    with pytest.raises(TaskCancelled):
        next(candidates)


def test_missing_root_raises_unavailable_without_results(
    tmp_path: Path, task_context: TaskContext
) -> None:
    root = make_root(tmp_path / "missing", mode="children", depth=1)

    with pytest.raises(RootUnavailableError):
        tuple(enumerate_candidates(root, task_context))


def make_root(
    path: Path,
    *,
    mode: str,
    depth: int,
    exclusions: tuple[str, ...] = (),
) -> ScanRoot:
    return ScanRoot(
        id="root-1",
        display_path=str(path),
        path_key=windows_path_key(path),
        enabled=True,
        scan_mode=mode,  # type: ignore[arg-type]
        max_depth=depth,
        exclusions=exclusions,
        last_scanned_at=None,
        last_scan_status="never",
        last_error=None,
        created_at="2026-08-12T00:00:00+00:00",
    )
