# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from pathlib import Path

from PyInstaller.compat import is_pure_conda
from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
)


repository_root = Path(SPECPATH)
if is_pure_conda:
    conda_binary_directory = Path(sys.prefix) / "Library" / "bin"
    if not conda_binary_directory.is_dir():
        raise RuntimeError(
            f"Conda native binary directory is missing: {conda_binary_directory}"
        )
    inherited_path = os.environ.get("PATH")
    os.environ["PATH"] = os.pathsep.join(
        [str(conda_binary_directory), *([inherited_path] if inherited_path else [])]
    )

datas = [
    (str(repository_root / "resources"), "resources"),
    *[
        (str(migration), "gamesave_scout/db/migrations")
        for migration in sorted(
            (repository_root / "src" / "gamesave_scout" / "db" / "migrations").glob(
                "*.sql"
            )
        )
    ],
    *collect_data_files("webview", subdir="lib"),
    *collect_data_files("webview", subdir="js"),
]
binaries = collect_dynamic_libs("webview")
if is_pure_conda:
    from PyInstaller.utils.hooks import conda_support

    binaries.extend(
        binary
        for binary in conda_support.collect_dynamic_libs("libexpat")
        if Path(binary[0]).name.casefold() == "libexpat.dll"
    )
hiddenimports = [
    "pefile",
    "PIL.BmpImagePlugin",
    "PIL.JpegImagePlugin",
    "PIL.PngImagePlugin",
    "PIL.WebPImagePlugin",
    "webview.platforms.edgechromium",
    "yaml",
]

analysis = Analysis(
    [str(repository_root / "src" / "gamesave_scout" / "app.py")],
    pathex=[str(repository_root / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)


def _is_required_windows_x64_asset(entry):
    destination = entry[0].replace("\\", "/").casefold()
    excluded = (
        "webview/lib/pywebview-android.jar",
        "webview/lib/webbrowserinterop.x64.dll",
        "webview/lib/webbrowserinterop.x86.dll",
    )
    return not any(destination == item or destination.startswith(item) for item in excluded)


analysis.binaries = [
    entry for entry in analysis.binaries if _is_required_windows_x64_asset(entry)
]
analysis.datas = [entry for entry in analysis.datas if _is_required_windows_x64_asset(entry)]
pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="GameSaveScout",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    contents_directory="_internal",
)

collection = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="GameSaveScout",
)
