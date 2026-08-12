"""Cover file references stored relative to the portable data directory."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CoverFiles:
    original_relpath: str
    thumb_relpath: str
    revision: int
