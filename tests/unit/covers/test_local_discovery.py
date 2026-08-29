from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from PIL import Image

from gamesave_scout.bridge.tasks import TaskCancelled
from gamesave_scout.covers import local_discovery
from gamesave_scout.covers.local_discovery import (
    InvalidCoverDirectory,
    LocalCoverDiscovery,
)
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


class _CancelOnFirstReport(_Progress):
    def report(self, *args: object, **kwargs: object) -> None:
        super().report(*args, **kwargs)
        raise TaskCancelled("user")


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


def test_cover_directory_import_keeps_unmatched_hash_names_and_is_nonrecursive(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "covers"
    _write_image(directory / "Alice cover.png", (400, 600))
    _write_image(directory / "86025945_p10.jpg", (410, 610))
    _write_image(directory / "nested" / "ignored.png", (420, 620))
    progress = _Progress(messages=[])

    result = LocalCoverDiscovery().import_cover_directory(
        directory,
        tmp_path / "session",
        frozenset(),
        1000,
        progress,
    )

    assert [item.display_name for item in result.candidates] == [
        "86025945_p10.jpg",
        "Alice cover.png",
    ]
    assert result.inspected == 2
    assert result.duplicates == 0
    assert result.invalid == 0
    assert result.truncated is False
    assert all(item.file_ref.temporary is False for item in result.candidates)
    assert all(0 <= item.quality_score <= 35 for item in result.candidates)
    assert progress.messages == [
        "正在导入 86025945_p10.jpg",
        "正在导入 Alice cover.png",
    ]


def test_cover_directory_import_deduplicates_content_and_isolates_bad_images(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "covers"
    _write_image(directory / "first.png", (400, 600))
    (directory / "copy.png").write_bytes((directory / "first.png").read_bytes())
    directory.joinpath("broken.png").write_bytes(b"broken")

    result = LocalCoverDiscovery().import_cover_directory(
        directory,
        tmp_path / "session",
        frozenset(),
        1000,
        _Progress(),
    )

    assert len(result.candidates) == 1
    assert result.inspected == 3
    assert result.duplicates == 1
    assert result.invalid == 1
    assert result.warnings == ("无法读取图片：broken.png",)


def test_cover_directory_import_respects_remaining_shared_capacity(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "covers"
    _write_image(directory / "a.png", (400, 600))
    _write_image(directory / "b.png", (401, 601))

    result = LocalCoverDiscovery().import_cover_directory(
        directory,
        tmp_path / "session",
        frozenset(),
        1,
        _Progress(),
    )

    assert len(result.candidates) == 1
    assert result.inspected == 2
    assert result.truncated is True

def test_cover_directory_import_stops_at_the_global_image_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = tmp_path / "covers"
    for index, size in enumerate(((400, 600), (401, 601), (402, 602))):
        _write_image(directory / f"{index}.png", size)
    monkeypatch.setattr(local_discovery, "MAX_DISCOVERY_FILES", 2)

    result = LocalCoverDiscovery().import_cover_directory(
        directory,
        tmp_path / "session",
        frozenset(),
        1000,
        _Progress(),
    )

    assert result.inspected == 2
    assert len(result.candidates) == 2
    assert result.truncated is True


@pytest.mark.parametrize("directory_kind", ["missing", "file"])
def test_cover_directory_import_rejects_invalid_roots(
    tmp_path: Path,
    directory_kind: str,
) -> None:
    directory = tmp_path / "covers"
    if directory_kind == "file":
        directory.write_text("not a directory", encoding="utf-8")

    with pytest.raises(
        InvalidCoverDirectory,
        match="所选封面目录不存在或不是目录。",
    ):
        LocalCoverDiscovery().import_cover_directory(
            directory,
            tmp_path / "session",
            frozenset(),
            1000,
            _Progress(),
        )


def test_cover_directory_import_removes_batch_previews_when_cancelled(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "covers"
    _write_image(directory / "a.png")
    preview_root = tmp_path / "session" / "shared-previews"

    with pytest.raises(TaskCancelled):
        LocalCoverDiscovery().import_cover_directory(
            directory,
            tmp_path / "session",
            frozenset(),
            1000,
            _CancelOnFirstReport(),
        )

    assert not list(preview_root.glob("*.webp"))


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
