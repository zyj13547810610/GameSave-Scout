from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from gamesave_scout.covers import local_discovery
from gamesave_scout.covers.local_discovery import LocalCoverDiscovery
from gamesave_scout.library.models import Game


@dataclass
class _Progress:
    checks: int = 0
    reports: int = 0
    messages: list[str] | None = None

    def report(
        self,
        completed: int,
        total: int | None,
        message: str,
        *,
        details: object = None,
    ) -> None:
        del completed, total, details
        self.reports += 1
        if self.messages is not None:
            self.messages.append(message)

    def raise_if_cancelled(self) -> None:
        self.checks += 1


def _game(
    game_id: str = "game-1",
    *,
    title: str = "Alice",
    relative_dir: str = "AliceGame",
) -> Game:
    return Game(
        id=game_id,
        scan_root_id="root-1",
        relative_dir=relative_dir,
        install_path_key=rf"d:\games\{relative_dir}",
        title=title,
        detected_title=title,
        status="installed",
        detected_engine_id=None,
        detected_engine_variant=None,
        engine_id=None,
        engine_variant=None,
        engine_is_manual=False,
        engine_confidence=None,
        engine_evidence=(),
        engine_rules_version=None,
        main_exe_relpath=None,
        main_exe_is_manual=False,
        working_dir_relpath=None,
        launch_args=(),
        environment={},
        exe_arch="unknown",
        cover_original_relpath=None,
        cover_thumb_relpath=None,
        cover_revision=0,
        last_launched_at=None,
        missing_since=None,
    )


def _write_image(path: Path, size: tuple[int, int] = (400, 600)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image_format = "JPEG" if path.suffix.lower() in {".jpg", ".jpeg"} else "PNG"
    Image.new("RGB", size, (60, 90, 120)).save(path, image_format)


@pytest.mark.parametrize(
    ("depth", "expected_names"),
    [
        (1, {"root.png"}),
        (2, {"root.png", "a-child.jpg", "b-child.jpg"}),
        (3, {"root.png", "a-child.jpg", "b-child.jpg", "grandchild.png"}),
    ],
)
def test_shallow_scan_respects_total_layer_count_and_stable_breadth_first_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    depth: int,
    expected_names: set[str],
) -> None:
    install = tmp_path / "game"
    _write_image(install / "root.png")
    _write_image(install / "A" / "a-child.jpg")
    _write_image(install / "B" / "b-child.jpg")
    _write_image(install / "A" / "Deep" / "grandchild.png")
    _write_image(install / "linked" / "ignored.png")
    monkeypatch.setattr(
        local_discovery,
        "_is_reparse_point",
        lambda entry: entry.name == "linked",
    )
    progress = _Progress(messages=[])

    result = LocalCoverDiscovery().scan_game_directory(
        _game(), install, tmp_path / "session", 10, depth, progress
    )

    assert {item.display_name for item in result.candidates} == expected_names
    assert result.inspected == len(expected_names)
    assert result.skipped == 0
    assert result.truncated is False
    assert progress.checks >= 4
    assert progress.reports == len(expected_names)
    assert progress.messages == [
        f"正在检查 {name}"
        for name in ["root.png", "a-child.jpg", "b-child.jpg", "grandchild.png"]
        if name in expected_names
    ]


def test_shallow_scan_ranks_title_portrait_before_unrelated_landscape(
    tmp_path: Path,
) -> None:
    install = tmp_path / "game"
    _write_image(install / "unrelated.png", (160, 90))
    _write_image(install / "Alice cover.png", (1200, 1800))

    result = LocalCoverDiscovery().scan_game_directory(
        _game(), install, tmp_path / "session", 1, 2, _Progress()
    )

    assert [item.display_name for item in result.candidates] == ["Alice cover.png"]
    assert result.candidates[0].match_kind == "normalized"
    assert result.truncated is True


def test_cover_directory_is_nonrecursive_and_matches_title_or_install_leaf(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "covers"
    _write_image(directory / "Alice 封面.png")
    _write_image(directory / "Expedition 33 poster.jpg")
    _write_image(directory / "House in Fata Morgana.png")
    _write_image(directory / "unrelated.png")
    _write_image(directory / "nested" / "Alice.png")
    games = (
        _game("alice", title="Alice", relative_dir="AliceGame"),
        _game("expedition", title="33号远征队", relative_dir="Expedition 33"),
        _game("house", title="The House in Fata Morgana", relative_dir="Fata"),
    )

    results = LocalCoverDiscovery().match_cover_directory(
        games, directory, tmp_path / "session", _Progress()
    )

    assert [item.display_name for item in results["alice"].candidates] == [
        "Alice 封面.png"
    ]
    assert [item.display_name for item in results["expedition"].candidates] == [
        "Expedition 33 poster.jpg"
    ]
    assert [item.display_name for item in results["house"].candidates] == [
        "House in Fata Morgana.png"
    ]
    assert all(
        item.source == "cover_directory"
        for summary in results.values()
        for item in summary.candidates
    )


def test_one_damaged_image_isolated_from_later_valid_image(tmp_path: Path) -> None:
    install = tmp_path / "game"
    install.mkdir()
    (install / "a-damaged.png").write_bytes(b"broken")
    _write_image(install / "b-valid.png")

    result = LocalCoverDiscovery().scan_game_directory(
        _game(), install, tmp_path / "session", 10, 2, _Progress()
    )

    assert [item.display_name for item in result.candidates] == ["b-valid.png"]
    assert result.inspected == 2
    assert result.skipped == 1
    assert len(result.warnings) == 1


def test_shallow_scan_stops_at_the_global_image_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install = tmp_path / "game"
    for name in ("a.png", "b.png", "c.png"):
        _write_image(install / name)
    monkeypatch.setattr(local_discovery, "MAX_DISCOVERY_FILES", 2)

    result = LocalCoverDiscovery().scan_game_directory(
        _game(), install, tmp_path / "session", 10, 1, _Progress()
    )

    assert result.inspected == 2
    assert result.truncated is True


def test_candidate_limit_is_bounded_to_one_hundred_for_cover_directory(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "covers"
    payload = BytesIO()
    Image.new("RGB", (2, 3)).save(payload, "PNG")
    directory.mkdir()
    for index in range(101):
        (directory / f"Alice {index}.png").write_bytes(payload.getvalue())

    result = LocalCoverDiscovery().match_cover_directory(
        (_game(),), directory, tmp_path / "session", _Progress()
    )["game-1"]

    assert len(result.candidates) == 100
    assert result.truncated is True
