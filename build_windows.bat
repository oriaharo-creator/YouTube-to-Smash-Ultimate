@echo off
REM ===========================================================================
REM  Build the YouTube -> Smash Ultimate Windows app + installer  (TURNKEY).
REM
REM  Just double-click this file (or run it from a terminal) on Windows. It:
REM    1. finds a usable Python (3.11 or 3.12 - NOT 3.13+, pydub needs audioop)
REM    2. installs the Python build dependencies
REM    3. AUTO-DOWNLOADS the bundled tools (ffmpeg, ffprobe, VGAudioCli,
REM       nus3audio) into bin\  -- no manual hunting for binaries
REM    4. freezes the GUI + CLI into dist\YouTubeToSmash\ with PyInstaller
REM    5. (if Inno Setup is installed) builds the per-user installer
REM    6. packages a portable zip with the EXE at its ROOT (the clean, minimal
REM       download for GameBanana / a GitHub release)
REM
REM  Only prerequisite you must install yourself: Python 3.11 or 3.12
REM    https://www.python.org/downloads/   (tick "Add python.exe to PATH")
REM  Optional, for the installer step: Inno Setup 6
REM    https://jrsoftware.org/isdl.php
REM ===========================================================================
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
set "APPVER=1.0.0"

echo.
echo ===========================================================================
echo   YouTube to Smash Ultimate  -  Windows build
echo ===========================================================================

REM --- [0/6] Locate a Python 3.11/3.12 interpreter --------------------------
echo.
echo [0/6] Locating Python 3.11 or 3.12...
set "PY="

REM Prefer the py launcher with an explicit version (most reliable).
for %%V in (3.12 3.11) do (
    if not defined PY (
        py -%%V -c "import sys" >nul 2>nul && set "PY=py -%%V"
    )
)

REM Fall back to whatever 'python' is, but only if it's 3.11 or 3.12.
if not defined PY (
    python -c "import sys; raise SystemExit(0 if (3,11)<=sys.version_info[:2]<=(3,12) else 1)" >nul 2>nul && set "PY=python"
)

if not defined PY (
    echo.
    echo   ERROR: Could not find Python 3.11 or 3.12.
    echo.
    echo   This app must be frozen with Python 3.11 or 3.12 - NOT 3.13 or newer,
    echo   because pydub relies on the stdlib "audioop" module that 3.13 removed.
    echo.
    echo   Install Python 3.12 from https://www.python.org/downloads/ ^(tick
    echo   "Add python.exe to PATH" during setup^), then run this script again.
    goto :error
)
for /f "delims=" %%I in ('%PY% -c "import sys;print(sys.version.split()[0])"') do set "PYVER=%%I"
echo   Using Python %PYVER%   ^(command: %PY%^)

echo.
echo [1/6] Installing build dependencies...
%PY% -m pip install --upgrade pip >nul 2>nul
%PY% -m pip install -r requirements-build.txt || goto :error

echo.
echo [2/6] Downloading bundled tools into bin\ ^(ffmpeg, VGAudioCli, nus3audio^)...
echo   This can take a couple of minutes the first time.
%PY% tooldl.py --dir bin || goto :error

echo.
echo [3/6] Preflight: checking bundled tools resolve...
%PY% cli.py --check
if errorlevel 1 (
    echo.
    echo   WARNING: not all tools were found after download. The app will still
    echo   build and can self-install missing pieces on first launch, but the
    echo   bundle won't be fully self-contained. See bin\README.txt.
    echo.
)

echo.
echo Closing any running app and clearing old build folders...
REM A running YouTubeToSmash.exe locks files in dist\ and makes the freeze fail
REM with "Access is denied". Close it first, then remove stale outputs.
taskkill /f /im YouTubeToSmash.exe  >nul 2>nul
taskkill /f /im yt2smash-cli.exe    >nul 2>nul
ping -n 2 127.0.0.1 >nul
if exist dist  rmdir /s /q dist  2>nul
if exist build rmdir /s /q build 2>nul

echo.
echo [4/6] Freezing with PyInstaller ^(one-folder^)...
%PY% -m PyInstaller --noconfirm --clean yt2smash.spec || goto :error
echo   -^> dist\YouTubeToSmash\YouTubeToSmash.exe
echo   -^> dist\YouTubeToSmash\yt2smash-cli.exe

echo.
echo [5/6] Building the per-user installer with Inno Setup...
set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%ISCC%" (
    "%ISCC%" installer\yt2smash.iss || goto :error
    echo   -^> installer\Output\YouTubeToSmash-Setup.exe
) else (
    echo   Inno Setup not found - skipping the installer step.
    echo   The runnable app is ready at dist\YouTubeToSmash\ ^(you can zip and
    echo   share that folder as-is^). To also build the setup.exe, install Inno
    echo   Setup 6 from https://jrsoftware.org/isdl.php then run:
    echo       iscc installer\yt2smash.iss
)

echo.
echo [6/6] Packaging the portable zip ^(EXE at the root^)...
set "PORTZIP=YouTubeToSmash-v%APPVER%-windows-x64.zip"
if exist "%PORTZIP%" del /q "%PORTZIP%"
REM Compress the *contents* of the onedir folder so YouTubeToSmash.exe sits at
REM the zip root (not inside a nested folder) - the clean, professional layout.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path 'dist\YouTubeToSmash\*' -DestinationPath '%PORTZIP%' -Force" || goto :error
echo   -^> %PORTZIP%

echo.
echo ===========================================================================
echo   DONE.
echo     Run it now:   dist\YouTubeToSmash\YouTubeToSmash.exe
echo     Portable zip: %PORTZIP%   ^(exe at root - upload this^)
if exist "installer\Output\YouTubeToSmash-Setup.exe" echo     Installer:    installer\Output\YouTubeToSmash-Setup.exe
echo ===========================================================================
echo.
pause
goto :eof

:error
echo.
echo ===========================================================================
echo   BUILD FAILED ^(see the error above^).
echo ===========================================================================
echo.
pause
exit /b 1
