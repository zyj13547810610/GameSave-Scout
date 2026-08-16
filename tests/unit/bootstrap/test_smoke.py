from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from gameshelf.bootstrap.smoke import SmokeReport, write_smoke_report


def _successful_report() -> SmokeReport:
    return SmokeReport(
        schema_version=1,
        ok=True,
        app_version="0.1.0",
        frozen=True,
        executable=Path(r"C:\GameShelf\GameShelf.exe"),
        resource_root=Path(r"C:\GameShelf\_internal\resources"),
        webview_runtime=Path(r"C:\GameShelf\runtime"),
        checks={"resources": True, "webviewRuntime": True},
        error=None,
    )


def test_smoke_report_exposes_stable_json_contract() -> None:
    report = _successful_report()

    assert report.as_dict() == {
        "schemaVersion": 1,
        "ok": True,
        "appVersion": "0.1.0",
        "frozen": True,
        "executable": r"C:\GameShelf\GameShelf.exe",
        "resourceRoot": r"C:\GameShelf\_internal\resources",
        "webviewRuntime": r"C:\GameShelf\runtime",
        "checks": {"resources": True, "webviewRuntime": True},
        "error": None,
    }


def test_write_smoke_report_writes_utf8_json_atomically(tmp_path: Path) -> None:
    output = tmp_path / "诊断" / "smoke.json"

    write_smoke_report(_successful_report(), output)

    payload = json.loads(output.read_bytes().decode("utf-8"))
    assert payload["ok"] is True
    assert payload["appVersion"] == "0.1.0"
    assert list(output.parent.iterdir()) == [output]


def test_write_smoke_report_preserves_old_file_when_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "smoke.json"
    output.write_text("old report", encoding="utf-8")

    def fail_replace(_source: Path, _destination: Path) -> None:
        raise PermissionError("replace denied")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(PermissionError, match="replace denied"):
        write_smoke_report(_successful_report(), output)

    assert output.read_text(encoding="utf-8") == "old report"
    assert list(tmp_path.iterdir()) == [output]


def test_write_smoke_report_rejects_relative_output_path() -> None:
    with pytest.raises(ValueError, match="绝对路径"):
        write_smoke_report(_successful_report(), Path("smoke.json"))
