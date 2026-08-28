from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from gamesave_scout.covers.image_pipeline import InvalidCoverImage, normalize_cover


def test_pipeline_keeps_full_image_and_creates_centered_two_by_three_thumb(
    tmp_path: Path,
) -> None:
    source = BytesIO()
    Image.new("RGB", (1200, 600), "#ac5577").save(source, format="PNG")
    source.seek(0)

    result = normalize_cover(
        source,
        "image/png",
        tmp_path / "game-id",
        optimize=False,
    )

    with Image.open(tmp_path / result.original_relpath) as original:
        assert original.size == (1200, 600)
    with Image.open(tmp_path / result.thumb_relpath) as thumb:
        assert thumb.size == (400, 600)
        assert thumb.format == "WEBP"


def test_pipeline_preserves_png_alpha(tmp_path: Path) -> None:
    source = BytesIO()
    Image.new("RGBA", (20, 30), (255, 0, 0, 80)).save(source, format="PNG")
    source.seek(0)

    result = normalize_cover(source, "image/png", tmp_path / "alpha", optimize=True)

    with Image.open(tmp_path / result.original_relpath) as original:
        assert original.mode == "RGBA"
        assert original.format == "PNG"


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        ((3840, 2160), (1920, 1080)),
        ((2160, 3840), (1080, 1920)),
        ((800, 600), (800, 600)),
    ],
)
def test_optimized_cover_limits_the_longest_side_without_upscaling(
    tmp_path: Path,
    size: tuple[int, int],
    expected: tuple[int, int],
) -> None:
    source = BytesIO()
    Image.new("RGB", size, "#336699").save(source, format="PNG")
    source.seek(0)

    result = normalize_cover(
        source,
        "image/png",
        tmp_path / f"optimized-{size[0]}",
        optimize=True,
    )

    with Image.open(tmp_path / result.original_relpath) as original:
        assert original.size == expected
        assert original.format == "JPEG"
    with Image.open(tmp_path / result.thumb_relpath) as thumb:
        assert thumb.size == (400, 600)
        assert thumb.format == "WEBP"


def test_disabled_optimization_preserves_large_png_dimensions_and_format(
    tmp_path: Path,
) -> None:
    source = BytesIO()
    Image.new("RGB", (2560, 1440), "#445566").save(source, format="PNG")
    source.seek(0)

    result = normalize_cover(
        source,
        "image/png",
        tmp_path / "preserved",
        optimize=False,
    )

    with Image.open(tmp_path / result.original_relpath) as original:
        assert original.size == (2560, 1440)
        assert original.format == "PNG"


@pytest.mark.parametrize("payload", [b"not-an-image", b"GIF89a"])
def test_pipeline_rejects_corrupt_or_unsupported_bytes(
    tmp_path: Path, payload: bytes
) -> None:
    with pytest.raises(InvalidCoverImage):
        normalize_cover(
            BytesIO(payload),
            "image/png",
            tmp_path / "bad",
            optimize=True,
        )


def test_pipeline_rejects_images_over_pixel_limit(tmp_path: Path, monkeypatch) -> None:
    source = BytesIO()
    Image.new("RGB", (100, 100), "black").save(source, format="PNG")
    source.seek(0)
    monkeypatch.setattr("gamesave_scout.covers.image_pipeline.MAX_PIXELS", 9_999)

    with pytest.raises(InvalidCoverImage, match="pixel"):
        normalize_cover(
            source,
            "image/png",
            tmp_path / "too-large",
            optimize=True,
        )
