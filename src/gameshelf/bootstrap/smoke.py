"""Structured startup diagnostics used by source and frozen release smoke tests."""

from __future__ import annotations

import json
import os
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True)
class SmokeReport:
    """Stable machine-readable result for a GameShelf startup probe."""

    schema_version: int
    ok: bool
    app_version: str
    frozen: bool
    executable: Path
    runtime_mode: str
    resource_root: Path | None
    webview_runtime: Path | None
    checks: dict[str, bool]
    error: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": self.schema_version,
            "ok": self.ok,
            "appVersion": self.app_version,
            "frozen": self.frozen,
            "executable": str(self.executable),
            "runtimeMode": self.runtime_mode,
            "resourceRoot": (
                None if self.resource_root is None else str(self.resource_root)
            ),
            "webviewRuntime": (
                None if self.webview_runtime is None else str(self.webview_runtime)
            ),
            "checks": dict(self.checks),
            "error": self.error,
        }


def write_smoke_report(report: SmokeReport, output: Path) -> None:
    """Atomically write one UTF-8 JSON report to an absolute path."""

    if not output.is_absolute():
        raise ValueError("smoke JSON 输出必须使用绝对路径。")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(report.as_dict(), stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    finally:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)
