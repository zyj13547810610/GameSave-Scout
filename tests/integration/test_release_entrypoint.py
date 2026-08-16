from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_SCRIPT = REPOSITORY_ROOT / "scripts" / "build_release.ps1"
POWERSHELL = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")


def test_release_entrypoint_rejects_relative_archive_before_cleanup(
    tmp_path: Path,
) -> None:
    repository = _copy_entrypoint(tmp_path)
    build_marker = repository / "build" / "release" / "keep.txt"
    dist_marker = repository / "dist" / "keep.txt"
    build_marker.parent.mkdir(parents=True)
    dist_marker.parent.mkdir()
    build_marker.write_text("keep build", encoding="utf-8")
    dist_marker.write_text("keep dist", encoding="utf-8")

    result = _run_entrypoint(repository, "relative-runtime.cab")

    assert result.returncode != 0
    assert "absolute path" in f"{result.stdout}\n{result.stderr}"
    assert build_marker.read_text(encoding="utf-8") == "keep build"
    assert dist_marker.read_text(encoding="utf-8") == "keep dist"


def test_release_entrypoint_has_no_skip_or_download_bypass_parameters(
    tmp_path: Path,
) -> None:
    repository = _copy_entrypoint(tmp_path)

    for bypass in ("-SkipTests", "-SkipHash", "-Force", "-Download"):
        result = _run_entrypoint(repository, "relative-runtime.cab", bypass)

        assert result.returncode != 0
        assert "parameter" in f"{result.stdout}\n{result.stderr}".casefold()


def test_release_entrypoint_validates_environment_before_mutating_outputs(
    tmp_path: Path,
) -> None:
    repository = _copy_entrypoint(tmp_path)
    archive = repository / "Microsoft.WebView2.FixedVersionRuntime.x64.cab"
    archive.write_bytes(b"not a real cab")
    build_marker = repository / "build" / "release" / "keep.txt"
    dist_marker = repository / "dist" / "keep.txt"
    build_marker.parent.mkdir(parents=True)
    dist_marker.parent.mkdir()
    build_marker.write_text("keep build", encoding="utf-8")
    dist_marker.write_text("keep dist", encoding="utf-8")

    result = _run_entrypoint(repository, str(archive))

    assert result.returncode != 0
    assert build_marker.read_text(encoding="utf-8") == "keep build"
    assert dist_marker.read_text(encoding="utf-8") == "keep dist"


def _copy_entrypoint(tmp_path: Path) -> Path:
    repository = tmp_path / "repository"
    scripts = repository / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(SOURCE_SCRIPT, scripts / SOURCE_SCRIPT.name)
    return repository


def _run_entrypoint(
    repository: Path,
    archive: str,
    *extra: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            str(POWERSHELL),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(repository / "scripts" / "build_release.ps1"),
            "-WebView2Archive",
            archive,
            *extra,
        ],
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
        shell=False,
    )
