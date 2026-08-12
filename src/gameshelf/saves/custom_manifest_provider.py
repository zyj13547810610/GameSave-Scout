"""Load user-supplied Ludusavi-compatible manifests independently."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from gameshelf.saves.ludusavi_models import LudusaviManifest
from gameshelf.saves.ludusavi_parser import InvalidLudusaviManifest, parse_manifest

MAX_CUSTOM_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_CUSTOM_MANIFEST_FILES = 100


@dataclass(frozen=True, slots=True)
class LoadedCustomManifest:
    source_name: str
    manifest: LudusaviManifest


@dataclass(frozen=True, slots=True)
class CustomManifestError:
    source_name: str
    message: str


@dataclass(frozen=True, slots=True)
class CustomManifestLoadResult:
    manifests: tuple[LoadedCustomManifest, ...]
    errors: tuple[CustomManifestError, ...]


class CustomManifestProvider:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def load_all(self) -> CustomManifestLoadResult:
        self.directory.mkdir(parents=True, exist_ok=True)
        candidates = sorted(
            (
                path
                for path in self.directory.iterdir()
                if path.is_file() and path.suffix.casefold() in {".yaml", ".yml"}
            ),
            key=lambda path: path.name.casefold(),
        )
        manifests: list[LoadedCustomManifest] = []
        errors: list[CustomManifestError] = []
        if len(candidates) > MAX_CUSTOM_MANIFEST_FILES:
            errors.append(
                CustomManifestError(
                    "<目录>",
                    f"自定义清单最多允许 {MAX_CUSTOM_MANIFEST_FILES} 个文件。",
                )
            )
            candidates = candidates[:MAX_CUSTOM_MANIFEST_FILES]

        for path in candidates:
            try:
                if path.stat().st_size > MAX_CUSTOM_MANIFEST_BYTES:
                    raise InvalidLudusaviManifest("单个自定义清单不能超过 8 MiB。")
                with path.open(encoding="utf-8") as stream:
                    manifest = parse_manifest(stream)
            except (OSError, UnicodeError, InvalidLudusaviManifest) as error:
                errors.append(CustomManifestError(path.name, str(error)))
                continue
            manifests.append(LoadedCustomManifest(path.name, manifest))
        return CustomManifestLoadResult(tuple(manifests), tuple(errors))

