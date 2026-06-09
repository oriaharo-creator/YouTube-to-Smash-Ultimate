# Packaging

The app builds on both Windows and Linux. PyInstaller produces native artifacts
per platform and cannot cross-build, so build each target on its own OS. The
Windows path produces an `.exe` + Inno Setup installer; the Linux path produces
a one-folder app + tarball. Jump to [Packaging on Linux (Ubuntu)](#packaging-on-linux-ubuntu)
for the Linux instructions.

# Packaging the Windows installer

This builds the app into a one-folder Windows program (`YouTubeToSmash.exe` +
console `yt2smash-cli.exe`) and wraps it in a `setup.exe`. All steps run **on
Windows** — PyInstaller and Inno Setup produce native Windows artifacts and
cannot cross-build from Linux/macOS.

## One-time setup

1. Install **Python 3.11 or 3.12** (not 3.13+ — `pydub` needs the `audioop`
   module that was removed in 3.13). Tick *Add python.exe to PATH* in the
   installer.
2. *(Optional, only for the `setup.exe`)* Install **Inno Setup 6** (free):
   https://jrsoftware.org/isdl.php
3. *(Optional)* drop an icon at `assets/app.ico` (see `assets/README.txt`).

You do **not** need to fetch ffmpeg/VGAudio/nus3audio yourself — the build
script downloads them into `bin/` for you (`python tooldl.py --dir bin`).

## Build

From the project root, just double-click **`build_windows.bat`** (or run it from
a terminal). It locates Python 3.11/3.12, installs the build deps, auto-downloads
the bundled tools into `bin/`, runs a preflight check, freezes with PyInstaller,
and compiles the per-user installer. Or run the steps manually:

```bat
pip install -r requirements-build.txt
python tooldl.py --dir bin            :: auto-download ffmpeg/VGAudio/nus3audio
python cli.py --check                 :: verify bin/ tools resolve
pyinstaller --noconfirm --clean yt2smash.spec
iscc installer\yt2smash.iss
```

The installer is configured **per-user** (`PrivilegesRequired=lowest`): it
installs under `%LocalAppData%\Programs\YouTubeToSmash` with no UAC prompt. To
build a per-machine installer for all users instead, set `PrivilegesRequired=admin`
in `installer\yt2smash.iss`.

## Outputs

| Artifact | Path |
|---|---|
| Runnable app folder | `dist\YouTubeToSmash\` |
| GUI executable | `dist\YouTubeToSmash\YouTubeToSmash.exe` |
| CLI executable | `dist\YouTubeToSmash\yt2smash-cli.exe` |
| Installer | `installer\Output\YouTubeToSmash-Setup.exe` |

The installer puts the program in `Program Files`, adds a Start Menu shortcut
(and an optional desktop icon), and registers an uninstaller in
Add/Remove Programs.

## How bundling works

`backend.resource_path()` resolves `data/` and `bin/` relative to PyInstaller's
extraction dir (`sys._MEIPASS`) when frozen, and relative to the source tree
otherwise — so the same code path finds `songlist.json` and the tools whether
you run from source or from the installed app. The spec collects `data/` and
`bin/` into the bundle, pulls in `yt_dlp`'s dynamically-loaded extractors as
hidden imports, and excludes heavy unused libs (librosa/numba/scipy/etc.).

## Common issues

- **"A required component is missing" banner / `--check` fails:** a tool is
  absent from `bin/`. Confirm the exact filenames in `bin/README.txt`.
- **VGAudioCli won't run on a clean machine:** it's a .NET app. Use a
  self-contained build, or document the .NET runtime as a prerequisite.
- **Antivirus flags the EXE:** PyInstaller bootloaders sometimes trigger
  heuristics. Signing the executables with a code-signing certificate resolves
  this for distribution.
- **Build succeeds but the app is huge:** ensure the `excludes` in the spec
  still match your environment; accidental imports of scipy/matplotlib bloat it.

## Licensing reminder

The app ships **no copyrighted audio**. `ffmpeg`, `VGAudio`, and `nus3audio`
each have their own licences — include their notices (e.g. in a
`THIRD_PARTY_LICENSES` file) when you distribute the installer.

---

# Packaging on Linux (Ubuntu)

This builds the same one-folder app (`YouTubeToSmash` GUI + `yt2smash-cli`
console tool) for Linux and packages it as a `.tar.gz`. Run these steps **on
Ubuntu** (or another glibc-based Linux). Tested on Ubuntu 22.04+.

## One-time setup

1. Install **Python 3.11 or 3.12** plus the Qt/X11 runtime libraries the GUI
   needs:

   ```bash
   sudo apt update
   sudo apt install python3 python3-pip python3-venv \
       libegl1 libxkbcommon0 libxcb-cursor0 mono-complete ffmpeg
   ```

   `mono-complete` is needed because `VGAudioCli.exe` runs through mono;
   `ffmpeg` provides system `ffmpeg`/`ffprobe` you can copy into `bin/`.

2. Populate `bin/` with the **Linux** tool set — native `ffmpeg`/`ffprobe`/
   `nus3audio` binaries plus the `VGAudioCli.exe` (run via mono). See the
   **LINUX (Ubuntu)** section of `bin/README.txt` for exact sources, names, and
   the `chmod +x` step.

3. *(Optional)* drop a `assets/app.png` icon for the desktop launcher.

## Build

From the project root:

```bash
./build_linux.sh
```

The script installs build deps, runs the preflight tool check, freezes with
PyInstaller, and packs a tarball. Or run the steps manually:

```bash
pip install -r requirements-build.txt
python3 cli.py --check                 # verify bin/ tools resolve
pyinstaller --noconfirm --clean yt2smash.spec
tar -C dist -czf dist/YouTubeToSmash-linux-x86_64.tar.gz YouTubeToSmash
```

## Outputs

| Artifact | Path |
|---|---|
| Runnable app folder | `dist/YouTubeToSmash/` |
| GUI executable | `dist/YouTubeToSmash/YouTubeToSmash` |
| CLI executable | `dist/YouTubeToSmash/yt2smash-cli` |
| Tarball | `dist/YouTubeToSmash-<version>-linux-x86_64.tar.gz` |

Run the app directly with `./dist/YouTubeToSmash/YouTubeToSmash`, or unpack the
tarball anywhere and run the `YouTubeToSmash` binary inside.

## Desktop launcher (menu entry)

To add a “YouTube to Smash Ultimate” entry to your application menu (per-user,
no sudo):

```bash
./linux/install.sh                       # uses ./dist/YouTubeToSmash
./linux/install.sh /opt/YouTubeToSmash   # or point it at where you unpacked
./linux/install.sh --uninstall           # remove the entry
```

It writes a `.desktop` file to `~/.local/share/applications` pointing at the app
folder (it does **not** copy the app, so move the folder wherever you like and
pass its path).

## Linux-specific notes

- **The bundle is not portable across glibc versions.** Build on the oldest
  Ubuntu you intend to support; newer-glibc builds won't start on older systems.
- **`mono` is a runtime dependency** for `VGAudioCli.exe`. It is *not* bundled —
  document `sudo apt install mono-runtime` (or `mono-complete`) for end users, or
  swap in a native Linux Opus encoder if you'd rather drop the mono dependency.
- **GUI won't start / xcb plugin error:** install the Qt platform libs listed in
  one-time setup (`libegl1 libxkbcommon0 libxcb-cursor0`).
- **`audioop` missing:** you're on Python 3.13+. Use 3.11 or 3.12.
