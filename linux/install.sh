#!/usr/bin/env bash
# ===========================================================================
#  Install (or uninstall) a desktop launcher for the frozen Linux app.
#
#  Per-user install (no sudo). Run AFTER ./build_linux.sh, or point it at an
#  unpacked tarball directory:
#
#      ./linux/install.sh                       # uses ./dist/YouTubeToSmash
#      ./linux/install.sh /opt/YouTubeToSmash   # uses a custom app dir
#      ./linux/install.sh --uninstall           # remove the launcher
#
#  This only registers a menu entry pointing at the app folder; it does not
#  copy the app. Move the app folder wherever you like and pass its path.
# ===========================================================================
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$HERE")"

APP_ID="yt2smash"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons"
DESKTOP_FILE="$DESKTOP_DIR/${APP_ID}.desktop"

if [[ "${1:-}" == "--uninstall" ]]; then
    rm -f "$DESKTOP_FILE" "$ICON_DIR/${APP_ID}.png"
    command -v update-desktop-database >/dev/null 2>&1 && \
        update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
    echo "Removed desktop launcher."
    exit 0
fi

APP_DIR="${1:-$PROJECT_ROOT/dist/YouTubeToSmash}"
EXEC_PATH="$APP_DIR/YouTubeToSmash"

if [[ ! -x "$EXEC_PATH" ]]; then
    echo "error: app executable not found at: $EXEC_PATH" >&2
    echo "Build it first with ./build_linux.sh, or pass the app dir as an argument." >&2
    exit 1
fi

mkdir -p "$DESKTOP_DIR" "$ICON_DIR"

# Install an icon if one is available; otherwise fall back to a generic name.
ICON_VALUE="multimedia-audio-player"
for cand in "$PROJECT_ROOT/assets/app.png" "$APP_DIR/app.png"; do
    if [[ -f "$cand" ]]; then
        cp "$cand" "$ICON_DIR/${APP_ID}.png"
        ICON_VALUE="$ICON_DIR/${APP_ID}.png"
        break
    fi
done

sed -e "s|__EXEC__|$EXEC_PATH|g" \
    -e "s|__ICON__|$ICON_VALUE|g" \
    "$HERE/yt2smash.desktop" > "$DESKTOP_FILE"
chmod 644 "$DESKTOP_FILE"

command -v update-desktop-database >/dev/null 2>&1 && \
    update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true

echo "Installed desktop launcher -> $DESKTOP_FILE"
echo "Look for \"YouTube to Smash Ultimate\" in your app menu."
