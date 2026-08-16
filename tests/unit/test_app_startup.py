from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

import gameshelf.app as app_module
from gameshelf.app import main


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
    assert payload["resourceRoot"].endswith("GameShelf\\resources")
    assert payload["webviewRuntime"] is None
    assert payload["checks"] == {
        "resources": True,
        "ui": True,
        "engineRules": True,
        "ludusavi": True,
        "desktopDependencies": True,
        "webviewRuntime": True,
        "windows10Permissions": True,
        "applicationBootstrap": True,
    }
    assert payload["error"] is None
    assert reporter.calls == []


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
