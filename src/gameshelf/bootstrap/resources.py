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
    builtin_engine_rules_file: Path
    builtin_save_rules_file: Path
    rule_schemas_dir: Path
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
        rules_dir = root / "rules"
        return cls(
            root=root,
            ui_dir=root / "ui",
            builtin_engine_rules_file=rules_dir / "builtin" / "engines.yaml",
            builtin_save_rules_file=rules_dir / "builtin" / "saves.yaml",
            rule_schemas_dir=rules_dir / "schemas",
            ludusavi_dir=rules_dir / "ludusavi",
        )

    def status(self) -> ResourceStatus:
        required = {
            "ui/index.html": self.ui_dir / "index.html",
            "rules/builtin/engines.yaml": self.builtin_engine_rules_file,
            "rules/builtin/saves.yaml": self.builtin_save_rules_file,
            "rules/schemas/engines.schema.json": (
                self.rule_schemas_dir / "engines.schema.json"
            ),
            "rules/schemas/saves.schema.json": (
                self.rule_schemas_dir / "saves.schema.json"
            ),
            "rules/schemas/README.md": self.rule_schemas_dir / "README.md",
            "rules/ludusavi/manifest.yaml": self.ludusavi_dir / "manifest.yaml",
            "rules/ludusavi/manifest-meta.json": (
                self.ludusavi_dir / "manifest-meta.json"
            ),
            "rules/ludusavi/manifest-index.sqlite": (
                self.ludusavi_dir / "manifest-index.sqlite"
            ),
            "rules/ludusavi/LICENSE": self.ludusavi_dir / "LICENSE",
        }
        return ResourceStatus(
            missing=tuple(
                relative_path
                for relative_path, path in required.items()
                if not path.is_file()
            )
        )
