@echo off
REM ===========================================================================
REM  Diagnose the conversion pipeline by running the three bundled tools in
REM  isolation on a generated 3-second test tone, using the SAME arguments the
REM  app uses. Prints each tool's exit code and output so we can see exactly
REM  which step misbehaves (notably: does VGAudioCli actually create the .lopus?)
REM
REM  Run from the project root (the folder with bin\):  diag_tools.bat
REM ===========================================================================
setlocal EnableExtensions
cd /d "%~dp0"

set "FF=bin\ffmpeg.exe"
set "VG=bin\VGAudioCli.exe"
set "N3=bin\nus3audio.exe"

echo.
echo === Tool presence ===
for %%T in ("%FF%" "%VG%" "%N3%") do (
    if exist "%%~T" (echo   FOUND  %%~T) else (echo   MISSING %%~T)
)

echo.
echo === [1] ffmpeg: make a 3s 48kHz/16-bit/stereo test tone (144000 samples) ===
"%FF%" -hide_banner -y -f lavfi -i sine=frequency=440:duration=3 -ar 48000 -ac 2 -sample_fmt s16 test.wav
echo   ffmpeg exit=%errorlevel%
if exist test.wav (echo   OK   test.wav created) else (echo   FAIL test.wav missing & goto :done)

echo.
echo === [2a] VGAudioCli: encode with loop end = FULL length (0-144000) ===
echo       (this mirrors the app's "whole track" / default loop)
"%VG%" -i test.wav -o test.lopus -l 0-144000 --bitrate 64000 --CBR --opusheader namco
echo   VGAudioCli exit=%errorlevel%
if exist test.lopus (
    echo   OK   test.lopus created  ^<-- encode works with full-length loop
) else (
    echo   NO LOPUS produced with 0-144000. Retrying one block shorter...
    echo.
    echo === [2b] VGAudioCli: retry with loop end one block short (0-143952) ===
    "%VG%" -i test.wav -o test.lopus -l 0-143952 --bitrate 64000 --CBR --opusheader namco
    echo   VGAudioCli exit=%errorlevel%
    if exist test.lopus (
        echo   OK   test.lopus created with 0-143952  ^<-- full-length loop end is the bug
    ) else (
        echo   STILL NO LOPUS  ^<-- VGAudio itself is failing; read its output above
        echo                       ^(often: missing .NET runtime, or wrong VGAudio build^)
        goto :done
    )
)

echo.
echo === [3] nus3audio: package the .lopus into a .nus3audio ===
"%N3%" -n -w test.nus3audio -A test test.lopus
echo   nus3audio exit=%errorlevel%
if exist test.nus3audio (echo   OK   test.nus3audio created  ^<-- full pipeline works) else (echo   FAIL test.nus3audio missing)

:done
echo.
echo === Cleanup ^(leaving outputs so you can inspect them^) ===
echo   Generated: test.wav, test.lopus, test.nus3audio ^(whichever succeeded^)
echo.
pause
endlocal
