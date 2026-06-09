# Troubleshooting

Most problems fall into one of five buckets: **missing components**, **the .NET
runtime**, **downloading from YouTube**, **sending to your Switch**, or **how the
mod behaves in-game**. Find your symptom below. If none of these fix it, please
[open an issue](https://github.com/oriaharo-creator/YouTube-to-Smash-Ultimate/issues/new/choose)
and include the exact error text and, if you built from source, the console
output.

A fast first check, from the command line:

```
yt2smash-cli --check
```

It prints `Preflight OK` only when FFmpeg, VGAudioCli, and nus3audio all resolve.

---

## Missing components

### "A required component is missing" / the yellow banner won't go away

The app needs three external tools — **FFmpeg** (download + audio), **VGAudioCli**
(Opus encoding), and **nus3audio** (packaging). On first launch it downloads any
that are missing into your per-user folder automatically.

- Let the in-app installer finish — it needs a working internet connection and
  about a minute.
- If it reports something still missing afterward, click **Try setup again**
  (the connection may have dropped mid-download).
- To install them from a terminal instead: `yt2smash-cli --install-tools`.
- The downloaded tools live in:
  - **Windows:** `%APPDATA%\yt2smash\bin`
  - **Linux:** `~/.local/share/yt2smash/bin`

  Deleting that folder forces a clean re-download on next launch.

---

## The .NET runtime (Opus encoder)

### "The Opus encoder (VGAudioCli) could not run… it needs the Microsoft .NET runtime"

VGAudio is a .NET program. If your PC has no compatible .NET runtime, the encoder
can't start and no audio file is produced.

**Fix:** install the free **[.NET Desktop Runtime](https://dotnet.microsoft.com/download)**
(any current version — the app rolls the encoder forward onto whatever you have),
then convert again. Most Windows machines already have .NET from other software;
this only bites a clean install.

> Why this happens: the community VGAudio build targets the long-retired .NET Core
> 2.0. The app sets `DOTNET_ROLL_FORWARD=LatestMajor` and patches VGAudio's
> runtime config so it binds your modern runtime instead — but it still needs
> *some* .NET runtime present.

### "The Opus encoder finished without producing an audio file"

The encoder ran but wrote nothing. The dialog includes VGAudio's own output —
read the last lines. Usually it's the .NET issue above, or a corrupted tool
download (delete the per-user `bin` folder shown above and let it re-download).

---

## Downloading from YouTube

### "Couldn't fetch that video" / "Check the URL and your connection"

- Confirm the link opens in a browser and isn't private, age-restricted, or
  region-blocked.
- Paste the full URL (`https://www.youtube.com/watch?v=…` or `https://youtu.be/…`).
- YouTube changes things often; if a link that should work fails, the bundled
  **yt-dlp** may be out of date. Building from a fresh checkout pulls the latest
  yt-dlp. (A self-updating downloader is on the roadmap — contributions welcome.)
- Check that nothing (VPN, firewall, captive portal) is blocking the connection.

---

## Sending to your Switch

### "Couldn't reach your Switch" / connection refused or timed out

1. Start an **FTP server on the Switch** — `ftpd` (sys-ftpd / homebrew) must be
   running *before* you click Convert.
2. Enter the **exact IP** the FTP app shows (e.g. `192.168.1.164`), and the right
   **port** (ftpd's default is **5000**, not 21).
3. Make sure the PC and Switch are on the **same Wi-Fi network**, and that no
   firewall blocks the connection.
4. Test the FTP login from a desktop FTP client first to rule out the Switch side.

### It uploads, but the song doesn't change in-game

The file must land at exactly:

```
sd:/ultimate/mods/<YourModFolder>/stream;/sound/bgm/bgm_<id>.nus3audio
```

The app builds this path for you, but double-check:

- The **mod folder name** matches a real folder under `/ultimate/mods/`.
- ARCropolis is installed and enabled, and the mod is **toggled on** in its menu.
- The on-disk filename keeps the full `bgm_` prefix (the app does this for you —
  don't rename it).

---

## In-game problems

### The mod plays the wrong slot

You replaced a different `bgm_id` than you intended. Use the in-app **search** to
pick by song name, confirm the resolved ID shown under the dropdown
(*"Will replace bgm_…"*), and check **Modded songs** for what you've already done.

### The audio is silent, or cuts out after a few seconds

- **Silent the whole time / cuts out:** this is almost always a loop-point or
  header issue from an *older* build. Make sure you're on the latest release — the
  current version clamps the loop end below the track length and writes a correct
  Namco header.
- **Set your loop manually** rather than whole-track for a tight, seamless loop.
  Whole-track loops the entire song back to the start, which is correct but not
  "seamless" the way a hand-picked loop is.
- Very loud sources can distort; try **Match game volume** (the default) instead
  of a manual boost.

### "Loop points must be less than the number of samples"

Fixed in the current release. If you still see it, you're running an older build —
update to the latest.

---

## Installing / running the app

### Windows SmartScreen or antivirus flags the EXE

PyInstaller-built executables are unsigned, so Windows SmartScreen may warn and
some antivirus engines flag them heuristically. The app is open source — you can
read every line here and build it yourself. To run anyway: **More info →
Run anyway**. Code-signing the binaries removes this for distribution.

### The app window opens off-screen or too small

It remembers its size between runs. Delete the saved settings to reset:

- **Windows:** registry key `HKEY_CURRENT_USER\Software\yt2smash`
- **Linux:** `~/.config/yt2smash/` settings

---

## Building from source

### `PermissionError: Access is denied` when freezing with PyInstaller

A previously-built `YouTubeToSmash.exe` is still running and locking files in
`dist\`. Close the app (and any error dialog), then rebuild. `rebuild_windows.bat`
now force-closes it and clears `dist\`/`build\` automatically.

### `ModuleNotFoundError: No module named 'audioop'`

You're on **Python 3.13+**, which removed the `audioop` module that `pydub` needs.
Build with **Python 3.11 or 3.12**.

### `cli.py --check` fails right after a build

The bundled tools didn't download into `bin/`. Re-run `python tooldl.py --dir bin`
(it fetches FFmpeg, VGAudio, and nus3audio into the project `bin/`), then build
again. See [`bin/README.txt`](bin/README.txt).

---

## Still stuck?

Open an issue with:

- Your OS and version, and whether you used the installer or built from source.
- The **exact** error text (screenshots are fine).
- For build problems, the console output around the failure.

We read every report. Thanks for helping make the tool better.
