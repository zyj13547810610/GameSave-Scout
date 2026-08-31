"""Desktop window size normalization for portable pywebview startup."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import cast

from gamesave_scout.bootstrap.config import (
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
    MAX_WINDOW_DIMENSION,
    MIN_WINDOW_HEIGHT,
    MIN_WINDOW_WIDTH,
)


@dataclass(frozen=True, slots=True)
class WindowSize:
    width: int
    height: int


def fit_window_to_primary_work_area(
    width: int,
    height: int,
    screens: object,
) -> WindowSize:
    """Limit a saved logical size to the primary screen's working area."""
    saved = _safe_window_size(width, height)
    primary = _first_item(screens)
    if primary is None:
        return saved

    frame = getattr(primary, "frame", None)
    available_width = _strict_positive_int(getattr(frame, "Width", None))
    available_height = _strict_positive_int(getattr(frame, "Height", None))
    if available_width is None:
        available_width = _strict_positive_int(getattr(primary, "width", None))
    if available_height is None:
        available_height = _strict_positive_int(getattr(primary, "height", None))

    return WindowSize(
        width=_fit_dimension(
            saved.width,
            available_width,
            minimum=MIN_WINDOW_WIDTH,
        ),
        height=_fit_dimension(
            saved.height,
            available_height,
            minimum=MIN_WINDOW_HEIGHT,
        ),
    )


def read_restored_window_size(window: object) -> WindowSize:
    """Read the normal logical size, including while a WinForms window is maximized."""
    native = getattr(window, "native", None)
    restore_bounds = getattr(native, "RestoreBounds", None)
    scale = getattr(native, "_scale", None)
    physical_width = _strict_positive_number(getattr(restore_bounds, "Width", None))
    physical_height = _strict_positive_number(getattr(restore_bounds, "Height", None))
    logical_scale = _strict_positive_number(scale)
    if (
        _is_maximized_or_minimized(getattr(native, "WindowState", None))
        and
        physical_width is not None
        and physical_height is not None
        and logical_scale is not None
    ):
        return _safe_window_size(
            round(physical_width / logical_scale),
            round(physical_height / logical_scale),
        )

    return _safe_window_size(
        getattr(window, "width", DEFAULT_WINDOW_WIDTH),
        getattr(window, "height", DEFAULT_WINDOW_HEIGHT),
    )


def _first_item(values: object) -> object | None:
    if not isinstance(values, Iterable):
        return None
    try:
        return cast(object, next(iter(values)))
    except StopIteration:
        return None


def _safe_window_size(width: object, height: object) -> WindowSize:
    return WindowSize(
        width=_bounded_dimension(
            width,
            default=DEFAULT_WINDOW_WIDTH,
            minimum=MIN_WINDOW_WIDTH,
        ),
        height=_bounded_dimension(
            height,
            default=DEFAULT_WINDOW_HEIGHT,
            minimum=MIN_WINDOW_HEIGHT,
        ),
    )


def _bounded_dimension(value: object, *, default: int, minimum: int) -> int:
    if type(value) is not int:
        return default
    return min(MAX_WINDOW_DIMENSION, max(minimum, value))


def _fit_dimension(saved: int, available: int | None, *, minimum: int) -> int:
    if available is None:
        return saved
    return max(minimum, min(saved, available))


def _strict_positive_int(value: object) -> int | None:
    return value if type(value) is int and value > 0 else None


def _strict_positive_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    return float(value)


def _is_maximized_or_minimized(state: object) -> bool:
    state_name = str(state).casefold()
    if state_name.endswith(("maximized", "minimized")):
        return True
    return getattr(state, "value__", None) in (1, 2)
