bin/ — bundled command-line tools
==================================

The converter shells out to four external tools at runtime. The backend looks
for them HERE FIRST (backend.resource_path("bin", ...)) before falling back to
anything on your system PATH, so dropping the right binaries in this folder is
all that's needed to make the frozen build self-contained.

The tools are platform-specific. Build on Windows with the Windows set, build
on Linux with the Linux set — see the two sections below.


WINDOWS
-------

Place these files directly in this bin/ folder before building:

  1. ffmpeg.exe        Audio decode/normalise (used by pydub) and required by yt-dlp.
  2. ffprobe.exe       Ships alongside ffmpeg in the same download.
                       -> https://www.gyan.dev/ffmpeg/builds/  (grab a "release" build,
                          copy ffmpeg.exe and ffprobe.exe out of its bin\ folder)

  3. VGAudioCli.exe    Opus/Namco encoding. A .NET application.
                       -> https://github.com/Thealexbarney/VGAudio/releases
                       Use a build that runs WITHOUT 'mono' on Windows. If the release
                       includes companion .dll files (e.g. VGAudio.dll), copy ALL of
                       them into this folder too — they must sit next to the .exe.
                       (If it targets .NET Framework, end users need the .NET runtime;
                       prefer a self-contained / framework-dependent build you've tested.)

  4. nus3audio.exe     .nus3audio container packaging.
                       -> https://github.com/jam1garner/nus3audio-rs/releases
                       (Rename the downloaded Windows binary to exactly nus3audio.exe.)

Windows layout expected by the build:

  bin\
    ffmpeg.exe
    ffprobe.exe
    VGAudioCli.exe
    (any VGAudio*.dll companions)
    nus3audio.exe


LINUX (Ubuntu)
--------------

Place these files directly in this bin/ folder before building. Note that two
of them are native ELF binaries, but VGAudioCli is still the Windows .exe — it
is run through `mono` (the backend prepends mono automatically on non-Windows).

  1. ffmpeg          Native Linux build. The simplest source is the system
  2. ffprobe         package:  sudo apt install ffmpeg  — then copy the
                     binaries here:
                         cp "$(command -v ffmpeg)"  bin/ffmpeg
                         cp "$(command -v ffprobe)" bin/ffprobe
                     Or grab a static build from https://johnvansickle.com/ffmpeg/
                     (good for a portable bundle with no system dependency).

  3. VGAudioCli.exe  Same .NET .exe as on Windows (download from
                     https://github.com/Thealexbarney/VGAudio/releases).
                     Copy the .exe AND any VGAudio*.dll companions here.
                     At runtime it is invoked as `mono VGAudioCli.exe`, so the
                     end user must have mono installed:
                         sudo apt install mono-runtime libmono-system-*
                     (the `mono-complete` package is the safe catch-all).

  4. nus3audio       Native Linux build of nus3audio-rs. If a Linux release
                     binary is published, download and rename it to exactly
                     `nus3audio`. Otherwise build it from source with cargo:
                         cargo install --git https://github.com/jam1garner/nus3audio-rs
                         cp ~/.cargo/bin/nus3audio bin/nus3audio
                     Make it executable:  chmod +x bin/nus3audio

Linux layout expected by the build:

  bin/
    ffmpeg            (chmod +x)
    ffprobe           (chmod +x)
    VGAudioCli.exe    (run via mono)
    (any VGAudio*.dll companions)
    nus3audio         (chmod +x)


Notes
-----
* Tool NAMES matter: the backend resolves "ffmpeg", "ffprobe", "VGAudioCli",
  and "nus3audio". On Windows it appends .exe to each; on Linux it tries the
  bare name first and ALSO the .exe variant (so a bundled VGAudioCli.exe is
  found and run through mono). Keep these exact stems.
* On Linux, make sure the native binaries are executable: chmod +x bin/ffmpeg
  bin/ffprobe bin/nus3audio.
* This README.txt is NOT shipped — the spec skips it when collecting bin/.
* You can verify resolution before packaging by running, from the project root:
      python cli.py --check
  It prints OK only when all four tools are found.
* Licensing: ffmpeg (LGPL/GPL depending on build), VGAudio, and nus3audio each
  carry their own licences. Include their notices in THIRD_PARTY_LICENSES when
  you distribute. The app itself ships no copyrighted audio.
