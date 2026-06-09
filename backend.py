"""
youtube_to_smash.backend
=========================

Backend conversion pipeline for turning a YouTube URL into a Switch-compatible
``.nus3audio`` file for Super Smash Bros. Ultimate (ARCropolis).

This module is the *single source of truth* for the conversion logic. Both the
command-line wrapper (``cli.py``) and the GUI import the same public API, so
behaviour can never drift between them.

Design goals for a frozen Windows EXE
-------------------------------------
* **No ``mono`` on Windows.** ``VGAudioCli.exe`` is a .NET application and is
  invoked directly; ``mono`` is only used as a fallback on Linux/macOS dev
  machines.
* **Relocatable binaries.** Every bundled tool is resolved through
  :func:`resource_path`, which understands PyInstaller's ``sys._MEIPASS``
  extraction directory, so paths survive freezing.
* **Bundled ffmpeg.** ``pydub`` is pointed at the bundled ``ffmpeg``/``ffprobe``
  and their directory is prepended to ``PATH`` so ``yt-dlp`` finds them too.
* **No librosa.** "Auto-detect" loops the whole track; manual loop points
  heuristic (optional); the primary, recommended path is user-supplied manual
  loop points. This keeps the bundle small and avoids the numba/llvmlite
  freezing headaches.
* **Structured progress + typed errors.** Progress is reported through a
  callback (not stdout scraping) and failures raise specific exception types
  that a GUI can map to friendly dialogs.

Public API
----------
* :class:`ConversionConfig`      -- immutable description of one conversion job.
* :class:`ConversionResult`      -- what came back.
* :class:`ProgressReporter`      -- callback contract for progress updates.
* :func:`convert`                -- run the full pipeline end to end.
* Exceptions: :class:`ConversionError` and its subclasses.
"""

from __future__ import annotations

import os
import sys
import shutil
import struct
import subprocess
import tempfile
import wave
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Hardware / engine constants (do NOT tune these without understanding why)
# ---------------------------------------------------------------------------

#: Smash Ultimate's audio engine expects exactly this PCM format.
TARGET_SAMPLE_RATE = 48_000
TARGET_SAMPLE_WIDTH_BYTES = 2  # 16-bit
TARGET_CHANNELS = 2  # stereo

#: The Switch Opus decoder parses in 48-sample blocks; loop points must be
#: aligned to this boundary or the decoder panics when it seeks.
OPUS_BLOCK_ALIGNMENT = 48

#: VGAudioCli defaults to VBR, which overruns the game's ~3 second audio buffer
#: during loud passages. CBR at 64 kbps is required for stability.
OPUS_BITRATE_BPS = 64_000

#: Loudness target for the "match game volume" mode (EBU R128 / ffmpeg
#: ``loudnorm``). Smash Ultimate's vanilla BGM is mastered very hot and flat;
#: community measurements put most tracks around -8 to -10 LUFS integrated.
#: We target -9 LUFS so a converted track sits at roughly the same perceived
#: loudness as the original slot -- quiet sources get boosted, hot sources get
#: pulled down, all relative to the source's measured loudness. The true-peak
#: ceiling prevents the Switch decoder from clipping. These are tunable.
TARGET_LUFS = -9.0
TARGET_TRUE_PEAK_DB = -1.0
TARGET_LRA = 11.0

#: Volume handling modes (see :class:`ConversionConfig.volume_mode`).
VOLUME_MATCH = "match"    # loudness-match to SSBU vanilla (recommended)
VOLUME_MANUAL = "manual"  # peak-normalise to 0 dBFS, then apply gain_db

#: The community VGAudio build is a framework-dependent .NET Core 2.0 app whose
#: runtimeconfig pins runtime 2.0.0 (long EOL, absent from modern machines).
#: These env vars tell the .NET host to roll that pin forward to whatever modern
#: runtime is installed, so the encoder actually starts. Without this the apphost
#: can't bind a runtime and silently produces no .lopus.
_DOTNET_ROLLFORWARD_ENV = {
    "DOTNET_ROLL_FORWARD": "LatestMajor",
    "DOTNET_ROLL_FORWARD_TO_PRERELEASE": "1",
}

#: ARCropolis stream mount. ``:`` is illegal on FAT32, so ARCropolis encodes the
#: ``stream:`` mount as the folder name ``stream;``.
DEFAULT_FTP_PORT = 5_000
ARC_STREAM_SUBPATH = "stream;/sound/bgm"


# ---------------------------------------------------------------------------
# Path / platform resolution
# ---------------------------------------------------------------------------

IS_WINDOWS = sys.platform.startswith("win")
IS_FROZEN = getattr(sys, "frozen", False)


def resource_path(*relative_parts: str) -> str:
    """Resolve a path to a bundled resource.

    Works both when running from source and when running inside a
    PyInstaller ``--onefile`` / ``--onedir`` build, where data files are
    extracted to ``sys._MEIPASS``.

    Example
    -------
    >>> resource_path("bin", "VGAudioCli.exe")  # doctest: +SKIP
    'C:\\\\...\\\\bin\\\\VGAudioCli.exe'
    """
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *relative_parts)


def _exe_name(stem: str) -> str:
    """Append ``.exe`` on Windows, leave bare elsewhere."""
    return f"{stem}.exe" if IS_WINDOWS else stem


def user_bin_dir() -> str:
    """A per-user, *writable* directory for tools downloaded at runtime.

    The bundled ``bin/`` inside a frozen app lives next to the executable (e.g.
    under ``Program Files``), which a normal user cannot write to. The in-app
    "Install missing components" feature therefore downloads tools here instead,
    and :func:`_locate_binary` searches this location too.

    Mirrors the per-user location ``ledger`` uses:
    Windows ``%APPDATA%\\yt2smash\\bin``; macOS
    ``~/Library/Application Support/yt2smash/bin``; Linux
    ``$XDG_DATA_HOME`` (or ``~/.local/share``) ``/yt2smash/bin``.
    """
    if IS_WINDOWS:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "yt2smash", "bin")


# Marker written by tooldl after it installs an Opus-capable VGAudio build.
# Early versions of this app downloaded VGAudio's GitHub "latest release"
# (v2.2.1), which has no Smash Ultimate Opus encoder. Those users have a stale
# VGAudioCli sitting in user_bin_dir with no stamp; we treat it as missing so it
# gets transparently re-downloaded with a build that actually works.
VGAUDIO_STAMP_NAME = "vgaudio_opus.stamp"


def vgaudio_stamp_path() -> str:
    """Path to the marker proving the installed VGAudio can encode Namco Opus."""
    return os.path.join(user_bin_dir(), VGAUDIO_STAMP_NAME)


def default_output_dir() -> str:
    """A sensible, *writable* default folder for finished files.

    The GUI used to default to :func:`os.getcwd`, which is fine when launched
    from a terminal but wrong for a frozen Windows app started from a Start Menu
    shortcut -- there the working directory is often ``C:\\Windows\\System32`` or
    the install dir under ``Program Files``, neither of which a normal user can
    write to. Prefer the user's Downloads, then Documents, then their home dir,
    falling back to the current directory only as a last resort.
    """
    home = os.path.expanduser("~")
    for sub in ("Downloads", "Documents"):
        candidate = os.path.join(home, sub)
        if os.path.isdir(candidate):
            return candidate
    if os.path.isdir(home):
        return home
    return os.getcwd()


def _vgaudio_is_stale() -> bool:
    """True if the resolved VGAudio is a runtime-downloaded build with no stamp.

    Only applies to copies under :func:`user_bin_dir` (the ones tooldl manages).
    A bundled or on-PATH VGAudio is trusted as-is, so people who supply their
    own Opus-capable build are never second-guessed.
    """
    if not _VGAUDIO:
        return False
    try:
        in_user_dir = os.path.commonpath(
            [os.path.abspath(_VGAUDIO), os.path.abspath(user_bin_dir())]
        ) == os.path.abspath(user_bin_dir())
    except ValueError:  # different drives on Windows
        in_user_dir = False
    if not in_user_dir:
        return False
    return not os.path.isfile(vgaudio_stamp_path())


def _candidate_names(stem: str) -> list[str]:
    """Filenames to look for, in preference order.

    On Windows this is just ``<stem>.exe``; elsewhere we try the bare native
    name first, then the Windows ``.exe`` (which is run through ``mono`` for
    tools that only ship as a ``.exe``, notably VGAudioCli).
    """
    names = [_exe_name(stem)]
    if not IS_WINDOWS:
        names.append(f"{stem}.exe")
    return names


def _locate_binary(stem: str) -> Optional[str]:
    """Find a tool, preferring bundled, then the user tools dir, then PATH.

    Returns the resolved path, or ``None`` if it cannot be found anywhere.
    """
    names = _candidate_names(stem)

    # 1) Bundled next to the app, then 2) downloaded into the user tools dir.
    for directory in (resource_path("bin"), user_bin_dir()):
        for name in names:
            candidate = os.path.join(directory, name)
            if os.path.isfile(candidate):
                return candidate

    # 3) Anything already on PATH.
    for name in names:
        on_path = shutil.which(name)
        if on_path:
            return on_path
    return None


# Resolve external tooling once at import time.
_FFMPEG = _locate_binary("ffmpeg")
_FFPROBE = _locate_binary("ffprobe")
_VGAUDIO = _locate_binary("VGAudioCli")
_NUS3AUDIO = _locate_binary("nus3audio")


def refresh_tools() -> None:
    """Re-resolve every external tool and reconfigure ffmpeg for pydub/yt-dlp.

    Call this after downloading components at runtime (see ``tooldl``) so the
    rest of the module picks up the freshly installed binaries without a
    restart.
    """
    global _FFMPEG, _FFPROBE, _VGAUDIO, _NUS3AUDIO
    _FFMPEG = _locate_binary("ffmpeg")
    _FFPROBE = _locate_binary("ffprobe")
    _VGAUDIO = _locate_binary("VGAudioCli")
    _NUS3AUDIO = _locate_binary("nus3audio")
    _configure_ffmpeg_environment()


def _configure_ffmpeg_environment() -> None:
    """Point pydub at the bundled ffmpeg and make it discoverable to yt-dlp.

    yt-dlp shells out to ffmpeg via PATH, so we prepend the bundled ``bin``
    directory; pydub is configured directly because it caches the converter
    path at import.
    """
    # Lazy import so the module still imports cleanly if pydub is absent.
    try:
        from pydub import AudioSegment  # noqa: WPS433 (intentional local import)
    except Exception:  # pragma: no cover - pydub is a hard runtime dep
        return

    if _FFMPEG:
        AudioSegment.converter = _FFMPEG
        os.environ["PATH"] = os.path.dirname(_FFMPEG) + os.pathsep + os.environ.get("PATH", "")
    if _FFPROBE:
        AudioSegment.ffprobe = _FFPROBE


_configure_ffmpeg_environment()


# ---------------------------------------------------------------------------
# Errors -- specific types so the GUI can show targeted dialogs
# ---------------------------------------------------------------------------


class ConversionError(Exception):
    """Base class for every recoverable, user-facing pipeline failure."""


class MissingDependencyError(ConversionError):
    """A required bundled binary (ffmpeg / VGAudioCli / nus3audio) is missing."""


class DownloadFailedError(ConversionError):
    """yt-dlp could not fetch the requested audio (bad URL, network, geo-block)."""


class AudioProcessingError(ConversionError):
    """ffmpeg/pydub failed while normalising or re-encoding the source audio."""


class EncodingError(ConversionError):
    """VGAudioCli or nus3audio returned a non-zero exit code."""


class InvalidLoopPointsError(ConversionError):
    """Caller-supplied loop points are nonsensical (e.g. end <= start)."""


class SwitchUploadError(ConversionError):
    """FTP deployment to the Switch failed (host down, ftpd not running, ...)."""


# ---------------------------------------------------------------------------
# Progress reporting
# ---------------------------------------------------------------------------


class Stage(Enum):
    """High-level pipeline stages, in execution order."""

    DOWNLOAD = "Downloading audio"
    NORMALIZE = "Normalising audio"
    LOOP_DETECT = "Resolving loop points"
    ENCODE = "Encoding Opus"
    PACKAGE = "Packaging .nus3audio"
    UPLOAD = "Uploading to Switch"
    DONE = "Complete"


#: Stages used to compute overall percentage. UPLOAD is conditional and added
#: dynamically so a local-only conversion shows 100% without an upload step.
_BASE_STAGES = (
    Stage.DOWNLOAD,
    Stage.NORMALIZE,
    Stage.LOOP_DETECT,
    Stage.ENCODE,
    Stage.PACKAGE,
)


# A progress callback receives: (stage, overall_fraction 0..1, message).
ProgressCallback = Callable[[Stage, float, str], None]


class ProgressReporter:
    """Thin helper that turns stage transitions into overall-percentage events.

    The GUI passes a callback; pass ``None`` for silent operation. This replaces
    the old ``[X/6]`` stdout scraping: the worker thread receives structured
    events it can route straight to a ``QProgressBar``.
    """

    def __init__(self, callback: Optional[ProgressCallback], *, include_upload: bool):
        self._callback = callback
        self._stages = list(_BASE_STAGES)
        if include_upload:
            self._stages.append(Stage.UPLOAD)

    def emit(self, stage: Stage, message: str = "", *, sub_fraction: float = 0.0) -> None:
        """Report progress for ``stage``.

        ``sub_fraction`` (0..1) optionally interpolates within a stage so long
        steps like downloading can drive a smooth bar.
        """
        if self._callback is None:
            return
        if stage is Stage.DONE:
            self._callback(stage, 1.0, message or stage.value)
            return
        try:
            index = self._stages.index(stage)
        except ValueError:
            index = 0
        completed = index + max(0.0, min(1.0, sub_fraction))
        fraction = completed / len(self._stages)
        self._callback(stage, max(0.0, min(1.0, fraction)), message or stage.value)


# ---------------------------------------------------------------------------
# Configuration & result objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LoopSpec:
    """How to determine the loop region.

    Exactly one mode applies:

    * ``manual=True``  -> use ``start_sample`` / ``end_sample`` (recommended).
    * ``manual=False`` -> loop the whole track (start 0 -> end of file).

    ``end_sample`` of ``None`` (manual mode) means "loop to end of file".
    All values are in **samples at 48 kHz**.
    """

    manual: bool = True
    start_sample: int = 0
    end_sample: Optional[int] = None
    snap_to_zero_crossing: bool = True

    @classmethod
    def manual_seconds(cls, start_s: float, end_s: Optional[float]) -> "LoopSpec":
        """Convenience constructor taking seconds instead of samples."""
        start = int(round(start_s * TARGET_SAMPLE_RATE))
        end = None if end_s is None else int(round(end_s * TARGET_SAMPLE_RATE))
        return cls(manual=True, start_sample=start, end_sample=end)

    @classmethod
    def auto(cls) -> "LoopSpec":
        """"Auto-detect": loop the whole track (start 0 -> end of file).

        See :func:`_auto_loop_points` for why this is whole-track rather than a
        guessed sub-region.
        """
        return cls(manual=False)


@dataclass(frozen=True)
class ConversionConfig:
    """An immutable description of one conversion job.

    Parameters
    ----------
    url:
        Source YouTube URL.
    bgm_id:
        Target Smash BGM id, e.g. ``bgm_w27_mr_brinstar``. The ARCropolis
        internal name is derived by stripping a leading ``bgm_`` only.
    output_dir:
        Where the final ``.nus3audio`` is written.
    volume_mode:
        How loudness is handled (see the ``VOLUME_*`` constants):

        * ``VOLUME_MATCH`` -- loudness-match the track to Smash Ultimate's
          vanilla BGM using ffmpeg ``loudnorm`` (EBU R128). Quiet sources are
          boosted and hot sources pulled down, so the slot sits at the same
          perceived loudness as the original. Recommended.
        * ``VOLUME_MANUAL`` -- peak-normalise to 0 dBFS, then apply ``gain_db``.
    gain_db:
        Extra gain applied *after* peak-normalisation to 0 dBFS, used only in
        ``VOLUME_MANUAL`` mode. ``0.0`` keeps the normalised peak; negative
        values back it off. Exposed in the GUI as a "Volume boost" slider.
    loop:
        A :class:`LoopSpec` controlling loop-point selection.
    ftp_ip:
        If set, the result is uploaded to the Switch at this address.
    ftp_mod_name:
        ARCropolis mod folder name (under ``/ultimate/mods/``).
    local_mod_dir:
        If set, the result is also written into a local ARCropolis mod folder
        (e.g. an SD card mounted on this PC) at
        ``<local_mod_dir>/stream;/sound/bgm/<internal>.nus3audio``. This is the
        no-FTP deployment path.
    """

    url: str
    bgm_id: str
    output_dir: str
    volume_mode: str = VOLUME_MATCH
    gain_db: float = 0.0
    loop: LoopSpec = field(default_factory=LoopSpec)
    ftp_ip: Optional[str] = None
    ftp_port: int = DEFAULT_FTP_PORT
    ftp_mod_name: str = "HDR"
    local_mod_dir: Optional[str] = None

    @property
    def internal_name(self) -> str:
        """nus3audio internal track label (strip only a leading ``bgm_``).

        This is the ``-A`` name embedded *inside* the .nus3audio container. For
        a music mod ARCropolis never matches on it (the docs literally allow any
        value), so stripping the prefix here is purely cosmetic. The ON-DISK
        filename, however, must keep the prefix -- see :attr:`arc_filename`.
        """
        if self.bgm_id.startswith("bgm_"):
            return self.bgm_id[len("bgm_"):]
        return self.bgm_id

    @property
    def arc_filename(self) -> str:
        """The on-SD filename ARCropolis matches against the game's data.arc.

        Smash streams BGM from ``stream:/sound/bgm/bgm_<id>.nus3audio``, so the
        deployed file MUST be named with the leading ``bgm_`` prefix. Dropping it
        (as an earlier build did for FTP/local deploys) makes ARCropolis find no
        replacement and the vanilla track plays.
        """
        stem = self.bgm_id if self.bgm_id.startswith("bgm_") else f"bgm_{self.bgm_id}"
        return f"{stem}.nus3audio"

    @property
    def output_path(self) -> str:
        return os.path.join(self.output_dir, self.arc_filename)


@dataclass(frozen=True)
class ConversionResult:
    nus3audio_path: str
    loop_start: int
    loop_end: int
    uploaded: bool


# ---------------------------------------------------------------------------
# Subprocess helper -- consistent flags, no console flash on Windows
# ---------------------------------------------------------------------------


def _run(cmd: Sequence[str], *, error_cls: type[ConversionError], what: str,
         env: Optional[dict] = None) -> str:
    """Run a child process, capturing output and raising ``error_cls`` on failure.

    On a windowed (``--windowed``) Windows build there is no console, so we
    suppress the child's console window to avoid a black flash.

    ``env`` is merged onto the current environment (not replacing it), used e.g.
    to pass ``DOTNET_ROLL_FORWARD`` so the .NET-Core VGAudio binds to whatever
    modern .NET runtime the user has installed.
    """
    creationflags = 0
    startupinfo = None
    if IS_WINDOWS:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    child_env = None
    if env:
        child_env = os.environ.copy()
        child_env.update(env)

    try:
        completed = subprocess.run(
            list(cmd),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=child_env,
            # Decode child output as UTF-8 and never let a stray byte crash the
            # pipeline. Without this, `text=True` falls back to the locale code
            # page (cp1252 on most Windows installs); ffmpeg/VGAudio routinely
            # emit non-cp1252 bytes (UTF-8 paths, box-drawing in progress output)
            # which would raise UnicodeDecodeError and abort an otherwise good run.
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
            startupinfo=startupinfo,
        )
    except FileNotFoundError as exc:
        raise MissingDependencyError(f"{what}: executable not found ({cmd[0]}).") from exc
    except subprocess.CalledProcessError as exc:
        tail = (exc.output or "").strip().splitlines()[-5:]
        raise error_cls(f"{what} failed (exit {exc.returncode}):\n" + "\n".join(tail)) from exc
    return completed.stdout or ""


# ---------------------------------------------------------------------------
# Step 1 -- download
# ---------------------------------------------------------------------------


def download_youtube(url: str, output_wav: str, reporter: ProgressReporter) -> str:
    """Download the best audio stream and extract it to ``output_wav``.

    Raises :class:`DownloadFailedError` on any yt-dlp failure.
    """
    try:
        import yt_dlp  # local import keeps module import cheap & optional
    except Exception as exc:  # pragma: no cover
        raise MissingDependencyError("yt-dlp is not installed.") from exc

    reporter.emit(Stage.DOWNLOAD, "Contacting YouTube...")

    def _hook(status: dict) -> None:
        if status.get("status") != "downloading":
            return
        total = status.get("total_bytes") or status.get("total_bytes_estimate")
        done = status.get("downloaded_bytes", 0)
        if total:
            reporter.emit(
                Stage.DOWNLOAD,
                f"Downloading... {done * 100 // total}%",
                sub_fraction=done / total,
            )

    # yt-dlp appends the extension itself, so strip it from the template.
    out_stem = output_wav[:-4] if output_wav.lower().endswith(".wav") else output_wav
    ydl_opts = {
        "format": "bestaudio/best",
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "wav"}],
        "outtmpl": out_stem,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "progress_hooks": [_hook],
        # Let yt-dlp use the ffmpeg we bundled / put on PATH.
        "ffmpeg_location": os.path.dirname(_FFMPEG) if _FFMPEG else None,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except yt_dlp.utils.DownloadError as exc:
        raise DownloadFailedError(
            "Could not download that video. Check the URL and your connection."
        ) from exc

    if not os.path.isfile(output_wav):
        raise DownloadFailedError("Download finished but no audio file was produced.")
    return output_wav


# ---------------------------------------------------------------------------
# Step 2 -- normalise / reformat
# ---------------------------------------------------------------------------


def _loudnorm_measure(input_path: str) -> dict:
    """Pass 1 of ffmpeg ``loudnorm``: measure the source's loudness stats.

    Runs ``loudnorm`` in analysis mode with ``print_format=json`` and parses the
    JSON block ffmpeg writes to stderr. Returns the measured ``input_*`` values
    that pass 2 needs for an accurate, *linear* (non-pumping) normalisation.
    """
    if not _FFMPEG:
        raise MissingDependencyError("FFmpeg was not found. It must be bundled or on PATH.")

    measure_filter = (
        f"loudnorm=I={TARGET_LUFS}:TP={TARGET_TRUE_PEAK_DB}:LRA={TARGET_LRA}:print_format=json"
    )
    out = _run(
        [_FFMPEG, "-hide_banner", "-i", input_path, "-af", measure_filter,
         "-f", "null", "-"],
        error_cls=AudioProcessingError,
        what="Loudness analysis (ffmpeg loudnorm)",
    )

    # ffmpeg prints the JSON object as the tail of its (combined) output.
    import json
    start = out.rfind("{")
    end = out.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise AudioProcessingError("Could not read loudness measurements from ffmpeg.")
    try:
        return json.loads(out[start:end + 1])
    except (ValueError, json.JSONDecodeError) as exc:
        raise AudioProcessingError("Could not parse loudness measurements from ffmpeg.") from exc


def _loudnorm_process(input_wav: str, output_wav: str, reporter: ProgressReporter) -> str:
    """Loudness-match to the SSBU target with a two-pass ffmpeg ``loudnorm``.

    Pass 1 measures the source; pass 2 applies a *linear* gain using those
    measurements (``linear=true``), which avoids the dynamic "pumping" of
    single-pass loudnorm and lands the integrated loudness on
    :data:`TARGET_LUFS` with a :data:`TARGET_TRUE_PEAK_DB` ceiling. Output is the
    exact 48 kHz / 16-bit / stereo PCM the engine requires.
    """
    if not _FFMPEG:
        raise MissingDependencyError("FFmpeg was not found. It must be bundled or on PATH.")

    reporter.emit(Stage.NORMALIZE, "Measuring loudness...", sub_fraction=0.2)
    m = _loudnorm_measure(input_wav)

    reporter.emit(Stage.NORMALIZE, "Matching to game volume...", sub_fraction=0.6)
    apply_filter = (
        f"loudnorm=I={TARGET_LUFS}:TP={TARGET_TRUE_PEAK_DB}:LRA={TARGET_LRA}"
        f":measured_I={m['input_i']}:measured_TP={m['input_tp']}"
        f":measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}"
        f":offset={m['target_offset']}:linear=true:print_format=summary"
    )
    _run(
        [_FFMPEG, "-hide_banner", "-y", "-i", input_wav,
         "-af", apply_filter,
         "-ar", str(TARGET_SAMPLE_RATE),
         "-ac", str(TARGET_CHANNELS),
         "-sample_fmt", "s16",
         output_wav],
        error_cls=AudioProcessingError,
        what="Loudness normalisation (ffmpeg loudnorm)",
    )
    if not os.path.isfile(output_wav):
        raise AudioProcessingError("Loudness normalisation produced no output file.")
    return output_wav


def _manual_process(input_wav: str, output_wav: str, gain_db: float, reporter: ProgressReporter) -> str:
    """Peak-normalise to 0 dBFS (plus ``gain_db``) and force 48 kHz/16-bit/stereo."""
    try:
        from pydub import AudioSegment
        from pydub.exceptions import CouldntDecodeError
    except Exception as exc:  # pragma: no cover
        raise MissingDependencyError("pydub is not installed.") from exc

    reporter.emit(Stage.NORMALIZE, "Normalising and resampling...")

    try:
        audio = AudioSegment.from_file(input_wav)
    except CouldntDecodeError as exc:
        raise AudioProcessingError(
            "Could not decode the downloaded audio. Is FFmpeg available?"
        ) from exc
    except FileNotFoundError as exc:
        # pydub raises this when the ffmpeg executable itself is missing.
        raise MissingDependencyError("FFmpeg was not found. It must be bundled or on PATH.") from exc

    # Peak-normalise to 0 dBFS, then apply the user's gain offset.
    normalized = audio.apply_gain(-audio.max_dBFS + gain_db)
    processed = (
        normalized
        .set_frame_rate(TARGET_SAMPLE_RATE)
        .set_sample_width(TARGET_SAMPLE_WIDTH_BYTES)
        .set_channels(TARGET_CHANNELS)
    )
    processed.export(output_wav, format="wav")
    return output_wav


def process_audio(input_wav: str, output_wav: str, config: "ConversionConfig", reporter: ProgressReporter) -> str:
    """Normalise to the engine format, branching on ``config.volume_mode``.

    * :data:`VOLUME_MATCH`  -> ffmpeg ``loudnorm`` two-pass loudness match.
    * :data:`VOLUME_MANUAL` -> pydub peak-normalise to 0 dBFS + ``gain_db``.
    """
    if config.volume_mode == VOLUME_MATCH:
        return _loudnorm_process(input_wav, output_wav, reporter)
    return _manual_process(input_wav, output_wav, config.gain_db, reporter)


# ---------------------------------------------------------------------------
# Step 3 -- loop points
# ---------------------------------------------------------------------------


def _read_wav_mono(path: str) -> Tuple["object", int, int]:
    """Read a PCM WAV as a mono float array using only numpy + the stdlib.

    Returns ``(samples, sample_rate, total_frames)``.
    """
    import numpy as np

    with wave.open(path, "rb") as wf:
        sample_rate = wf.getframerate()
        channels = wf.getnchannels()
        width = wf.getsampwidth()
        frames = wf.getnframes()
        raw = wf.readframes(frames)

    dtype = {1: np.uint8, 2: np.int16, 4: np.int32}.get(width)
    if dtype is None:
        raise AudioProcessingError(f"Unsupported WAV sample width: {width} bytes.")

    data = np.frombuffer(raw, dtype=dtype).astype(np.float64)
    if width == 1:  # 8-bit PCM is unsigned, centre it
        data -= 128.0
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return data, sample_rate, frames


def _snap_to_zero_crossing(samples, target: int) -> int:
    """Snap ``target`` to the nearest sign change in a mono signal (numpy only)."""
    import numpy as np

    if target <= 0 or target >= len(samples) - 1:
        return int(max(0, min(target, len(samples) - 1)))
    # Search a small window around the target for the closest zero crossing.
    window = TARGET_SAMPLE_RATE // 20  # ~50 ms
    lo = max(1, target - window)
    hi = min(len(samples) - 1, target + window)
    segment = samples[lo:hi]
    crossings = np.where(np.signbit(segment[:-1]) != np.signbit(segment[1:]))[0]
    if len(crossings) == 0:
        return target
    nearest = crossings[np.abs((crossings + lo) - target).argmin()]
    return int(nearest + lo)


def _align(value: int) -> int:
    """Align a sample index to the 48-sample Opus block boundary."""
    return int(round(value / OPUS_BLOCK_ALIGNMENT) * OPUS_BLOCK_ALIGNMENT)


def _auto_loop_points(wav_path: str) -> Tuple[int, int]:
    """Loop the whole track: start at sample 0, end at the final sample.

    HISTORY / why this is dead simple now
    -------------------------------------
    An earlier version ran a numpy autocorrelation to "find the loop". In
    practice that was actively harmful: for almost any real track the strongest
    self-similarity sits at the *smallest* lag the search allowed (~2 s), so it
    returned a 2-second loop region no matter how long the song was. In game the
    BGM then restarted every couple of seconds -- the "loops every few seconds"
    bug. Reliable musical loop-point detection needs structural analysis we
    deliberately don't ship (no librosa/numba), and guessing wrong is worse than
    not guessing.

    So "Auto-detect" now means the only thing we can do correctly for an
    arbitrary YouTube track: play the entire song, then loop back to the start.
    That is what the vast majority of music mods want and it matches the user's
    expectation that the track loops *at its end*, not partway through. Users who
    want a tighter seamless loop can set exact points with Manual mode.
    """
    _, _, total = _read_wav_mono(wav_path)
    return 0, total


def resolve_loop_points(wav_path: str, spec: LoopSpec, reporter: ProgressReporter) -> Tuple[int, int]:
    """Return ``(loop_start, loop_end)`` in samples, validated and aligned.

    Both points are snapped to a zero crossing (to avoid clicks) and then to the
    48-sample Opus block boundary (a hard hardware requirement).
    """
    reporter.emit(Stage.LOOP_DETECT)
    _, _, total = _read_wav_mono(wav_path)

    if spec.manual:
        start = spec.start_sample
        end = spec.end_sample if spec.end_sample is not None else total
    else:
        start, end = _auto_loop_points(wav_path)

    start = max(0, min(start, total - 1))
    end = total if end is None else max(0, min(end, total))
    if end <= start:
        raise InvalidLoopPointsError(
            f"Loop end ({end}) must be greater than loop start ({start})."
        )

    if spec.snap_to_zero_crossing:
        import numpy as np  # noqa: F401  (ensures numpy present for the helper)
        samples, _, _ = _read_wav_mono(wav_path)
        start = _snap_to_zero_crossing(samples, start)
        end = _snap_to_zero_crossing(samples, end)

    start, end = _align(start), _align(end)

    # VGAudio requires BOTH loop points to be non-negative and STRICTLY LESS than
    # the sample count (it rejects loopEnd == total: "Loop points must be less
    # than the number of samples"). The whole-track default sets end = total, and
    # 48-sample alignment can even round end *up* to total -- so clamp the end to
    # the largest aligned index that is still below the track length.
    max_end = max(0, ((total - 1) // OPUS_BLOCK_ALIGNMENT) * OPUS_BLOCK_ALIGNMENT)
    if end > max_end:
        end = max_end
    if start >= end:  # alignment/clamping collapsed the region; back start off
        start = max(0, end - OPUS_BLOCK_ALIGNMENT)
    if end <= start:
        raise InvalidLoopPointsError(
            "The track is too short to set a valid loop region.")
    return start, end


# ---------------------------------------------------------------------------
# Steps 4 & 5 -- Opus encode + nus3audio package
# ---------------------------------------------------------------------------


def _vgaudio_command(wav_path: str, lopus_path: str, loop_start: int, loop_end: int) -> list[str]:
    """Build the VGAudioCli command for the Smash Ultimate Namco-Opus encode.

    The encoder flags are the official ones:
        VGAudioCli -i in.wav -o out.lopus -l s-e --bitrate 64000 --CBR --opusheader namco

    *How* we launch it matters far more than the flags. The community VGAudio is a
    framework-dependent **.NET Core 2.0** build. Three launch paths, in order of
    robustness:

    1. ``dotnet VGAudioCli.dll`` -- the documented, runtime-version-independent
       path. The ``dotnet`` host honours ``DOTNET_ROLL_FORWARD`` (set by the
       caller) and runs the 2.0 assembly on any installed modern .NET. Preferred
       whenever a ``dotnet`` host and the managed ``VGAudioCli.dll`` are present.
    2. The platform **apphost** -- ``VGAudioCli.exe`` on Windows. This is pinned
       to runtime 2.0 by its runtimeconfig; tooldl patches that config to roll
       forward, and the caller also exports ``DOTNET_ROLL_FORWARD`` so even an
       unpatched copy can bind a modern runtime.
    3. ``mono VGAudioCli.exe`` -- last-resort fallback on non-Windows dev boxes.
    """
    if not _VGAUDIO:
        raise MissingDependencyError("VGAudioCli was not found in the bundle or on PATH.")

    encode_args = [
        "-i", wav_path,
        "-o", lopus_path,
        "-l", f"{loop_start}-{loop_end}",
        "--bitrate", str(OPUS_BITRATE_BPS),
        "--CBR",
        "--opusheader", "namco",
    ]

    # 1) Preferred: run the managed DLL through the dotnet host (handles the
    #    2.0 -> modern roll-forward cleanly on every OS).
    vg_dir = os.path.dirname(_VGAUDIO)
    vg_dll = os.path.join(vg_dir, "VGAudioCli.dll")
    dotnet = shutil.which("dotnet")
    if dotnet and os.path.isfile(vg_dll):
        return [dotnet, vg_dll, *encode_args]

    # 2) Windows apphost (relies on the roll-forward env/config to find a runtime).
    if IS_WINDOWS or _VGAUDIO.lower().endswith(".exe") is False:
        return [_VGAUDIO, *encode_args]

    # 3) Non-Windows .exe with no dotnet host: fall back to mono.
    mono = shutil.which("mono")
    if not mono:
        raise MissingDependencyError(
            "Could not run VGAudioCli: install the .NET runtime (provides the "
            "'dotnet' command) or mono to run the Opus encoder.")
    return [mono, _VGAUDIO, *encode_args]


def convert_to_nus3audio(
    wav_path: str,
    loop_start: int,
    loop_end: int,
    config: ConversionConfig,
    reporter: ProgressReporter,
) -> str:
    """Encode to ``.lopus`` (Namco header, CBR) and pack into ``.nus3audio``."""
    if not _NUS3AUDIO:
        raise MissingDependencyError("nus3audio was not found in the bundle or on PATH.")

    base = os.path.splitext(wav_path)[0]
    lopus_path = f"{base}.lopus"

    reporter.emit(Stage.ENCODE, "Encoding to Namco Opus (CBR 64 kbps)...")
    vg_output = _run(
        _vgaudio_command(wav_path, lopus_path, loop_start, loop_end),
        error_cls=EncodingError,
        what="Opus encoding (VGAudioCli)",
        env=_DOTNET_ROLLFORWARD_ENV,
    )

    # VGAudio can exit 0 yet write nothing (e.g. the .NET host failed to bind a
    # runtime, or the build silently rejected an argument). Verify the file is
    # actually there so the failure surfaces here -- with VGAudio's own output --
    # instead of later as a confusing "nus3audio can't read its input" crash.
    if not os.path.isfile(lopus_path) or os.path.getsize(lopus_path) == 0:
        detail = (vg_output or "").strip()
        low = detail.lower()
        if (not detail) or ("framework" in low) or ("to run this application" in low) \
                or ("not be found" in low) or ("dotnet" in low and "install" in low):
            raise MissingDependencyError(
                "The Opus encoder (VGAudioCli) could not run. It needs the "
                "Microsoft .NET runtime, which doesn't appear to be installed.\n\n"
                "Install the free \".NET Desktop Runtime\" (or \".NET Runtime\") "
                "from https://dotnet.microsoft.com/download , then try again."
                + (f"\n\nEncoder output:\n{detail}" if detail else ""))
        raise EncodingError(
            "The Opus encoder finished without producing an audio file.\n\n"
            f"Encoder output:\n{detail}")

    reporter.emit(Stage.PACKAGE, "Packaging .nus3audio...")
    os.makedirs(config.output_dir, exist_ok=True)
    _run(
        [_NUS3AUDIO, "-n", "-w", config.output_path, "-A", config.internal_name, lopus_path],
        error_cls=EncodingError,
        what="nus3audio packaging",
    )

    if os.path.exists(lopus_path):
        os.remove(lopus_path)
    return config.output_path


# ---------------------------------------------------------------------------
# Step 6 -- optional FTP upload
# ---------------------------------------------------------------------------


def upload_to_switch(nus3_path: str, config: ConversionConfig, reporter: ProgressReporter) -> None:
    """Deploy the file into the ARCropolis stream directory over FTP.

    Raises :class:`SwitchUploadError` (never silently swallows) so the GUI can
    prompt the user to start ftpd.
    """
    import ftplib

    reporter.emit(Stage.UPLOAD, f"Connecting to {config.ftp_ip}...")
    remote_dir = f"/ultimate/mods/{config.ftp_mod_name}/{ARC_STREAM_SUBPATH}"
    remote_path = f"{remote_dir}/{config.arc_filename}"

    ftp = ftplib.FTP()
    try:
        ftp.connect(config.ftp_ip, config.ftp_port, timeout=10)
        ftp.login()
        _ftp_makedirs(ftp, remote_dir)
        with open(nus3_path, "rb") as handle:
            ftp.storbinary(f"STOR {remote_path}", handle)
    except OSError as exc:
        # ConnectionRefused (ftpd not running), timeout, host unreachable, ...
        raise SwitchUploadError(
            f"Could not reach the Switch at {config.ftp_ip}:{config.ftp_port}. "
            "Make sure the FTP server (ftpd) is running on your Switch."
        ) from exc
    except ftplib.all_errors as exc:
        raise SwitchUploadError(f"FTP upload failed: {exc}") from exc
    finally:
        try:
            ftp.quit()
        except Exception:
            ftp.close()


def _ftp_makedirs(ftp, remote_dir: str) -> None:
    """Recursively create a remote directory tree, ignoring 'already exists'."""
    import ftplib

    current = ""
    for part in remote_dir.strip("/").split("/"):
        current += f"/{part}"
        try:
            ftp.mkd(current)
        except ftplib.error_perm:
            # 550: directory already exists -- expected, keep going.
            pass


def deploy_local(nus3_path: str, config: ConversionConfig, reporter: ProgressReporter) -> str:
    """Copy the result into a local ARCropolis mod folder (no FTP).

    Builds ``<local_mod_dir>/stream;/sound/bgm/bgm_<id>.nus3audio`` -- the same
    layout ARCropolis expects on the SD card -- so a user with the card mounted
    on this PC can deploy without a network connection. Returns the written path.
    """
    if not config.local_mod_dir:
        raise SwitchUploadError("No local mod folder was selected.")

    reporter.emit(Stage.UPLOAD, "Copying to mod folder...")
    dest_dir = os.path.join(config.local_mod_dir, *ARC_STREAM_SUBPATH.split("/"))
    dest_path = os.path.join(dest_dir, config.arc_filename)
    try:
        os.makedirs(dest_dir, exist_ok=True)
        shutil.copy2(nus3_path, dest_path)
    except OSError as exc:
        raise SwitchUploadError(
            f"Could not write to the mod folder:\n{exc}"
        ) from exc
    return dest_path


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolStatus:
    """Resolution state of one external tool, for a structured preflight."""

    key: str           # stable id used by the downloader, e.g. "ffmpeg"
    label: str         # human label, e.g. "FFmpeg"
    purpose: str       # why it's needed (shown in the UI)
    found: bool
    path: Optional[str]


def tool_status() -> list[ToolStatus]:
    """Structured status for every required tool (drives the GUI checklist).

    ``ffprobe`` ships with ``ffmpeg`` and is grouped under the ``ffmpeg`` key so
    the downloader fetches them together.
    """
    return [
        ToolStatus("ffmpeg", "FFmpeg", "download + audio processing",
                   bool(_FFMPEG and _FFPROBE), _FFMPEG),
        ToolStatus("vgaudio", "VGAudioCli", "Opus encoding",
                   bool(_VGAUDIO) and not _vgaudio_is_stale(), _VGAUDIO),
        ToolStatus("nus3audio", "nus3audio", "packaging the .nus3audio",
                   bool(_NUS3AUDIO), _NUS3AUDIO),
    ]


def missing_tool_keys() -> list[str]:
    """Keys of tools that still need installing (for the downloader)."""
    return [t.key for t in tool_status() if not t.found]


def preflight() -> list[str]:
    """Return a list of human-readable problems with the current install.

    A GUI should call this on launch (and an installer at build verification
    time) so users learn about missing binaries before they start a job.
    """
    purpose = {
        "ffmpeg": "FFmpeg not found (needed for download + audio processing).",
        "vgaudio": "VGAudioCli not found (needed for Opus encoding).",
        "nus3audio": "nus3audio not found (needed for packaging).",
    }
    return [purpose[t.key] for t in tool_status() if not t.found]


def convert(config: ConversionConfig, on_progress: Optional[ProgressCallback] = None) -> ConversionResult:
    """Run the full pipeline for ``config`` and return a :class:`ConversionResult`.

    This is the single entry point shared by the CLI and the GUI. It should be
    invoked on a background worker thread; ``on_progress`` is called from that
    same thread, so a GUI must marshal updates back to the UI thread (e.g. a Qt
    signal).

    Raises a :class:`ConversionError` subclass on any recoverable failure.
    """
    missing = preflight()
    if missing:
        raise MissingDependencyError("Missing required components:\n- " + "\n- ".join(missing))

    deploys = bool(config.ftp_ip) or bool(config.local_mod_dir)
    reporter = ProgressReporter(on_progress, include_upload=deploys)

    with tempfile.TemporaryDirectory(prefix="yt2smash_") as tmp:
        raw_wav = os.path.join(tmp, "raw.wav")
        processed_wav = os.path.join(tmp, "processed.wav")

        download_youtube(config.url, raw_wav, reporter)
        process_audio(raw_wav, processed_wav, config, reporter)
        loop_start, loop_end = resolve_loop_points(processed_wav, config.loop, reporter)
        nus3_path = convert_to_nus3audio(processed_wav, loop_start, loop_end, config, reporter)

        uploaded = False
        if config.ftp_ip:
            upload_to_switch(nus3_path, config, reporter)
            uploaded = True
        if config.local_mod_dir:
            deploy_local(nus3_path, config, reporter)

    reporter.emit(Stage.DONE, "Done")
    return ConversionResult(
        nus3audio_path=nus3_path,
        loop_start=loop_start,
        loop_end=loop_end,
        uploaded=uploaded,
    )
