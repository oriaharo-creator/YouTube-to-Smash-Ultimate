# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-06-05

First public release.

### Added
- One-window **PySide6 GUI** and a scriptable **CLI** (`yt2smash-cli`) sharing a
  single backend pipeline.
- Searchable catalogue of all **1,137 vanilla BGM slots** by name and series.
- Conversion to the exact Switch format: 48 kHz / 16-bit stereo, **CBR
  Namco-Opus**, 48-sample-aligned loop points.
- **Match game volume** (two-pass EBU R128 loudness match) and a manual
  peak-normalise + gain mode.
- **Manual** and **whole-track** looping, snapped to zero-crossings.
- Three deploy targets: save the file, copy into a local mod folder, or **FTP to
  the Switch** over Wi-Fi.
- A **ledger** of modded slots with an overwrite warning.
- **Self-installing components** — FFmpeg, VGAudio, and nus3audio are downloaded
  on first run if missing.
- **Windows** turnkey build (`build_windows.bat`) with a per-user **Inno Setup**
  installer, and a **Linux** build (`build_linux.sh`) with a tarball + desktop
  launcher.
- GitHub Actions CI building the Windows installer and Linux tarball on tags.

### Fixed
- **Opus encoder failing on Windows** — the .NET-Core VGAudio build is now
  launched via the `dotnet` host with `DOTNET_ROLL_FORWARD=LatestMajor`, and its
  runtime config is patched to roll forward, so it binds a modern installed .NET
  runtime instead of silently producing no file.
- **"Loop points must be less than the number of samples"** — the whole-track loop
  end is now clamped to the largest 48-aligned index below the track length, so
  VGAudio accepts it.
- **Crash on non-ASCII tool output on Windows** — child process output is decoded
  as UTF-8 with replacement instead of the locale code page.
- **Non-writable default output folder** — the GUI now defaults to Downloads /
  Documents instead of the working directory, which is read-only when launched
  from a Start Menu shortcut.

[Unreleased]: https://github.com/oriaharo-creator/YouTube-to-Smash-Ultimate/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/oriaharo-creator/YouTube-to-Smash-Ultimate/releases/tag/v1.0.0
