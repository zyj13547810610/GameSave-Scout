from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from gamesave_scout.covers import candidate_images
from gamesave_scout.covers.candidate_images import (
    PREVIEW_MAX_SIZE,
    stage_candidate_bytes,
    stage_candidate_file,
)
from gamesave_scout.covers.image_pipeline import InvalidCoverImage


def _image_bytes(image_format: str, size: tuple[int, int] = (120, 180)) -> bytes:
    stream = BytesIO()
    Image.new("RGB", size, (40, 80, 120)).save(stream, format=image_format)
    return stream.getvalue()


@pytest.mark.parametrize(
    ("image_format", "suffix"),
    [("PNG", ".png"), ("JPEG", ".jpg"), ("WEBP", ".webp"), ("BMP", ".bmp")],
)
def test_stage_external_candidate_validates_formats_without_mutating_source(
    tmp_path: Path, image_format: str, suffix: str
) -> None:
    source = tmp_path / f"source{suffix}"
    payload = _image_bytes(image_format, (900, 1200))
    source.write_bytes(payload)
    preview = tmp_path / "preview.webp"

    staged = stage_candidate_file(source, preview)

    assert source.read_bytes() == payload
    assert staged.file_ref.path == source
    assert staged.file_ref.temporary is False
    assert staged.file_ref.expected_sha256 == hashlib.sha256(payload).hexdigest()
    assert staged.width == 900
    assert staged.height == 1200
    assert staged.sha256 == staged.file_ref.expected_sha256
    assert staged.preview_path == preview
    with Image.open(preview) as image:
        assert image.format == "WEBP"
        assert image.width <= PREVIEW_MAX_SIZE[0]
        assert image.height <= PREVIEW_MAX_SIZE[1]


def test_stage_candidate_bytes_atomically_persists_temporary_source(tmp_path: Path) -> None:
    payload = _image_bytes("PNG")
    source = tmp_path / "sources" / "candidate.png"
    preview = tmp_path / "previews" / "candidate.webp"

    staged = stage_candidate_bytes(payload, source, preview)

    assert source.read_bytes() == payload
    assert staged.file_ref.temporary is True
    assert staged.file_ref.path == source
    assert not tuple(tmp_path.rglob("*.part"))


def test_damaged_external_image_leaves_source_but_no_preview(tmp_path: Path) -> None:
    source = tmp_path / "damaged.png"
    source.write_bytes(b"not an image")
    preview = tmp_path / "preview.webp"

    with pytest.raises(InvalidCoverImage):
        stage_candidate_file(source, preview)

    assert source.exists()
    assert not preview.exists()
    assert not tuple(tmp_path.rglob("*.part"))


def test_oversized_bytes_remove_temporary_source_and_parts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(candidate_images, "MAX_SOURCE_BYTES", 16)
    source = tmp_path / "source.bin"
    preview = tmp_path / "preview.webp"

    with pytest.raises(InvalidCoverImage, match="50 MiB"):
        stage_candidate_bytes(b"x" * 17, source, preview)

    assert not source.exists()
    assert not preview.exists()
    assert not tuple(tmp_path.rglob("*.part"))


@pytest.mark.parametrize(
    ("limit_name", "limit_value", "size", "message"),
    [
        ("MAX_SIDE", 10, (11, 1), "16,384"),
        ("MAX_PIXELS", 100, (11, 10), "64 million"),
    ],
)
def test_dimension_boundaries_are_enforced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    limit_name: str,
    limit_value: int,
    size: tuple[int, int],
    message: str,
) -> None:
    monkeypatch.setattr(candidate_images, limit_name, limit_value)
    source = tmp_path / "source.png"
    source.write_bytes(_image_bytes("PNG", size))

    with pytest.raises(InvalidCoverImage, match=message):
        stage_candidate_file(source, tmp_path / "preview.webp")
