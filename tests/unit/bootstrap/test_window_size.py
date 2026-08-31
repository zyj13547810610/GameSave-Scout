from __future__ import annotations

from importlib import import_module
from types import SimpleNamespace
from typing import Any


def _subject() -> Any:
    return import_module("gamesave_scout.bootstrap.window_size")


def test_saved_size_is_limited_to_primary_work_area() -> None:
    subject = _subject()
    screens = [SimpleNamespace(frame=SimpleNamespace(Width=1536, Height=824))]

    result = subject.fit_window_to_primary_work_area(3000, 2000, screens)

    assert result == subject.WindowSize(1536, 824)


def test_screen_bounds_are_used_when_work_area_is_unavailable() -> None:
    subject = _subject()
    screens = [SimpleNamespace(frame=None, width=1366, height=768)]

    result = subject.fit_window_to_primary_work_area(1440, 900, screens)

    assert result == subject.WindowSize(1366, 768)


def test_saved_size_is_preserved_when_screen_information_is_unavailable() -> None:
    subject = _subject()

    result = subject.fit_window_to_primary_work_area(1440, 900, [])

    assert result == subject.WindowSize(1440, 900)


def test_maximized_window_uses_logical_restore_bounds() -> None:
    subject = _subject()
    native = SimpleNamespace(
        RestoreBounds=SimpleNamespace(Width=1500, Height=900),
        _scale=1.25,
        WindowState="Maximized",
    )
    window = SimpleNamespace(native=native, width=1536, height=824)

    result = subject.read_restored_window_size(window)

    assert result == subject.WindowSize(1200, 720)


def test_resized_normal_window_uses_current_size_instead_of_restore_bounds() -> None:
    subject = _subject()
    native = SimpleNamespace(
        RestoreBounds=SimpleNamespace(Width=1180, Height=760),
        _scale=1.0,
        WindowState="Normal",
    )
    window = SimpleNamespace(native=native, width=1375, height=845)

    result = subject.read_restored_window_size(window)

    assert result == subject.WindowSize(1375, 845)


def test_window_size_falls_back_to_pywebview_dimensions() -> None:
    subject = _subject()
    window = SimpleNamespace(native=None, width=1400, height=880)

    result = subject.read_restored_window_size(window)

    assert result == subject.WindowSize(1400, 880)
