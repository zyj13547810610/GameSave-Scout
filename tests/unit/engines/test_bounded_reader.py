from pathlib import Path

import pytest

from gamesave_scout.engines.bounded_reader import (
    BoundedReadError,
    contains_in_edges,
    read_prefix,
    read_suffix,
    read_text_limit,
)


def test_edge_search_reads_only_requested_regions(tmp_path: Path) -> None:
    archive = tmp_path / "archive.bin"
    archive.write_bytes(b"needle" + b"A" * 100_000 + b"tail")

    assert contains_in_edges(archive, b"needle", edge_bytes=4096)
    assert contains_in_edges(archive, b"tail", edge_bytes=4096)
    assert len(read_prefix(archive, 4096)) == 4096
    assert len(read_suffix(archive, 4096)) == 4096


def test_binary_read_limit_is_enforced(tmp_path: Path) -> None:
    path = tmp_path / "file.bin"
    path.write_bytes(b"A" * 100)

    with pytest.raises(BoundedReadError):
        read_prefix(path, 65 * 1024)


def test_text_reader_detects_bom_utf8_and_cp932(tmp_path: Path) -> None:
    utf16 = tmp_path / "utf16.txt"
    utf16.write_text("标题", encoding="utf-16")
    cp932 = tmp_path / "sjis.txt"
    cp932.write_bytes("ゲーム".encode("cp932"))

    assert read_text_limit(utf16) == "标题"
    assert read_text_limit(cp932) == "ゲーム"
