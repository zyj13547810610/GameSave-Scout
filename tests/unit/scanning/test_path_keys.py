from pathlib import Path

import pytest

from gameshelf.scanning.path_keys import (
    PathTraversalError,
    expand_relative,
    is_same_or_child,
    portable_relative,
    windows_path_key,
)


def test_windows_keys_dedupe_case_prefix_slashes_and_trailing_marks() -> None:
    assert windows_path_key("\\\\?\\D:\\Games\\Alice\\.\\") == windows_path_key(
        "d:/games/Alice"
    )
    assert windows_path_key("D:\\Games\\Alice. ") == windows_path_key(
        "d:\\games\\alice"
    )


def test_windows_key_preserves_unc_share_boundary() -> None:
    key = windows_path_key("\\\\?\\UNC\\Server\\Share\\Games\\Alice")

    assert key == "\\\\server\\share\\games\\alice"


def test_child_check_respects_component_boundary() -> None:
    root = windows_path_key("D:\\Games")

    assert is_same_or_child(windows_path_key("D:\\Games\\A"), root)
    assert not is_same_or_child(windows_path_key("D:\\GamesBackup\\A"), root)


def test_relative_paths_are_portable_and_cannot_escape(tmp_path: Path) -> None:
    root = tmp_path / "games"

    assert portable_relative(root / "group" / "game", root) == "group/game"
    with pytest.raises(PathTraversalError):
        expand_relative(root, "../outside")


@pytest.mark.parametrize("relative", ["C:/outside", "\\\\server\\share", "/absolute"])
def test_expand_relative_rejects_absolute_or_drive_paths(
    tmp_path: Path, relative: str
) -> None:
    with pytest.raises(PathTraversalError):
        expand_relative(tmp_path, relative)
