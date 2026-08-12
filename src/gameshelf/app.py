"""GameShelf command-line and desktop entry point."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from gameshelf.bootstrap.application import Application, build_application
from gameshelf.bootstrap.paths import AppPaths


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gameshelf")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--app-root", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    paths = AppPaths.from_root(args.app_root) if args.app_root else AppPaths.for_runtime()
    application = build_application(paths)
    if args.smoke_test:
        try:
            print(f"GameShelf bootstrap OK (schema {application.schema_version})")
            return 0
        finally:
            application.close()
    return _run_desktop(application)


def _run_desktop(application: Application) -> int:
    import webview

    ui_path = application.paths.app_root / "resources" / "ui" / "index.html"
    dev_url = os.environ.get("GAMESHELF_DEV_SERVER_URL")
    is_frozen = bool(getattr(sys, "frozen", False))
    url = dev_url if dev_url and not is_frozen else str(ui_path)
    window = webview.create_window(
        "GameShelf",
        url,
        js_api=application.api,
        width=1180,
        height=760,
        min_size=(960, 640),
    )
    if window is None:
        application.close()
        raise RuntimeError("无法创建 GameShelf 桌面窗口。")
    application.api.attach_window(window)
    window.events.closed += application.close
    try:
        webview.start(
            debug=False,
            private_mode=False,
            storage_path=str(application.paths.webview_dir),
        )
    finally:
        application.close()
    return 0
