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

    result = _run_entrypoint(
        repository,
        "relative-runtime.cab",
        "relative-bootstrapper.exe",
    )

    assert result.returncode != 0
    assert "absolute path" in f"{result.stdout}\n{result.stderr}"
    assert build_marker.read_text(encoding="utf-8") == "keep build"
    assert dist_marker.read_text(encoding="utf-8") == "keep dist"


def test_release_entrypoint_rejects_relative_bootstrapper_before_cleanup(
    tmp_path: Path,
) -> None:
    repository = _copy_entrypoint(tmp_path)
    archive = repository / "runtime.cab"
    archive.write_bytes(b"cab")
    build_marker, dist_marker = _write_keep_markers(repository)

    result = _run_entrypoint(
        repository,
        str(archive),
        "relative-bootstrapper.exe",
    )

    assert result.returncode != 0
    assert "absolute path" in f"{result.stdout}\n{result.stderr}"
    assert build_marker.read_text(encoding="utf-8") == "keep build"
    assert dist_marker.read_text(encoding="utf-8") == "keep dist"


def test_release_entrypoint_full_mode_does_not_require_bootstrapper(
    tmp_path: Path,
) -> None:
    repository = _copy_entrypoint(tmp_path)
    build_marker, dist_marker = _write_keep_markers(repository)

    result = _run_entrypoint_arguments(
        repository,
        "-PackageMode",
        "Full",
        "-WebView2Archive",
        "relative-runtime.cab",
    )

    assert result.returncode != 0
    assert "WebView2Archive must be an absolute path" in (
        f"{result.stdout}\n{result.stderr}"
    )
    assert build_marker.read_text(encoding="utf-8") == "keep build"
    assert dist_marker.read_text(encoding="utf-8") == "keep dist"


def test_release_entrypoint_lite_mode_does_not_require_archive(
    tmp_path: Path,
) -> None:
    repository = _copy_entrypoint(tmp_path)
    build_marker, dist_marker = _write_keep_markers(repository)

    result = _run_entrypoint_arguments(
        repository,
        "-PackageMode",
        "Lite",
        "-WebView2Bootstrapper",
        "relative-bootstrapper.exe",
    )

    assert result.returncode != 0
    assert "WebView2Bootstrapper must be an absolute path" in (
        f"{result.stdout}\n{result.stderr}"
    )
    assert build_marker.read_text(encoding="utf-8") == "keep build"
    assert dist_marker.read_text(encoding="utf-8") == "keep dist"


def test_release_entrypoint_has_no_skip_or_download_bypass_parameters(
    tmp_path: Path,
) -> None:
    repository = _copy_entrypoint(tmp_path)

    for bypass in (
        "-SkipTests",
        "-SkipHash",
        "-SkipLite",
        "-SkipSignature",
        "-Force",
        "-Download",
    ):
        result = _run_entrypoint(
            repository,
            "relative-runtime.cab",
            "relative-bootstrapper.exe",
            bypass,
        )

        assert result.returncode != 0
        assert "parameter" in f"{result.stdout}\n{result.stderr}".casefold()


def test_release_entrypoint_validates_environment_before_mutating_outputs(
    tmp_path: Path,
) -> None:
    repository = _copy_entrypoint(tmp_path)
    archive = repository / "Microsoft.WebView2.FixedVersionRuntime.x64.cab"
    archive.write_bytes(b"not a real cab")
    bootstrapper = repository / "MicrosoftEdgeWebview2Setup.exe"
    bootstrapper.write_bytes(b"not a real bootstrapper")
    build_marker = repository / "build" / "release" / "keep.txt"
    dist_marker = repository / "dist" / "keep.txt"
    build_marker.parent.mkdir(parents=True)
    dist_marker.parent.mkdir()
    build_marker.write_text("keep build", encoding="utf-8")
    dist_marker.write_text("keep dist", encoding="utf-8")

    result = _run_entrypoint(repository, str(archive), str(bootstrapper))

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
    bootstrapper: str,
    *extra: str,
) -> subprocess.CompletedProcess[str]:
    return _run_entrypoint_arguments(
        repository,
        "-WebView2Archive",
        archive,
        "-WebView2Bootstrapper",
        bootstrapper,
        *extra,
    )


def _run_entrypoint_arguments(
    repository: Path,
    *arguments: str,
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
            *arguments,
        ],
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
        shell=False,
    )


def _write_keep_markers(repository: Path) -> tuple[Path, Path]:
    build_marker = repository / "build" / "release" / "keep.txt"
    dist_marker = repository / "dist" / "keep.txt"
    build_marker.parent.mkdir(parents=True)
    dist_marker.parent.mkdir()
    build_marker.write_text("keep build", encoding="utf-8")
    dist_marker.write_text("keep dist", encoding="utf-8")
    return build_marker, dist_marker
