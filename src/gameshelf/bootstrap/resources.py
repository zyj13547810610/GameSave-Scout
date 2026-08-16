"""Resolve bundled read-only resources independently from portable user data."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ResourceStatus:
    """Validation result for resources required before application startup."""

    missing: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.missing


@dataclass(frozen=True)
class ResourcePaths:
    """Immutable locations for bundled GameShelf resources."""

    root: Path
    ui_dir: Path
    engine_rules_file: Path
    ludusavi_dir: Path

    @classmethod
    def for_runtime(
        cls,
        *,
        frozen: bool | None = None,
        bundle_root: Path | None = None,
        source_root: Path | None = None,
    ) -> ResourcePaths:
        is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
        if is_frozen:
            if bundle_root is None:
                meipass = getattr(sys, "_MEIPASS", None)
                if meipass is None:
                    raise RuntimeError("冻结环境缺少 PyInstaller 资源根目录。")
                bundle_root = Path(meipass)
            root = bundle_root.resolve(strict=False) / "resources"
        else:
            repository_root = (
                Path(__file__).resolve().parents[3]
                if source_root is None
                else source_root.resolve(strict=False)
            )
            root = repository_root / "resources"
        return cls(
            root=root,
            ui_dir=root / "ui",
            engine_rules_file=root / "rules" / "engines.yaml",
            ludusavi_dir=root / "manifests" / "ludusavi",
        )

    def status(self) -> ResourceStatus:
        missing: list[str] = []
        if not (self.ui_dir / "index.html").is_file():
            missing.append("ui/index.html")
        if not self.engine_rules_file.is_file():
            missing.append("rules/engines.yaml")
        if not self.ludusavi_dir.is_dir():
            missing.append("manifests/ludusavi")
        return ResourceStatus(missing=tuple(missing))
