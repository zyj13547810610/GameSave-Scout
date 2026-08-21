from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

import gameshelf.app as app_module
from gameshelf.app import main
from gameshelf.bootstrap.webview_bootstrapper import (
    WebViewBootstrapperError,
    WebViewInstallCancelled,
    WebViewManualInstallRequired,
)
from gameshelf.bootstrap.webview_runtime import WebViewRuntime


class RecordingReporter:
    def __init__(self) -> None:
        self.calls: list[tuple[BaseException, Path]] = []

    def show(self, error: BaseException, logs_dir: Path) -> Path | None:
        self.calls.append((error, logs_dir))
        return None


def test_json_smoke_writes_success_without_creating_desktop_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "reports" / "smoke.json"
    app_root = tmp_path / "GameShelf"
    reporter = RecordingReporter()

    def unexpected_window(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("JSON smoke must not create a desktop window")

    monkeypatch.delattr(sys, "frozen", raising=False)
    real_import = app_module.import_module

    def import_without_desktop_window(
        module_name: str,
        package: str | None = None,
    ) -> ModuleType:
        if module_name.startswith("webview"):
            return ModuleType(module_name)
        return real_import(module_name, package)

    monkeypatch.setattr(app_module, "import_module", import_without_desktop_window)
    allow_manual_guide_calls: list[bool] = []
    real_ensure_available = WebViewRuntime.ensure_available

    def record_ensure_available(
        runtime: WebViewRuntime,
        *,
        allow_manual_guide: bool,
    ) -> str | None:
        allow_manual_guide_calls.append(allow_manual_guide)
        return real_ensure_available(
            runtime,
            allow_manual_guide=allow_manual_guide,
        )

    monkeypatch.setattr(
        WebViewRuntime,
        "ensure_available",
        record_ensure_available,
    )

    exit_code = main(
        [
            "--smoke-test",
            "--json-output",
            str(output),
            "--app-root",
            str(app_root),
        ],
        reporter=reporter,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["frozen"] is False
    assert payload["runtimeMode"] == "source"
    assert payload["resourceRoot"].endswith("GameShelf\\resources")
    assert payload["webviewRuntime"] is None
    assert payload["checks"] == {
        "resources": True,
        "ui": True,
        "engineRules": True,
        "saveRules": True,
        "ludusavi": True,
        "desktopDependencies": True,
        "webviewRuntime": True,
        "windows10Permissions": True,
        "applicationBootstrap": True,
    }
    assert payload["error"] is None
    assert reporter.calls == []
    assert allow_manual_guide_calls == [False]


@pytest.mark.parametrize(
    ("failed_module", "message"),
    [
        ("webview", "webview native dependency failed"),
        (
            "webview.platforms.edgechromium",
            "pywebview Edge backend dependency failed",
        ),
    ],
)
def test_json_smoke_reports_desktop_dependency_import_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failed_module: str,
    message: str,
) -> None:
    output = tmp_path / "smoke.json"
    real_import = app_module.import_module

    def fail_desktop_dependency(
        module_name: str,
        package: str | None = None,
    ) -> ModuleType:
        if module_name == failed_module:
            raise ImportError(message)
        return real_import(module_name, package)

    monkeypatch.setattr(app_module, "import_module", fail_desktop_dependency)

    exit_code = main(
        [
            "--smoke-test",
            "--json-output",
            str(output),
            "--app-root",
            str(tmp_path / "GameShelf"),
        ]
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code != 0
    assert payload["ok"] is False
    assert payload["checks"]["desktopDependencies"] is False
    assert message in payload["error"]


def test_json_smoke_writes_failure_without_showing_frozen_dialog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_root = tmp_path / "_internal"
    bundle_root.mkdir()
    output = tmp_path / "smoke.json"
    app_root = tmp_path / "GameShelf"
    reporter = RecordingReporter()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle_root), raising=False)

    exit_code = main(
        [
            "--smoke-test",
            "--json-output",
            str(output),
            "--app-root",
            str(app_root),
        ],
        reporter=reporter,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code != 0
    assert payload["ok"] is False
    assert payload["resourceRoot"] == str(bundle_root / "resources")
    assert payload["checks"] == {
        "resources": False,
        "ui": False,
        "engineRules": False,
        "saveRules": False,
        "ludusavi": False,
    }
    assert "ui/index.html" in payload["error"]
    assert reporter.calls == []
    assert not (app_root / "data").exists()


def test_normal_frozen_startup_failure_uses_reporter_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_root = tmp_path / "_internal"
    bundle_root.mkdir()
    app_root = tmp_path / "GameShelf"
    reporter = RecordingReporter()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle_root), raising=False)

    exit_code = main(
        ["--app-root", str(app_root)],
        reporter=reporter,
    )

    assert exit_code != 0
    assert len(reporter.calls) == 1
    error, logs_dir = reporter.calls[0]
    assert "ui/index.html" in str(error)
    assert logs_dir == app_root / "data" / "logs"


def test_user_cancelled_webview_install_exits_without_error_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle_root = tmp_path / "_internal"
    app_root = tmp_path / "GameShelf"
    _create_required_resources(bundle_root / "resources")
    _write_release_manifest(app_root, mode="evergreen")
    reporter = RecordingReporter()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle_root), raising=False)
    monkeypatch.setattr(app_module, "_validate_desktop_dependencies", lambda: None)
    monkeypatch.setattr(
        WebViewRuntime,
        "ensure_available",
        lambda _self, *, allow_manual_guide: (_ for _ in ()).throw(
            WebViewInstallCancelled
        ),
    )

    exit_code = main(["--app-root", str(app_root)], reporter=reporter)

    assert exit_code == 0
    assert reporter.calls == []
    assert not (app_root / "data" / "logs" / "startup-error.log").exists()


def test_manual_install_location_opened_exits_without_building_application(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle_root = tmp_path / "_internal"
    app_root = tmp_path / "GameShelf"
    _create_required_resources(bundle_root / "resources")
    _write_release_manifest(app_root, mode="evergreen")
    reporter = RecordingReporter()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle_root), raising=False)
    monkeypatch.setattr(app_module, "_validate_desktop_dependencies", lambda: None)
    monkeypatch.setattr(
        WebViewRuntime,
        "ensure_available",
        lambda _self, *, allow_manual_guide: (_ for _ in ()).throw(
            WebViewManualInstallRequired
        ),
    )
    monkeypatch.setattr(
        app_module,
        "build_application",
        lambda *_args, **_kwargs: pytest.fail("application must not build"),
    )

    exit_code = main(["--app-root", str(app_root)], reporter=reporter)

    assert exit_code == 0
    assert reporter.calls == []
    assert not (app_root / "data" / "logs" / "startup-error.log").exists()


def test_evergreen_install_failure_uses_existing_reporter_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle_root = tmp_path / "_internal"
    app_root = tmp_path / "GameShelf"
    _create_required_resources(bundle_root / "resources")
    _write_release_manifest(app_root, mode="evergreen")
    reporter = RecordingReporter()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle_root), raising=False)
    monkeypatch.setattr(app_module, "_validate_desktop_dependencies", lambda: None)
    monkeypatch.setattr(
        WebViewRuntime,
        "ensure_available",
        lambda _self, *, allow_manual_guide: (_ for _ in ()).throw(
            WebViewBootstrapperError("guide failed")
        ),
    )

    exit_code = main(["--app-root", str(app_root)], reporter=reporter)

    assert exit_code == 1
    assert len(reporter.calls) == 1
    assert "guide failed" in str(reporter.calls[0][0])


def test_evergreen_smoke_records_detection_and_bootstrapper_checks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle_root = tmp_path / "_internal"
    app_root = tmp_path / "GameShelf"
    output = tmp_path / "smoke.json"
    _create_required_resources(bundle_root / "resources")
    _write_release_manifest(app_root, mode="evergreen")
    ensure_calls: list[bool] = []
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle_root), raising=False)
    monkeypatch.setattr(app_module, "_validate_desktop_dependencies", lambda: None)
    monkeypatch.setattr(
        WebViewRuntime,
        "ensure_available",
        lambda _self, *, allow_manual_guide: ensure_calls.append(
            allow_manual_guide
        )
        or "151.0.4129.86",
    )
    monkeypatch.setattr(
        app_module,
        "build_application",
        lambda _paths, *, resources: SimpleNamespace(
            schema_version=1,
            close=lambda: None,
        ),
    )

    exit_code = main(
        [
            "--smoke-test",
            "--json-output",
            str(output),
            "--app-root",
            str(app_root),
        ]
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert ensure_calls == [False]
    assert payload["runtimeMode"] == "evergreen"
    assert payload["webviewRuntime"] is None
    assert payload["checks"]["evergreenRuntime"] is True
    assert payload["checks"]["webviewBootstrapper"] is True


def test_normal_source_startup_failure_is_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reporter = RecordingReporter()
    monkeypatch.delattr(sys, "frozen", raising=False)

    def fail_build(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("source startup failed")

    monkeypatch.setattr(app_module, "build_application", fail_build)

    with pytest.raises(RuntimeError, match="source startup failed"):
        main(["--app-root", str(tmp_path / "GameShelf")], reporter=reporter)

    assert reporter.calls == []


def test_python_module_entrypoint_runs_smoke_test(tmp_path: Path) -> None:
    output = tmp_path / "smoke.json"
    app_root = tmp_path / "GameShelf"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "gameshelf.app",
            "--smoke-test",
            "--json-output",
            str(output),
            "--app-root",
            str(app_root),
        ],
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
        shell=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["ok"] is True


def _create_required_resources(resource_root: Path) -> None:
    (resource_root / "ui").mkdir(parents=True)
    (resource_root / "ui" / "index.html").write_text(
        "<!doctype html>",
        encoding="utf-8",
    )
    (resource_root / "rules").mkdir()
    (resource_root / "rules" / "engines.yaml").write_text(
        "version: test\nrules: []\n",
        encoding="utf-8",
    )
    (resource_root / "rules" / "saves.yaml").write_text(
        "version: test\nrules: []\n",
        encoding="utf-8",
    )
    (resource_root / "manifests" / "ludusavi").mkdir(parents=True)


def _write_release_manifest(root: Path, *, mode: str) -> None:
    root.mkdir(parents=True)
    (root / "release-manifest.json").write_text(
        json.dumps(
            {
                "formatVersion": 2,
                "runtimeMode": mode,
                "fixedRuntime": mode == "fixed",
                "webview2BootstrapperSha256": "a" * 64,
            }
        ),
        encoding="utf-8",
    )
