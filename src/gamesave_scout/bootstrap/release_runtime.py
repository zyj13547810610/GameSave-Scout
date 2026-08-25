"""Parse the frozen release manifest into an immutable runtime selection."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

_MANIFEST_NAME = "release-manifest.json"
_BOOTSTRAPPER_RELATIVE_PATH = (
    Path("prerequisites") / "MicrosoftEdgeWebview2Setup.exe"
)
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class RuntimeMode(StrEnum):
    """Supported source and frozen WebView2 runtime modes."""

    SOURCE = "source"
    FIXED = "fixed"
    EVERGREEN = "evergreen"


class ReleaseRuntimeError(RuntimeError):
    """Raised when a frozen release manifest cannot select a safe runtime."""


@dataclass(frozen=True)
class ReleaseRuntimeConfig:
    """Runtime choice derived solely from the frozen release manifest."""

    mode: RuntimeMode
    bootstrapper_path: Path | None = None
    bootstrapper_sha256: str | None = None

    @classmethod
    def for_runtime(
        cls,
        app_root: Path,
        *,
        frozen: bool | None = None,
    ) -> ReleaseRuntimeConfig:
        is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
        if not is_frozen:
            return cls(RuntimeMode.SOURCE)
        manifest = _read_manifest(Path(app_root) / _MANIFEST_NAME)
        return _parse_runtime_config(Path(app_root), manifest)


def _read_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ReleaseRuntimeError(f"冻结版发布清单不存在：{path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseRuntimeError(f"无法读取发布清单 JSON：{path}") from exc
    if not isinstance(payload, dict):
        raise ReleaseRuntimeError("发布清单 JSON 顶层必须是对象。")
    return payload


def _parse_runtime_config(
    app_root: Path,
    manifest: dict[str, Any],
) -> ReleaseRuntimeConfig:
    if manifest.get("formatVersion") != 2:
        raise ReleaseRuntimeError("发布清单 formatVersion 必须为整数 2。")

    raw_mode = manifest.get("runtimeMode")
    if not isinstance(raw_mode, str):
        raise ReleaseRuntimeError(f"发布清单 runtimeMode 无效：{raw_mode!r}")
    try:
        mode = RuntimeMode(raw_mode)
    except ValueError as exc:
        raise ReleaseRuntimeError(f"发布清单 runtimeMode 无效：{raw_mode!r}") from exc
    if mode is RuntimeMode.SOURCE:
        raise ReleaseRuntimeError("冻结版发布清单 runtimeMode 不能为 source。")

    fixed_runtime = manifest.get("fixedRuntime")
    expected_fixed_runtime = mode is RuntimeMode.FIXED
    if fixed_runtime is not expected_fixed_runtime:
        raise ReleaseRuntimeError(
            "发布清单 fixedRuntime 与 runtimeMode 不一致。"
        )

    if mode is RuntimeMode.FIXED:
        return ReleaseRuntimeConfig(RuntimeMode.FIXED)

    digest = manifest.get("webview2BootstrapperSha256")
    if not isinstance(digest, str) or _SHA256_PATTERN.fullmatch(digest) is None:
        raise ReleaseRuntimeError(
            "Evergreen 发布清单缺少有效的 Bootstrapper SHA-256。"
        )
    return ReleaseRuntimeConfig(
        mode=RuntimeMode.EVERGREEN,
        bootstrapper_path=app_root / _BOOTSTRAPPER_RELATIVE_PATH,
        bootstrapper_sha256=digest,
    )
