"""Bounded image decoding and deterministic cover rendering."""

from __future__ import annotations

import os
from contextlib import suppress
from io import BytesIO
from pathlib import Path
from typing import BinaryIO

from PIL import Image, ImageOps, UnidentifiedImageError

from gameshelf.covers.models import CoverFiles

MAX_SOURCE_BYTES = 50 * 1024 * 1024
MAX_SIDE = 16_384
MAX_PIXELS = 64_000_000
THUMB_SIZE = (400, 600)
_SUPPORTED_FORMATS = {"PNG", "JPEG", "WEBP", "BMP"}


class InvalidCoverImage(ValueError):
    """Raised when an image is unsafe, damaged, or outside V1 format limits."""


def normalize_cover(
    source: BinaryIO, content_type: str, destination_stem: Path
) -> CoverFiles:
    del content_type  # The decoded format, not a caller-controlled MIME value, is authoritative.
    payload = source.read(MAX_SOURCE_BYTES + 1)
    if len(payload) > MAX_SOURCE_BYTES:
        raise InvalidCoverImage("Cover image exceeds the 50 MiB limit.")

    destination_stem.parent.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    try:
        image_format = _verify(payload)
        with Image.open(BytesIO(payload)) as decoded:
            _validate_dimensions(decoded)
            decoded.load()
            normalized = ImageOps.exif_transpose(decoded)
            normalized = _normalized_mode(normalized)
            original_suffix = _original_suffix(image_format)
            original = destination_stem.with_suffix(original_suffix)
            thumb = destination_stem.with_name(f"{destination_stem.name}.thumb.webp")
            _atomic_image_save(normalized, original, image_format)
            created.append(original)
            fitted = ImageOps.fit(
                normalized,
                THUMB_SIZE,
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )
            _atomic_image_save(fitted, thumb, "WEBP")
            created.append(thumb)
        return CoverFiles(original.name, thumb.name, 0)
    except InvalidCoverImage:
        raise
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as error:
        raise InvalidCoverImage("Cover image could not be decoded safely.") from error
    finally:
        if len(created) == 1:
            with suppress(OSError):
                created[0].unlink()


def _verify(payload: bytes) -> str:
    try:
        with Image.open(BytesIO(payload)) as image:
            image_format = (image.format or "").upper()
            if image_format not in _SUPPORTED_FORMATS:
                raise InvalidCoverImage(f"Unsupported cover format: {image_format or 'unknown'}")
            _validate_dimensions(image)
            image.verify()
            return image_format
    except InvalidCoverImage:
        raise
    except (OSError, SyntaxError, UnidentifiedImageError, Image.DecompressionBombError) as error:
        raise InvalidCoverImage("Cover image is damaged or unsupported.") from error


def _validate_dimensions(image: Image.Image) -> None:
    width, height = image.size
    if width <= 0 or height <= 0:
        raise InvalidCoverImage("Cover image has invalid dimensions.")
    if width > MAX_SIDE or height > MAX_SIDE:
        raise InvalidCoverImage("Cover image side exceeds 16,384 pixels.")
    if width * height > MAX_PIXELS:
        raise InvalidCoverImage("Cover image exceeds the 64 million pixel limit.")


def _normalized_mode(image: Image.Image) -> Image.Image:
    if image.mode in {"RGBA", "LA"} or (
        image.mode == "P" and "transparency" in image.info
    ):
        return image.convert("RGBA")
    return image.convert("RGB")


def _original_suffix(image_format: str) -> str:
    return {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}.get(
        image_format, ".png"
    )


def _atomic_image_save(image: Image.Image, destination: Path, image_format: str) -> None:
    temporary = destination.with_name(f".{destination.name}.part")
    options: dict[str, int | bool] = {}
    if image_format == "JPEG":
        options = {"quality": 92, "optimize": True}
    elif image_format == "WEBP":
        quality = 88 if destination.name.endswith(".thumb.webp") else 92
        options = {"quality": quality, "method": 6}
    try:
        with temporary.open("wb") as stream:
            image.save(stream, format=image_format, **options)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)
