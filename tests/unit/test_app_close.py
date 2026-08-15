from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from gameshelf.app import _allow_window_close
from gameshelf.bootstrap.application import Application


class FakeGuidedSaves:
    def __init__(self, allow: bool) -> None:
        self.allow = allow
        self.calls = 0

    def request_close(self) -> bool:
        self.calls += 1
        return self.allow


def test_window_close_is_allowed_without_an_active_guided_session() -> None:
    guided = FakeGuidedSaves(True)
    application = cast(Application, SimpleNamespace(guided_saves=guided))

    assert _allow_window_close(application) is True
    assert guided.calls == 1


def test_window_close_is_blocked_while_guided_session_awaits_resolution() -> None:
    guided = FakeGuidedSaves(False)
    application = cast(Application, SimpleNamespace(guided_saves=guided))

    assert _allow_window_close(application) is False
    assert guided.calls == 1
