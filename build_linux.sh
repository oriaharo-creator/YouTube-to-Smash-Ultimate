#!/usr/bin/env bash
# ===========================================================================
#  Build the YouTube -> Smash Ultimate Linux app (one-folder + tarball).
#
#  Run this from the project root on Ubuntu (or another glibc Linux):
#      ./build_linux.sh
#
#  Prerequisites:
#    * Python 3.11 or 3.12 on PATH (NOT 3.13 - pydub needs the audioop module)
#    * bin/ populated with the Linux tools (see bin/README.txt):
#        ffmpeg, ffprobe          (native ELF binaries, or install via apt)
#        VGAudioCli.exe           (run through mono; install `mono-runtime`)
#        nus3audio                (native ELF binary)
#    * (optional) assets/app.png for the desktop launcher icon
# ===========================================================================
set -euo pipefail

cd "$(dirname "$0")"

PY="${PYTHON:-python3}"

echo
echo "[1/3] Installing build dependencies..."
"$PY" -m pip install -r requirements-build.txt

echo
echo "[2/3] Preflight: checking bundled tools resolve..."
if ! "$PY" cli.py --check; then
    echo
    echo "  WARNING: not all tools were found. The app will build but conversions"
    echo "  will fail until bin/ is populated. See bin/README.txt."
    echo
fi

echo
echo "[3/3] Freezing with PyInstaller (one-folder)..."
"$PY" -m PyInstaller --noconfirm --clean yt2smash.spec
echo "  -> dist/YouTubeToSmash/YouTubeToSmash"

# --- Bundle the desktop-launcher installer alongside the app --------------
# So the released tarball is self-contained: users can run install.sh from the
# unpacked folder to register a menu entry.
cp linux/install.sh linux/yt2smash.desktop dist/YouTubeToSmash/ 2>/dev/null || true
[ -f assets/app.png ] && cp assets/app.png dist/YouTubeToSmash/ || true

# --- Package a distributable tarball --------------------------------------
VERSION="${VERSION:-$(git describe --tags --always 2>/dev/null || echo dev)}"
TARBALL="dist/YouTubeToSmash-${VERSION}-linux-x86_64.tar.gz"
echo
echo "Packaging ${TARBALL} ..."
tar -C dist -czf "$TARBALL" YouTubeToSmash
echo "  -> ${TARBALL}"

echo
echo "Done."
echo "Run it with:   ./dist/YouTubeToSmash/YouTubeToSmash"
echo "Install a desktop launcher with:   ./linux/install.sh"
