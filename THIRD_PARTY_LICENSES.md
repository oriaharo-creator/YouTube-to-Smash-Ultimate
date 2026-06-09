# Third-party licenses

The distributed application includes the third-party components listed below.
Each is the property of its respective authors and is used under its own
license. This project's own code is MIT-licensed (see `LICENSE`).

This software ships **no copyrighted audio**. Users supply their own source
material; respect the rights of content owners and the terms of any service
you download from.

## Bundled command-line tools (in `bin/`)

| Tool | Purpose | License | Source |
|---|---|---|---|
| **FFmpeg** (`ffmpeg.exe`, `ffprobe.exe`) | Audio decode / normalise; required by yt-dlp | LGPL-2.1-or-later (GPL-2.0-or-later if built with `--enable-gpl`) | https://ffmpeg.org |
| **VGAudio** (`VGAudioCli.exe`) | Opus / Namco-header encoding | MIT | https://github.com/Thealexbarney/VGAudio |
| **nus3audio-rs** (`nus3audio.exe`) | `.nus3audio` container packaging | MIT | https://github.com/jam1garner/nus3audio-rs |

> **FFmpeg note:** which license applies depends on the *build* you bundle.
> "Essentials"/LGPL builds are LGPL-2.1+; builds compiled with `--enable-gpl`
> (or that include GPL-only libraries such as x264) are GPL. Ship the license
> text that matches the binary you actually distribute, and — for LGPL — keep
> FFmpeg as a separately-replaceable executable (which this app does: it lives
> in `bin/` and is invoked as a subprocess, never statically linked).

## Python libraries (bundled by PyInstaller)

| Library | Purpose | License | Source |
|---|---|---|---|
| **PySide6** (Qt for Python) | Desktop GUI | LGPL-3.0 (or commercial) | https://www.qt.io / https://pypi.org/project/PySide6/ |
| **yt-dlp** | YouTube audio download | The Unlicense (public domain) | https://github.com/yt-dlp/yt-dlp |
| **pydub** | Audio loading / normalisation | MIT | https://github.com/jiaaro/pydub |
| **NumPy** | Loop-point autocorrelation math | BSD-3-Clause | https://numpy.org |
| **PyInstaller** (build tool only; its bootloader ships in the EXE) | Packaging | GPL-2.0-or-later **with a bootloader exception** that permits distributing frozen apps under any license | https://github.com/pyinstaller/pyinstaller |

> **PySide6 / LGPL note:** the app uses PySide6 as an unmodified, dynamically
> linked library, which satisfies the LGPL. Because PyInstaller can bundle Qt
> into a single distribution, include this notice and a copy of the LGPL-3.0
> text with your release, and do not modify the Qt libraries themselves.

## How to assemble full license texts for a release

The table above identifies each component and its license. Before publishing a
release, place the verbatim license text of each bundled component alongside
this file (e.g. in a `licenses/` folder):

- `licenses/FFmpeg-LICENSE.txt` — copy from your FFmpeg build's `LICENSE`/`COPYING`
- `licenses/VGAudio-LICENSE.txt` — from the VGAudio repo
- `licenses/nus3audio-LICENSE.txt` — from the nus3audio-rs repo
- `licenses/PySide6-LGPL-3.0.txt` and `licenses/Qt-LGPL-3.0.txt`
- `licenses/NumPy-LICENSE.txt`, `licenses/pydub-LICENSE.txt`
- `licenses/yt-dlp-UNLICENSE.txt`

Most are short and available in each project's repository root. Verify the
exact license of the *specific version* you bundle, since projects can relicense
between releases.
