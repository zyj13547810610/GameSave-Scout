from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or not (Path(sys.prefix) / "conda-meta").is_dir(),
    reason="Conda Windows 原生依赖只在发布构建环境中验证。",
)


@pytest.fixture(scope="module")
def pyinstaller_build(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    repository_root = Path(__file__).resolve().parents[2]
    build_path = tmp_path_factory.mktemp("pyinstaller-spec")
    dist_path = build_path / "dist"
    work_path = build_path / "work"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--clean",
            "--noconfirm",
            str(repository_root / "GameShelf.spec"),
            "--distpath",
            str(dist_path),
            "--workpath",
            str(work_path),
        ],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = f"{completed.stdout}\n{completed.stderr}"

    assert completed.returncode == 0, output
    return dist_path, work_path


def test_pyinstaller_bundle_includes_conda_libexpat(
    pyinstaller_build: tuple[Path, Path],
) -> None:
    dist_path, work_path = pyinstaller_build
    assert (dist_path / "GameShelf" / "_internal" / "libexpat.dll").is_file()
    warnings = (work_path / "GameShelf" / "warn-GameShelf.txt").read_text(
        encoding="utf-8"
    )
    assert "could not resolve 'libexpat.dll'" not in warnings


def test_pyinstaller_bundle_uses_active_conda_openssl(
    pyinstaller_build: tuple[Path, Path],
) -> None:
    dist_path, _ = pyinstaller_build
    internal = dist_path / "GameShelf" / "_internal"
    conda_bin = Path(sys.prefix) / "Library" / "bin"

    for dll_name in ("libcrypto-3-x64.dll", "libssl-3-x64.dll"):
        bundled = internal / dll_name
        expected = conda_bin / dll_name
        assert bundled.is_file()
        assert expected.is_file()
        assert hashlib.file_digest(bundled.open("rb"), "sha256").digest() == (
            hashlib.file_digest(expected.open("rb"), "sha256").digest()
        )


def test_pyinstaller_bundle_contains_pywebview_edge_runtime_paths(
    pyinstaller_build: tuple[Path, Path],
) -> None:
    dist_path, _ = pyinstaller_build
    webview_lib = dist_path / "GameShelf" / "_internal" / "webview" / "lib"

    assert (webview_lib / "Microsoft.Web.WebView2.Core.dll").is_file()
    assert (webview_lib / "Microsoft.Web.WebView2.WinForms.dll").is_file()
    assert (
        webview_lib / "runtimes" / "win-x64" / "native" / "WebView2Loader.dll"
    ).is_file()
    assert (
        webview_lib / "runtimes" / "win-x86" / "native" / "WebView2Loader.dll"
    ).is_file()
    assert (
        webview_lib / "runtimes" / "win-arm64" / "native" / "WebView2Loader.dll"
    ).is_file()
    assert not (webview_lib / "pywebview-android.jar").exists()
    assert not (webview_lib / "WebBrowserInterop.x64.dll").exists()
    assert not (webview_lib / "WebBrowserInterop.x86.dll").exists()


def test_pyinstaller_bundle_includes_only_migration_payload(
    pyinstaller_build: tuple[Path, Path],
) -> None:
    dist_path, _ = pyinstaller_build
    migrations = (
        dist_path / "GameShelf" / "_internal" / "gameshelf" / "db" / "migrations"
    )

    assert (migrations / "0001_initial.sql").is_file()
    assert not (migrations / "__init__.py").exists()
