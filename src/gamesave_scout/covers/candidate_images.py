"""Validate candidate images and produce bounded temporary previews."""

from __future__ import annotations

import hashlib
import os
from contextlib import suppress
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from gamesave_scout.covers.candidates import CandidateFileRef
from gamesave_scout.covers.image_pipeline import (
    MAX_PIXELS,
    MAX_SIDE,
    MAX_SOURCE_BYTES,
    InvalidCoverImage,
)

PREVIEW_MAX_SIZE = (480, 720)
_SUPPORTED_FORMATS = {"PNG", "JPEG", "WEBP", "BMP"}


@dataclass(frozen=True)
class StagedCandidateImage:
    file_ref: CandidateFileRef
    preview_path: Path
    width: int
    height: int
    sha256: str


def stage_candidate_file(source: Path, preview: Path) -> StagedCandidateImage:
    """Read an external image without changing or copying the source."""
    payload = _read_bounded(source)
    return _stage_payload(payload, source, preview, temporary=False)


def stage_candidate_bytes(
    payload: bytes, source: Path, preview: Path
) -> StagedCandidateImage:
    """Atomically persist a temporary source before validating its preview."""
    if len(payload) > MAX_SOURCE_BYTES:
        raise InvalidCoverImage("Cover image exceeds the 50 MiB limit.")
    source.parent.mkdir(parents=True, exist_ok=True)
    temporary = source.with_name(f".{source.name}.part")
    try:
        with temporary.open("wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, source)
        return _stage_payload(payload, source, preview, temporary=True)
    except Exception:
        with suppress(OSError):
            source.unlink(missing_ok=True)
        with suppress(OSError):
            preview.unlink(missing_ok=True)
        raise
    finally:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)


def _read_bounded(source: Path) -> bytes:
    try:
        with source.open("rb") as stream:
            payload = stream.read(MAX_SOURCE_BYTES + 1)
    except OSError as error:
        raise InvalidCoverImage(f"Cannot read cover source: {source}") from error
    if len(payload) > MAX_SOURCE_BYTES:
        raise InvalidCoverImage("Cover image exceeds the 50 MiB limit.")
    return payload


def _stage_payload(
    payload: bytes, source: Path, preview: Path, *, temporary: bool
) -> StagedCandidateImage:
    digest = hashlib.sha256(payload).hexdigest()
    try:
        with Image.open(BytesIO(payload)) as image:
            image_format = (image.format or "").upper()
            if image_format not in _SUPPORTED_FORMATS:
                raise InvalidCoverImage(
                    f"Unsupported cover format: {image_format or 'unknown'}"
                )
            _validate_dimensions(image)
            image.verify()

        with Image.open(BytesIO(payload)) as decoded:
            _validate_dimensions(decoded)
            width, height = decoded.size
            decoded.load()
            rendered = ImageOps.exif_transpose(decoded)
            rendered = _normalized_mode(rendered)
            rendered.thumbnail(PREVIEW_MAX_SIZE, Image.Resampling.LANCZOS)
            _atomic_preview_save(rendered, preview)
    except InvalidCoverImage:
        raise
    except (
        OSError,
        SyntaxError,
        ValueError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
    ) as error:
        raise InvalidCoverImage("Cover image is damaged or unsupported.") from error

    return StagedCandidateImage(
        file_ref=CandidateFileRef(source, temporary, digest),
        preview_path=preview,
        width=width,
        height=height,
        sha256=digest,
    )


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


def _atomic_preview_save(image: Image.Image, preview: Path) -> None:
    preview.parent.mkdir(parents=True, exist_ok=True)
    temporary = preview.with_name(f".{preview.name}.part")
    try:
        with temporary.open("wb") as stream:
            image.save(stream, format="WEBP", quality=86, method=6)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, preview)
    finally:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)
