@echo off
REM ===========================================================================
REM  FAST rebuild: re-freeze the app + (if available) re-build the installer,
REM  WITHOUT re-downloading the bundled tools. Use this when you've only changed
REM  Python source (the tools already in bin\ are reused as-is).
REM
REM  For a clean first build (which also downloads the tools), use
REM  build_windows.bat instead.
REM ===========================================================================
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
set "APPVER=1.0.0"

set "PY="
for %%V in (3.12 3.11) do (
    if not defined PY ( py -%%V -c "import sys" >nul 2>nul && set "PY=py -%%V" )
)
if not defined PY (
    python -c "import sys; raise SystemExit(0 if (3,11)<=sys.version_info[:2]<=(3,12) else 1)" >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo ERROR: Need Python 3.11 or 3.12 on PATH. & pause & exit /b 1
)

echo [0/3] Closing any running app and clearing old build folders...
REM A running YouTubeToSmash.exe locks files in dist\ and makes COLLECT fail with
REM "Access is denied". Close it (and the console CLI) before rebuilding.
taskkill /f /im YouTubeToSmash.exe  >nul 2>nul
taskkill /f /im yt2smash-cli.exe    >nul 2>nul
REM Give the OS a moment to release the file handles, then remove old outputs.
ping -n 2 127.0.0.1 >nul
if exist dist  rmdir /s /q dist  2>nul
if exist build rmdir /s /q build 2>nul
if exist dist (
    echo.
    echo   Could not remove dist\ -- a file there is still locked.
    echo   Close the app, any "Couldn't build the audio file" dialog, and any
    echo   Explorer window open inside dist\, then run this again.
    echo.
    pause & exit /b 1
)

echo [1/4] Preflight: tools resolve?
%PY% cli.py --check

echo.
echo [2/4] Freezing with PyInstaller...
%PY% -m PyInstaller --noconfirm --clean yt2smash.spec || (echo BUILD FAILED & pause & exit /b 1)
echo   -^> dist\YouTubeToSmash\YouTubeToSmash.exe

echo.
echo [3/4] Installer (if Inno Setup present)...
set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%ISCC%" ( "%ISCC%" installer\yt2smash.iss ) else ( echo   Inno Setup not found - skipped. )

echo.
echo [4/4] Packaging the portable zip ^(EXE at the root^)...
set "PORTZIP=YouTubeToSmash-v%APPVER%-windows-x64.zip"
if exist "%PORTZIP%" del /q "%PORTZIP%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path 'dist\YouTubeToSmash\*' -DestinationPath '%PORTZIP%' -Force" || (echo ZIP FAILED & pause & exit /b 1)
echo   -^> %PORTZIP%

echo.
echo Done.
echo   Run:          dist\YouTubeToSmash\YouTubeToSmash.exe
echo   Portable zip: %PORTZIP%   ^(exe at root - upload this^)
echo.
pause
