"""
Command-line front end for the YouTube -> Smash Ultimate conversion pipeline.

This is a *thin* wrapper: all real work lives in :mod:`backend`, so the CLI and
the GUI share identical behaviour. Run ``python cli.py --help`` for usage.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import backend
import ledger
from backend import (
    ConversionConfig,
    ConversionError,
    LoopSpec,
    Stage,
)


def _build_loop_spec(args: argparse.Namespace) -> LoopSpec:
    """Translate CLI flags into a LoopSpec. Manual is the default/primary path."""
    if args.auto_loop:
        return LoopSpec.auto()
    return LoopSpec.manual_seconds(args.loop_start, args.loop_end)


def _make_progress_printer() -> "callable":
    """Render progress as a single rewriting line: ' 42% | Encoding Opus'."""
    last_stage = {"value": None}

    def _printer(stage: Stage, fraction: float, message: str) -> None:
        line = f"\r{fraction * 100:5.1f}% | {message:<40}"
        sys.stdout.write(line)
        sys.stdout.flush()
        if stage is Stage.DONE:
            sys.stdout.write("\n")
        last_stage["value"] = stage

    return _printer


# ---------------------------------------------------------------------------
# Modded-song ledger helpers (shared record with the GUI)
# ---------------------------------------------------------------------------


def _load_songlist() -> list[dict]:
    """Best-effort load of the BGM catalogue for friendly names in the ledger."""
    try:
        with open(backend.resource_path("data", "songlist.json"), encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return []


def _song_for(bgm_id: str, songs: list[dict]) -> dict:
    for song in songs:
        if song.get("bgm_id") == bgm_id:
            return song
    return {}


def _print_mods() -> int:
    """Print the global record of modded slots and exit."""
    entries = ledger.all_entries()
    if not entries:
        print("No modded songs recorded yet.")
        return 0
    print(f"{len(entries)} modded slot(s):")
    for e in entries:
        name = e.get("name") or e.get("bgm_id", "")
        when = e.get("modded_at", "")
        up = "  [on Switch]" if e.get("uploaded") else ""
        print(f"  - {e.get('bgm_id', ''):<28} {name}  ({when}){up}")
    return 0


def _install_tools() -> int:
    """Download any missing bundled components into the per-user tools dir."""
    import tooldl

    missing = backend.missing_tool_keys()
    if not missing:
        print("All components already present.")
        return 0
    print("Installing missing components:", ", ".join(missing))

    def _progress(label: str, fraction: float, message: str) -> None:
        sys.stdout.write(f"\r{fraction * 100:5.1f}% | {message:<48}")
        sys.stdout.flush()
        if fraction >= 1.0:
            sys.stdout.write("\n")

    try:
        tooldl.install_tools(missing, _progress)
    except tooldl.ToolDownloadError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 1
    remaining = backend.preflight()
    if remaining:
        print("Still missing:")
        for item in remaining:
            print(f"  - {item}")
        return 1
    print(f"Done. Tools installed in {backend.user_bin_dir()}")
    return 0


def _confirm_overwrite(config: ConversionConfig, force: bool) -> bool:
    """Warn before overwriting an already-modded slot. Returns True to proceed."""
    prior = ledger.find(config.bgm_id, config.output_dir)
    if not prior:
        return True

    when = prior.get("modded_at", "")
    fname = prior.get("filename", "")
    print(f"Warning: {config.bgm_id} is already modded"
          + (f" (last: {fname}" if fname else "")
          + (f" on {when})" if when else (")" if fname else "")),
          file=sys.stderr)

    if force:
        return True
    if not sys.stdin.isatty():
        print("Refusing to overwrite without --force (non-interactive).", file=sys.stderr)
        return False
    reply = input("Overwrite this slot? [y/N] ").strip().lower()
    return reply in ("y", "yes")


def _record(config: ConversionConfig, result, songs: list[dict]) -> None:
    """Record a successful conversion to both ledgers (never raises)."""
    song = _song_for(config.bgm_id, songs)
    try:
        ledger.record(ledger.ModEntry.create(
            bgm_id=config.bgm_id,
            name=song.get("name", ""),
            series=song.get("series", ""),
            internal_name=config.internal_name,
            filename=os.path.basename(result.nus3audio_path),
            mod_folder=config.ftp_mod_name,
            output_dir=config.output_dir,
            source_url=config.url,
            uploaded=bool(result.uploaded),
            loop_start=int(result.loop_start),
            loop_end=int(result.loop_end),
        ))
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="youtube-to-smash",
        description="Convert a YouTube URL into a Smash Ultimate .nus3audio file.",
    )
    # Optional so `--check` / `--list-mods` can run on their own.
    parser.add_argument("url", nargs="?", help="YouTube URL to convert.")
    parser.add_argument(
        "bgm_id", nargs="?",
        help="Target Smash BGM id, e.g. 'bgm_w27_mr_brinstar'.",
    )
    parser.add_argument(
        "-o", "--output-dir", default=".",
        help="Directory to write the .nus3audio into (default: current dir).",
    )
    parser.add_argument(
        "--volume", choices=[backend.VOLUME_MATCH, backend.VOLUME_MANUAL],
        default=backend.VOLUME_MATCH, dest="volume_mode",
        help="Volume handling: 'match' loudness-matches the track to Smash's "
             "vanilla BGM (recommended, default); 'manual' peak-normalises to "
             "0 dBFS then applies --gain.",
    )
    parser.add_argument(
        "--gain", type=float, default=0.0, dest="gain_db",
        help="Extra gain in dB applied after 0 dBFS normalisation; "
             "only used with --volume manual (default: 0).",
    )

    loop = parser.add_argument_group("loop points")
    loop.add_argument(
        "--auto-loop", action="store_true",
        help="Loop the whole track (play to the end, then back to the start).",
    )
    loop.add_argument(
        "--loop-start", type=float, default=0.0,
        help="Manual loop start in seconds (default: 0.0).",
    )
    loop.add_argument(
        "--loop-end", type=float, default=None,
        help="Manual loop end in seconds (default: end of track).",
    )

    deploy = parser.add_argument_group("deployment (optional)")
    deploy.add_argument("--ftp", dest="ftp_ip", default=None, help="Switch FTP IP, e.g. 192.168.1.164.")
    deploy.add_argument("--ftp-port", type=int, default=backend.DEFAULT_FTP_PORT, help="FTP port (default: 5000).")
    deploy.add_argument("--mod-name", default="HDR", help="ARCropolis mod folder name (used with --ftp).")
    deploy.add_argument(
        "--mod-dir", dest="local_mod_dir", default=None,
        help="Copy the result into a local ARCropolis mod folder (no FTP). Point "
             "this at the mod's own folder; the stream;/sound/bgm subpath is added.",
    )

    parser.add_argument("--check", action="store_true", help="Run a preflight dependency check and exit.")
    parser.add_argument("--install-tools", action="store_true",
                        help="Download any missing bundled components, then exit.")
    parser.add_argument("--list-mods", action="store_true", help="List previously modded slots and exit.")
    parser.add_argument("--force", action="store_true", help="Overwrite an already-modded slot without prompting.")

    args = parser.parse_args(argv)

    if args.install_tools:
        return _install_tools()

    if args.check:
        problems = backend.preflight()
        if problems:
            print("Preflight FAILED:")
            for item in problems:
                print(f"  - {item}")
            return 1
        print("Preflight OK: ffmpeg, VGAudioCli and nus3audio all found.")
        return 0

    if args.list_mods:
        return _print_mods()

    if not args.url or not args.bgm_id:
        parser.error("url and bgm_id are required (unless using --check or --list-mods).")

    config = ConversionConfig(
        url=args.url,
        bgm_id=args.bgm_id,
        output_dir=args.output_dir,
        volume_mode=args.volume_mode,
        gain_db=args.gain_db,
        loop=_build_loop_spec(args),
        ftp_ip=args.ftp_ip,
        ftp_port=args.ftp_port,
        ftp_mod_name=args.mod_name,
        local_mod_dir=args.local_mod_dir,
    )

    if not _confirm_overwrite(config, args.force):
        print("Cancelled - existing mod kept.", file=sys.stderr)
        return 1

    songs = _load_songlist()

    try:
        result = backend.convert(config, on_progress=_make_progress_printer())
    except ConversionError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 1

    _record(config, result, songs)

    print(f"Wrote {result.nus3audio_path}")
    print(f"Loop region: {result.loop_start}-{result.loop_end} samples @ 48kHz")
    if result.uploaded:
        print("Uploaded to Switch.")
    if config.local_mod_dir:
        print(f"Copied into mod folder: {config.local_mod_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
