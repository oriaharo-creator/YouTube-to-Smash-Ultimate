"""
youtube_to_smash.tooldl
========================

Runtime downloader for the bundled command-line tools (FFmpeg/ffprobe,
VGAudioCli, nus3audio). This powers the GUI's **"Install missing components"**
button: if a frozen build is missing a tool (or a from-source checkout never
populated ``bin/``), the app can fetch the right binaries for the current OS and
drop them into the per-user, writable tools directory
(:func:`backend.user_bin_dir`) -- no admin rights, no separate download.

Design constraints
------------------
* **Standard library only.** Uses ``urllib`` for HTTP and ``zipfile`` /
  ``tarfile`` for extraction, so it adds no dependencies to the freeze.
* **Writable location.** Everything lands in :func:`backend.user_bin_dir`,
  which :func:`backend._locate_binary` already searches, so a follow-up
  :func:`backend.refresh_tools` makes the tools live without a restart.
* **Structured progress.** Each step reports ``(label, fraction, message)`` so
  the GUI can drive a progress bar from a worker thread.

The download sources mirror the CI workflow (``.github/workflows/build.yml``):
gyan.dev / johnvansickle / evermeet for FFmpeg, and the upstream GitHub releases
for VGAudio and nus3audio.
"""

from __future__ import annotations

import json
import os
import shutil
import ssl
import stat
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from typing import Callable, Optional

import backend  # for user_bin_dir(), refresh_tools(), platform flags

# (label, overall_fraction 0..1, message)
ToolDLProgress = Callable[[str, float, str], None]

_UA = {"User-Agent": "yt2smash-tooldl/1.0"}


class ToolDownloadError(Exception):
    """A component could not be downloaded or installed."""


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def _ssl_context() -> ssl.SSLContext:
    """A normal verifying context; falls back gracefully if certs are absent."""
    try:
        return ssl.create_default_context()
    except Exception:  # pragma: no cover
        return ssl.create_default_context()


def _download(url: str, dest: str, progress: Optional[ToolDLProgress],
              label: str, lo: float, hi: float) -> str:
    """Stream ``url`` to ``dest``, reporting progress between fractions ``lo``..``hi``."""
    req = urllib.request.Request(url, headers=_UA)
    try:
        with urllib.request.urlopen(req, context=_ssl_context(), timeout=60) as resp:
            total = int(resp.headers.get("Content-Length", 0) or 0)
            read = 0
            chunk = 1 << 16
            with open(dest, "wb") as out:
                while True:
                    buf = resp.read(chunk)
                    if not buf:
                        break
                    out.write(buf)
                    read += len(buf)
                    if progress and total:
                        frac = lo + (hi - lo) * (read / total)
                        mb = read / (1 << 20)
                        progress(label, frac, f"Downloading {label}... {mb:.1f} MB")
    except Exception as exc:  # urllib raises a zoo of errors; normalise them
        raise ToolDownloadError(f"Failed to download {label}: {exc}") from exc
    return dest


def _github_assets(repo: str) -> list[dict]:
    """Return the asset list for a GitHub repo's latest release."""
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    req = urllib.request.Request(url, headers={**_UA, "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, context=_ssl_context(), timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise ToolDownloadError(f"Could not query GitHub release for {repo}: {exc}") from exc
    return data.get("assets", [])


def _pick_asset(assets: list[dict], *, suffix: str = "", contains: str = "") -> Optional[dict]:
    for asset in assets:
        name = asset.get("name", "")
        if suffix and not name.lower().endswith(suffix.lower()):
            continue
        if contains and contains.lower() not in name.lower():
            continue
        return asset
    return None


def _make_executable(path: str) -> None:
    """chmod +x on POSIX; a no-op on Windows."""
    if not backend.IS_WINDOWS:
        st = os.stat(path)
        os.chmod(path, st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _copy_into_bin(src: str, name: str, bin_dir: Optional[str] = None) -> str:
    bin_dir = bin_dir or backend.user_bin_dir()
    os.makedirs(bin_dir, exist_ok=True)
    dest = os.path.join(bin_dir, name)
    shutil.copy2(src, dest)
    _make_executable(dest)
    return dest


# ---------------------------------------------------------------------------
# Per-tool installers
# ---------------------------------------------------------------------------


def _install_ffmpeg(progress: Optional[ToolDLProgress], lo: float, hi: float,
                    bin_dir: Optional[str] = None) -> None:
    """Fetch ffmpeg + ffprobe for the current OS into the user tools dir."""
    label = "FFmpeg"
    with tempfile.TemporaryDirectory(prefix="yt2smash_ff_") as tmp:
        if backend.IS_WINDOWS:
            url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
            archive = _download(url, os.path.join(tmp, "ffmpeg.zip"), progress, label, lo, hi - 0.05)
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(tmp)
            _harvest(tmp, {"ffmpeg.exe", "ffprobe.exe"}, bin_dir)
        elif sys.platform == "darwin":
            for tool in ("ffmpeg", "ffprobe"):
                url = f"https://evermeet.cx/ffmpeg/getrelease/{tool}/zip"
                archive = _download(url, os.path.join(tmp, f"{tool}.zip"), progress, label, lo, hi - 0.05)
                with zipfile.ZipFile(archive) as zf:
                    zf.extractall(tmp)
            _harvest(tmp, {"ffmpeg", "ffprobe"}, bin_dir)
        else:  # Linux: static build with both binaries
            url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
            archive = _download(url, os.path.join(tmp, "ffmpeg.tar.xz"), progress, label, lo, hi - 0.05)
            with tarfile.open(archive, "r:xz") as tf:
                tf.extractall(tmp)
            _harvest(tmp, {"ffmpeg", "ffprobe"}, bin_dir)
    if progress:
        progress(label, hi, "FFmpeg installed")


# The GitHub "latest release" of VGAudio (v2.2.1, Feb 2018) PREDATES Smash
# Ultimate Opus support: it cannot infer the ``.lopus`` extension and rejects
# ``--opusheader``/``--CBR``, so it can never produce a Namco Opus file. The
# Smash modding community therefore ships a newer build; the canonical, stable
# copy is the one bundled with the official modding documentation. It is a
# .NET Core build (VGAudioCli.dll + a VGAudioCli.exe apphost + VGAudio.dll) that
# runs directly on Windows (with the .NET runtime) and through ``mono`` on
# Linux/macOS -- verified end-to-end to emit a valid Namco ``.lopus``.
_VGAUDIO_ZIP_URL = (
    "https://github.com/Coolsonickirby/Smash-Ultimate-Documentation/"
    "raw/main/programs/vgaudio.zip"
)


def _purge_old_vgaudio(bin_dir: Optional[str] = None) -> None:
    """Delete any previously installed VGAudio files from the tools dir.

    Removes the stale stamp plus every ``VGAudio*`` file so a fresh, known-good
    build can be laid down without orphaned DLLs from an older version.
    """
    bin_dir = bin_dir or backend.user_bin_dir()
    if not os.path.isdir(bin_dir):
        return
    for fn in os.listdir(bin_dir):
        low = fn.lower()
        if low.startswith("vgaudio") or fn == backend.VGAUDIO_STAMP_NAME:
            try:
                os.remove(os.path.join(bin_dir, fn))
            except OSError:
                pass


def _install_vgaudio(progress: Optional[ToolDLProgress], lo: float, hi: float,
                     bin_dir: Optional[str] = None) -> None:
    """Fetch an Opus-capable VGAudioCli (CLI + companion DLLs).

    The same managed assembly is used on every OS; on Linux/macOS it is run
    through ``mono`` (see ``backend._vgaudio_command``). We deliberately do NOT
    use ``Thealexbarney/VGAudio``'s GitHub release: that build is too old and
    lacks Smash Ultimate's Namco Opus encoder. See ``_VGAUDIO_ZIP_URL`` above.
    """
    label = "VGAudioCli"
    # Clear any previous VGAudio (notably the stale v2.2.1 a prior version of
    # this app may have installed) so old DLLs can't shadow the new build.
    _purge_old_vgaudio(bin_dir)
    with tempfile.TemporaryDirectory(prefix="yt2smash_vg_") as tmp:
        archive = _download(_VGAUDIO_ZIP_URL, os.path.join(tmp, "vgaudio.zip"),
                            progress, label, lo, hi - 0.05)
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(tmp)
        # Copy the CLI (.exe apphost + .dll), every VGAudio*.dll companion, and
        # the .NET runtime config sidecars that sit next to them.
        copied = False
        for root, _dirs, files in os.walk(tmp):
            for fn in files:
                low = fn.lower()
                if not low.startswith("vgaudio"):
                    continue
                if low.endswith((".exe", ".dll", ".json")):
                    _copy_into_bin(os.path.join(root, fn), fn, bin_dir)
                    if low == "vgaudiocli.exe":
                        copied = True
        if not copied:
            raise ToolDownloadError(
                "VGAudio archive did not contain VGAudioCli.exe.")
    # Patch the runtimeconfig so the .NET-Core-2.0 build rolls forward onto a
    # modern installed runtime. Without this the pinned 2.0 apphost can't bind a
    # runtime on present-day machines and silently encodes nothing.
    _patch_vgaudio_runtimeconfig(bin_dir)
    # Stamp the install so backend trusts this copy as Opus-capable. The stamp
    # lives next to the binaries so it travels with whichever dir we targeted
    # (the per-user tools dir at runtime, or the project bin/ at build time).
    stamp = os.path.join(bin_dir, backend.VGAUDIO_STAMP_NAME) if bin_dir else backend.vgaudio_stamp_path()
    try:
        with open(stamp, "w", encoding="utf-8") as fh:
            fh.write("opus-capable VGAudio installed by tooldl\n")
    except OSError:
        pass  # non-fatal: worst case the tool re-checks next launch
    if progress:
        progress(label, hi, "VGAudioCli installed")


def _patch_vgaudio_runtimeconfig(bin_dir: Optional[str] = None) -> None:
    """Add ``rollForward: LatestMajor`` to VGAudioCli.runtimeconfig.json.

    The community VGAudio build pins ``Microsoft.NETCore.App`` 2.0.0 with no
    roll-forward policy, so it refuses to start on a machine that only has a
    modern .NET. Rewriting the config to roll forward lets the apphost (and the
    ``dotnet`` host) bind whatever runtime is actually installed.
    """
    bin_dir = bin_dir or backend.user_bin_dir()
    cfg = os.path.join(bin_dir, "VGAudioCli.runtimeconfig.json")
    if not os.path.isfile(cfg):
        return
    try:
        with open(cfg, encoding="utf-8") as fh:
            data = json.load(fh)
        opts = data.setdefault("runtimeOptions", {})
        opts["rollForward"] = "LatestMajor"
        with open(cfg, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
    except (OSError, ValueError):
        pass  # non-fatal: the backend also exports DOTNET_ROLL_FORWARD at runtime


def _install_nus3audio(progress: Optional[ToolDLProgress], lo: float, hi: float,
                       bin_dir: Optional[str] = None) -> None:
    """Fetch the nus3audio CLI from jam1garner/nus3audio-rs.

    Upstream publishes a prebuilt binary for every OS in the same release:
    ``nus3audio.exe`` (Windows), ``nus3audio`` (Linux, a bare ELF) and
    ``nus3audio_mac`` (macOS). We download the right one directly so setup is
    fully automatic with no build step or manual file copying.
    """
    label = "nus3audio"
    assets = _github_assets("jam1garner/nus3audio-rs")

    if backend.IS_WINDOWS:
        wanted_names = ("nus3audio.exe",)
        out_name = "nus3audio.exe"
    elif sys.platform == "darwin":
        wanted_names = ("nus3audio_mac",)
        out_name = "nus3audio"
    else:  # Linux: the asset is the bare, extension-less "nus3audio" ELF.
        wanted_names = ("nus3audio",)
        out_name = "nus3audio"

    asset = None
    for want in wanted_names:
        for a in assets:
            if a.get("name", "").lower() == want.lower():
                asset = a
                break
        if asset:
            break
    if not asset:
        raise ToolDownloadError(
            "Couldn't find a prebuilt nus3audio for this system in the latest "
            "release. Please try again later.")

    with tempfile.TemporaryDirectory(prefix="yt2smash_n3_") as tmp:
        blob = _download(asset["browser_download_url"], os.path.join(tmp, asset["name"]),
                         progress, label, lo, hi - 0.05)
        _copy_into_bin(blob, out_name, bin_dir)
    if progress:
        progress(label, hi, "nus3audio installed")


# ---------------------------------------------------------------------------
# Extraction utilities
# ---------------------------------------------------------------------------


def _extract_any(path: str, dest: str) -> None:
    """Extract a .zip / .tar.* archive, or leave a bare binary in place."""
    low = path.lower()
    if low.endswith(".zip"):
        with zipfile.ZipFile(path) as zf:
            zf.extractall(dest)
    elif any(low.endswith(ext) for ext in (".tar.xz", ".tar.gz", ".tgz", ".tar.bz2", ".tar")):
        with tarfile.open(path) as tf:
            tf.extractall(dest)
    # else: a raw binary already at `path` -- nothing to do.


def _harvest(root: str, names: set[str], bin_dir: Optional[str] = None) -> None:
    """Walk ``root`` and copy any file whose basename matches ``names`` into bin/."""
    wanted = {n.lower() for n in names}
    found: set[str] = set()
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            if fn.lower() in wanted:
                _copy_into_bin(os.path.join(dirpath, fn), fn, bin_dir)
                found.add(fn.lower())
    missing = wanted - found
    if missing:
        raise ToolDownloadError(
            "Downloaded archive did not contain: " + ", ".join(sorted(missing))
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


_INSTALLERS = {
    "ffmpeg": _install_ffmpeg,
    "vgaudio": _install_vgaudio,
    "nus3audio": _install_nus3audio,
}


def install_tools(keys: list[str], progress: Optional[ToolDLProgress] = None,
                  dest_dir: Optional[str] = None) -> None:
    """Download and install the tools named by ``keys`` (see ``backend.tool_status``).

    Splits the 0..1 progress range evenly across the requested tools, runs each
    installer, then (for a runtime install) calls :func:`backend.refresh_tools`
    so the freshly installed binaries are picked up immediately.

    ``dest_dir`` overrides where the binaries land. Leave it ``None`` for the
    normal runtime behaviour (the per-user tools dir). The Windows/Linux build
    scripts pass the project ``bin/`` so the tools get bundled into the frozen
    app; in that case we skip ``refresh_tools`` (there's nothing live to refresh
    at build time).

    Raises :class:`ToolDownloadError` on the first failure.
    """
    keys = [k for k in keys if k in _INSTALLERS]
    if not keys:
        return
    span = 1.0 / len(keys)
    for i, key in enumerate(keys):
        lo, hi = i * span, (i + 1) * span
        _INSTALLERS[key](progress, lo, hi, dest_dir)
    if dest_dir is None:
        backend.refresh_tools()
    if progress:
        progress("Done", 1.0, "All components installed")


def install_missing(progress: Optional[ToolDLProgress] = None) -> list[str]:
    """Install whatever :func:`backend.missing_tool_keys` reports as missing.

    Returns the list of keys that were (attempted to be) installed.
    """
    keys = backend.missing_tool_keys()
    install_tools(keys, progress)
    return keys


if __name__ == "__main__":
    # CLI usage:
    #   python tooldl.py [ffmpeg vgaudio nus3audio ...]   -> per-user tools dir
    #   python tooldl.py --dir bin [keys...]              -> a specific folder
    #
    # The build scripts call `python tooldl.py --dir bin`, which fetches ALL
    # tools into the project bin/ so PyInstaller bundles them. (We can't use
    # "missing" keys at build time: a tool already on the dev machine's PATH
    # would be skipped and then be absent from the frozen, self-contained app.)
    def _print(label: str, frac: float, msg: str) -> None:
        sys.stdout.write(f"\r[{frac*100:5.1f}%] {msg:<48}")
        sys.stdout.flush()
        if frac >= 1.0:
            sys.stdout.write("\n")

    argv = sys.argv[1:]
    dest_dir: Optional[str] = None
    if "--dir" in argv:
        i = argv.index("--dir")
        try:
            dest_dir = os.path.abspath(argv[i + 1])
        except IndexError:
            print("Error: --dir requires a path argument.", file=sys.stderr)
            raise SystemExit(2)
        del argv[i:i + 2]

    if dest_dir is not None:
        # Building a bundle: fetch everything unless specific keys were named.
        requested = argv or list(_INSTALLERS.keys())
    else:
        requested = argv or backend.missing_tool_keys()

    if not requested:
        print("All components already present.")
    else:
        target = dest_dir or backend.user_bin_dir()
        print("Installing:", ", ".join(requested), "->", target)
        install_tools(requested, _print, dest_dir=dest_dir)
        print("Done. Tools in:", target)
