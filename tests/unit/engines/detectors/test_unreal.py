from pathlib import Path

import pytest

from gamesave_scout.engines.base import DetectionContext
from gamesave_scout.engines.detectors.unreal import UnrealDetector
from gamesave_scout.scanning.pe_metadata import PeMetadata


def test_detects_unreal_bootstrap_with_runtime_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = _unreal_layout(tmp_path) / "Sample.exe"
    executable.write_bytes(b"MZ")
    monkeypatch.setattr(
        "gamesave_scout.engines.detectors.unreal.read_pe_metadata",
        lambda _: PeMetadata("BootstrapPackagedGame", "", "Epic Games", "x64"),
    )

    match = UnrealDetector().inspect(DetectionContext(tmp_path, executable))

    assert match is not None
    assert match.engine_id == "unreal"
    assert {item.code for item in match.evidence} == {
        "unreal_runtime_layout",
        "unreal_bootstrap",
    }


def test_detects_unreal_shipping_binary(tmp_path: Path) -> None:
    root = _unreal_layout(tmp_path)
    executable = root / "Sample" / "Binaries" / "Win64" / "Sample-Win64-Shipping.exe"
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_bytes(b"MZ")

    match = UnrealDetector().inspect(DetectionContext(tmp_path, executable))

    assert match is not None
    assert match.engine_id == "unreal"
    assert {item.code for item in match.evidence} == {
        "unreal_runtime_layout",
        "unreal_shipping",
    }


def test_rejects_unreal_internal_helper_as_entry(tmp_path: Path) -> None:
    root = _unreal_layout(tmp_path)
    helper = root / "Engine" / "Binaries" / "Win64" / "UnrealCEFSubProcess.exe"
    helper.parent.mkdir(parents=True, exist_ok=True)
    helper.write_bytes(b"MZ")

    assert UnrealDetector().inspect(DetectionContext(tmp_path, helper)) is None


def test_unreal_layout_without_supported_entry_remains_unknown(tmp_path: Path) -> None:
    root = _unreal_layout(tmp_path)
    tool = root / "Tool.exe"
    tool.write_bytes(b"MZ")

    assert UnrealDetector().inspect(DetectionContext(tmp_path, tool)) is None


def _unreal_layout(game_dir: Path) -> Path:
    root = game_dir / "Runtime"
    (root / "Engine" / "Binaries").mkdir(parents=True)
    (root / "Sample" / "Binaries").mkdir(parents=True)
    return root
