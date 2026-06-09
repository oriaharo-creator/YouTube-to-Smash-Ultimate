# Contributing

Thanks for your interest in improving **YouTube to Smash Ultimate**! Bug reports,
feature ideas, documentation fixes, and pull requests are all welcome. This guide
explains how to get set up and what makes a change easy to merge.

Please keep all interactions respectful, constructive, and welcoming to
newcomers.

## Ways to help

- **Report a bug** or **request a feature** via the
  [issue templates](https://github.com/oriaharo-creator/YouTube-to-Smash-Ultimate/issues/new/choose).
- **Improve the BGM metadata** in `data/songlist.json` (names, series).
- **Add a deploy target** or improve loop-point handling.
- **Fix or expand the docs** — including [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md).

If you're planning a larger change, please open an issue first so we can agree on
the approach before you invest the time.

## Project layout

| Path | What it is |
|---|---|
| `backend.py` | The conversion pipeline — the single source of truth. |
| `app.py` | PySide6 GUI. |
| `cli.py` | Command-line front end. |
| `tooldl.py` | Runtime downloader for FFmpeg / VGAudio / nus3audio. |
| `ledger.py` | Record of modded slots. |
| `data/songlist.json` | The 1,137 BGM slots. |
| `yt2smash.spec`, `build_*.{bat,sh}`, `installer/` | Packaging. |

**Golden rule:** the GUI and CLI must stay thin wrappers over `backend.py`. Put
conversion logic in the backend so both front ends share it and can never drift.

## Development setup

Use **Python 3.11 or 3.12** (not 3.13+ — `pydub` needs the `audioop` module that
3.13 removed).

```bash
git clone https://github.com/oriaharo-creator/YouTube-to-Smash-Ultimate.git
cd YouTube-to-Smash-Ultimate

python -m venv .venv
# Windows:  .venv\Scripts\activate
# Linux/macOS:  source .venv/bin/activate

pip install PySide6 yt-dlp pydub numpy

# Fetch the external tools into bin/ (or let the app self-install at runtime):
python tooldl.py --dir bin
python cli.py --check          # should print "Preflight OK"

python app.py                  # run the GUI
python cli.py --help           # run the CLI
```

## Coding guidelines

- **Style:** follow [PEP 8](https://peps.python.org/pep-0008/); keep the existing
  4-space indentation and import ordering. Formatting with `black` and linting
  with `ruff` is encouraged but not enforced.
- **Type hints** on public functions; the codebase uses
  `from __future__ import annotations`.
- **Docstrings** explain *why*, not just *what* — match the tone of the existing
  modules. Hardware/format constants must keep their explanatory comments.
- **Errors:** raise the specific `ConversionError` subclass that fits, with a
  message that tells the user how to fix the problem (see `backend.py`).
- **No new heavy dependencies** without discussion — the bundle is deliberately
  lean (the spec excludes scipy/librosa/numba/etc.).
- **Cross-platform:** code must work on Windows and Linux. Resolve bundled tools
  through `backend.resource_path()` / `backend.user_bin_dir()`, never hard-coded
  paths, and branch on `backend.IS_WINDOWS` where the OS genuinely differs.

## Testing your change

There isn't a formal test suite yet (contributions to add one are very welcome!).
Before opening a PR, please verify by hand:

1. `python cli.py --check` passes.
2. A real end-to-end conversion succeeds — GUI **and** CLI — for both **Whole
   track** and **Manual** loop modes.
3. If you touched deployment, test the **save**, **local mod folder**, and (if you
   can) **FTP** paths.
4. If you touched packaging, do a full `build_windows.bat` / `build_linux.sh` and
   confirm the frozen app runs.

Note in your PR description exactly what you tested and on which OS.

## Pull request process

1. Fork the repo and create a branch: `git checkout -b feature/short-description`.
2. Make focused commits with clear messages (imperative mood:
   *"Clamp loop end below sample count"*).
3. Update docs/`CHANGELOG.md` if your change is user-visible.
4. Open a PR against `main`, fill in the template, and link any related issue.
5. A maintainer will review; please be responsive to feedback.

## Licensing

This project is MIT-licensed. By contributing, you agree your contributions are
licensed under the same [MIT License](LICENSE). Don't add code or assets you don't
have the right to license this way, and **never** commit copyrighted audio or the
third-party tool binaries (they're git-ignored and fetched separately).

---

Maintained by [@yoavaharonofficial](https://github.com/yoavaharonofficial) and
[@oriaharo-creator](https://github.com/oriaharo-creator). Thank you for
contributing! 🎮
