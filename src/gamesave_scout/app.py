"""GameSave Scout command-line and desktop entry point."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from importlib import import_module
from pathlib import Path
from typing import Any, Protocol

from gamesave_scout import __version__
from gamesave_scout.bootstrap.application import Application, build_application
from gamesave_scout.bootstrap.paths import AppPaths
from gamesave_scout.bootstrap.release_runtime import ReleaseRuntimeConfig, RuntimeMode
from gamesave_scout.bootstrap.resources import ResourcePaths
from gamesave_scout.bootstrap.smoke import SmokeReport, write_smoke_report
from gamesave_scout.bootstrap.webview_bootstrapper import (
    WebViewInstallCancelled,
    WebViewManualInstallRequired,
)
from gamesave_scout.bootstrap.webview_runtime import WebViewRuntime
from gamesave_scout.bootstrap.window_size import (
    fit_window_to_primary_work_area,
    read_restored_window_size,
)
from gamesave_scout.db.migrator import LATEST_SCHEMA_VERSION
from gamesave_scout.platform.windows.startup_reporter import FrozenStartupReporter


class StartupReporter(Protocol):
    def show(self, error: BaseException, logs_dir: Path) -> Path | None: ...


def main(
    argv: Sequence[str] | None = None,
    *,
    reporter: StartupReporter | None = None,
) -> int:
    parser = argparse.ArgumentParser(prog="gamesave-scout")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--app-root", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.json_output is not None and not args.smoke_test:
        parser.error("--json-output 只能与 --smoke-test 一起使用。")
    if args.json_output is not None and not args.json_output.is_absolute():
        parser.error("--json-output 必须使用绝对路径。")

    is_frozen = bool(getattr(sys, "frozen", False))
    paths = AppPaths.from_root(args.app_root) if args.app_root else AppPaths.for_runtime()
    resources: ResourcePaths | None = None
    release_config: ReleaseRuntimeConfig | None = None
    webview_runtime: WebViewRuntime | None = None
    application: Application | None = None
    checks: dict[str, bool] = {}
    runtime_mode = RuntimeMode.SOURCE.value if not is_frozen else "unknown"
    try:
        resources = ResourcePaths.for_runtime()
        resource_status = resources.status()
        missing_resources = set(resource_status.missing)
        checks.update(
            {
                "resources": resource_status.ok,
                "ui": "ui/index.html" not in missing_resources,
                "engineRules": (
                    "rules/builtin/engines.yaml" not in missing_resources
                ),
                "saveRules": (
                    "rules/builtin/saves.yaml" not in missing_resources
                ),
                "builtinRules": all(
                    path not in missing_resources
                    for path in (
                        "rules/builtin/engines.yaml",
                        "rules/builtin/saves.yaml",
                    )
                ),
                "ruleSchemas": all(
                    path not in missing_resources
                    for path in (
                        "rules/schemas/engines.schema.json",
                        "rules/schemas/saves.schema.json",
                        "rules/schemas/README.md",
                    )
                ),
                "ludusavi": all(
                    path not in missing_resources
                    for path in (
                        "rules/ludusavi/manifest.yaml",
                        "rules/ludusavi/manifest-meta.json",
                        "rules/ludusavi/manifest-index.sqlite",
                    )
                ),
                "ludusaviLicense": (
                    "rules/ludusavi/LICENSE" not in missing_resources
                ),
            }
        )
        if not resource_status.ok:
            missing = ", ".join(resource_status.missing)
            raise RuntimeError(f"GameSave Scout 资源不完整：{missing}")
        checks["desktopDependencies"] = False
        _validate_desktop_dependencies()
        checks["desktopDependencies"] = True
        release_config = ReleaseRuntimeConfig.for_runtime(paths.app_root)
        runtime_mode = release_config.mode.value
        webview_runtime = WebViewRuntime.for_runtime(
            paths.app_root,
            release_config=release_config,
        )
        if release_config.mode is RuntimeMode.EVERGREEN:
            checks["evergreenRuntime"] = False
            if args.smoke_test:
                checks["webviewBootstrapper"] = False
        checks["webviewRuntime"] = False
        runtime_version = webview_runtime.ensure_available(
            allow_manual_guide=not args.smoke_test
        )
        checks["webviewRuntime"] = True
        if release_config.mode is RuntimeMode.EVERGREEN:
            checks["evergreenRuntime"] = runtime_version is not None
            if args.smoke_test:
                checks["webviewBootstrapper"] = True
        webview_runtime.prepare_windows10_permissions()
        checks["windows10Permissions"] = True
        application = build_application(paths, resources=resources)
        checks["applicationBootstrap"] = True
        checks["ruleCatalog"] = bool(
            application.rule_catalog.snapshot().catalog_version
        )
        if args.smoke_test:
            schema_version = application.schema_version
            application.close()
            application = None
            if args.json_output is not None:
                write_smoke_report(
                    _smoke_report(
                        ok=True,
                        frozen=is_frozen,
                        runtime_mode=runtime_mode,
                        resources=resources,
                        webview_runtime=webview_runtime,
                        checks=checks,
                    ),
                    args.json_output,
                )
            else:
                print(f"GameSave Scout bootstrap OK (schema {schema_version})")
            return 0
        return _run_desktop(application, webview_runtime)
    except (WebViewInstallCancelled, WebViewManualInstallRequired):
        if application is not None:
            application.close()
        return 0
    except Exception as error:
        if application is not None:
            application.close()
        if args.smoke_test and args.json_output is not None:
            write_smoke_report(
                _smoke_report(
                    ok=False,
                    frozen=is_frozen,
                    runtime_mode=runtime_mode,
                    resources=resources,
                    webview_runtime=webview_runtime,
                    checks=checks,
                    error=error,
                ),
                args.json_output,
            )
            return 1
        if is_frozen:
            active_reporter = reporter if reporter is not None else FrozenStartupReporter()
            active_reporter.show(error, paths.logs_dir)
            return 1
        raise


def _smoke_report(
    *,
    ok: bool,
    frozen: bool,
    runtime_mode: str,
    resources: ResourcePaths | None,
    webview_runtime: WebViewRuntime | None,
    checks: dict[str, bool],
    error: BaseException | None = None,
) -> SmokeReport:
    return SmokeReport(
        schema_version=LATEST_SCHEMA_VERSION,
        ok=ok,
        app_version=__version__,
        frozen=frozen,
        executable=Path(sys.executable),
        runtime_mode=runtime_mode,
        resource_root=None if resources is None else resources.root,
        webview_runtime=(
            None if webview_runtime is None else webview_runtime.path
        ),
        checks=dict(checks),
        error=None if error is None else str(error),
    )


def _validate_desktop_dependencies() -> None:
    for module_name in (
        "ssl",
        "sqlite3",
        "webview",
        "webview.platforms.edgechromium",
    ):
        import_module(module_name)


def _run_desktop(
    application: Application,
    webview_runtime: WebViewRuntime,
    *,
    webview_module: Any | None = None,
) -> int:
    if webview_module is None:
        import webview

        module: Any = webview
    else:
        module = webview_module

    webview_runtime.configure(module)

    dev_url = os.environ.get("GAMESAVE_SCOUT_DEV_SERVER_URL")
    is_frozen = bool(getattr(sys, "frozen", False))
    url = dev_url if dev_url and not is_frozen else application.asset_address.ui_url
    try:
        screens = module.screens
    except Exception:
        screens = ()
    config = application.config.current
    window_size = fit_window_to_primary_work_area(
        config.window_width,
        config.window_height,
        screens,
    )
    window = module.create_window(
        "GameSave Scout",
        url,
        js_api=application.api,
        width=window_size.width,
        height=window_size.height,
        min_size=(960, 640),
    )
    if window is None:
        application.close()
        raise RuntimeError("无法创建 GameSave Scout 桌面窗口。")
    application.api.attach_window(window)
    application.guided_saves.set_exit_callback(window.destroy)
    window.events.closing += lambda: _handle_window_closing(application, window)
    window.events.closed += application.close
    try:
        module.start(
            debug=False,
            private_mode=False,
            storage_path=str(application.paths.webview_dir),
            gui="edgechromium",
        )
    finally:
        application.close()
    return 0


def _allow_window_close(application: Application) -> bool:
    return application.guided_saves.request_close()


def _handle_window_closing(application: Application, window: object) -> bool:
    if not _allow_window_close(application):
        return False
    try:
        size = read_restored_window_size(window)
        application.config.set_window_size(size.width, size.height)
    except Exception:
        application.logger.warning(
            "无法保存窗口尺寸，下次启动将继续使用上次保存的尺寸。",
            exc_info=True,
        )
    return True


if __name__ == "__main__":
    raise SystemExit(main())
