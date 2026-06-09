# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for the YouTube -> Smash Ultimate converter.

Build mode: ONE-FOLDER (a `dist/YouTubeToSmash/` directory holding the GUI
executable, a console CLI executable, and an `_internal/` folder with all
dependencies and bundled tools). One-folder is used deliberately: it launches
faster than one-file (no per-run temp extraction) and is far more reliable when
shelling out to bundled native tools (ffmpeg, VGAudioCli, nus3audio). The
Inno Setup installer hides this folder layout from the end user.

Two executables are produced from a single dependency collection:
  * YouTubeToSmash.exe  -- the windowed GUI (no console window)
  * yt2smash-cli.exe    -- the command-line front end (console)

The GUI's dependency graph is a superset of the CLI's (both import `backend`
and `ledger`; the GUI additionally pulls in PySide6), so the shared runtime
libraries are collected once from the GUI Analysis and reused by both EXEs.

Run from this directory on Windows:

    pyinstaller yt2smash.spec

Prerequisites before building:
  * Populate `bin/` with the Windows tools (see bin/README.txt).
  * `pip install -r requirements-build.txt`
  * (Optional) drop an icon at `assets/app.ico`.
"""

import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# SPECPATH is injected by PyInstaller and points at this file's directory.
ROOT = SPECPATH  # noqa: F821


def _tree(folder):
    """Collect every file under ``folder`` as (src_abspath, dest_reldir) pairs,
    preserving the directory structure relative to ROOT."""
    collected = []
    base = os.path.join(ROOT, folder)
    if not os.path.isdir(base):
        return collected
    for dirpath, _dirs, names in os.walk(base):
        for name in names:
            if name == "README.txt":
                continue  # build-time docs only; don't ship them
            if name.endswith(".dev.json"):
                continue  # .NET *dev* runtimeconfig: unused at runtime, and it
                          # carries a developer's absolute paths -- don't ship it
            full = os.path.join(dirpath, name)
            dest = os.path.relpath(dirpath, ROOT)
            collected.append((full, dest))
    return collected


# --- data + bundled binaries -----------------------------------------------
# `data/songlist.json` is required at runtime; `bin/` holds the external tools.
# Both are resolved at runtime via backend.resource_path(), which understands
# PyInstaller's sys._MEIPASS extraction directory.
datas = _tree("data") + _tree("bin")

# yt-dlp loads its extractors dynamically, so its submodules and data files
# must be collected explicitly or the frozen build can't download anything.
datas += collect_data_files("yt_dlp")
hiddenimports = collect_submodules("yt_dlp") + [
    "PySide6.QtSvg",     # inline-SVG icon rendering in the GUI
    "pydub",
]

# Trim obvious dead weight to keep the bundle lean.
excludes = ["tkinter", "librosa", "numba", "llvmlite", "matplotlib", "scipy", "pytest"]

_icon = os.path.join(ROOT, "assets", "app.ico")
icon = _icon if os.path.isfile(_icon) else None


# --- analyses ---------------------------------------------------------------
gui = Analysis(  # noqa: F821
    ["app.py"],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

cli = Analysis(  # noqa: F821
    ["cli.py"],
    pathex=[ROOT],
    binaries=[],
    datas=[],                 # shared data comes from the GUI collection
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

# Drop Qt translation catalogues (~100 ".qm" files). The GUI is English-only and
# never installs a QTranslator, so Qt never loads them -- they're pure dead weight.
gui.datas = [d for d in gui.datas
             if not (d[0].endswith(".qm") and "translations" in d[0].replace("\\", "/"))]

gui_pyz = PYZ(gui.pure, gui.zipped_data)  # noqa: F821
cli_pyz = PYZ(cli.pure, cli.zipped_data)  # noqa: F821

gui_exe = EXE(  # noqa: F821
    gui_pyz,
    gui.scripts,
    [],
    exclude_binaries=True,
    name="YouTubeToSmash",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,            # windowed app: no console window
    disable_windowed_traceback=False,
    icon=icon,
)

cli_exe = EXE(  # noqa: F821
    cli_pyz,
    cli.scripts,
    [],
    exclude_binaries=True,
    name="yt2smash-cli",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,             # CLI: keep the console
    disable_windowed_traceback=False,
    icon=icon,
)

# A single COLLECT folder holds both executables plus the shared dependency
# tree gathered from the GUI Analysis (a superset of the CLI's needs).
coll = COLLECT(  # noqa: F821
    gui_exe,
    cli_exe,
    gui.binaries,
    gui.zipfiles,
    gui.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="YouTubeToSmash",
)
