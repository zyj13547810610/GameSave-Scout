from __future__ import annotations

import pytest

from gameshelf.library.title_parser import split_title_and_version


@pytest.mark.parametrize(
    ("raw_name", "expected"),
    [
        ("AoiChan.v1.0.8", ("AoiChan", "v1.0.8")),
        ("Game Name - Ver 1.42", ("Game Name", "Ver 1.42")),
        ("作品名（version 2.0）", ("作品名", "version 2.0")),
        ("Title_build_1234", ("Title", "build_1234")),
        ("アメリア Ver1.2", ("アメリア", "Ver1.2")),
    ],
)
def test_splits_only_explicit_version_suffixes(
    raw_name: str,
    expected: tuple[str, str | None],
) -> None:
    assert split_title_and_version(raw_name) == expected


@pytest.mark.parametrize(
    "raw_name",
    [
        "Need for Speed 21 Heat",
        "Resident Evil 4",
        "Game 1.05",
        "Game DLC",
        "Game PC",
        "Game x64",
        "Final",
    ],
)
def test_keeps_ambiguous_suffixes_in_title(raw_name: str) -> None:
    assert split_title_and_version(raw_name) == (raw_name, None)


def test_strips_outer_whitespace_without_changing_version_format() -> None:
    assert split_title_and_version("  Game Name - Ver 1.42  ") == (
        "Game Name",
        "Ver 1.42",
    )


@pytest.mark.parametrize("raw_name", ["v1.0", " Ver 2.0 ", "build_1234"])
def test_keeps_version_only_text_as_title(raw_name: str) -> None:
    expected = raw_name.strip()
    assert split_title_and_version(raw_name) == (expected, None)
