#!/usr/bin/env bash
# build_mac.sh — ScriptToVideo macOS .dmg build script
# Requires: Node.js, Python 3.10+, pip, Homebrew (for ffmpeg download)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "============================================================"
echo "  ScriptToVideo — macOS DMG Build"
echo "============================================================"
echo

# ── GitHub Token (required to publish releases with auto-update) ──────────────
#
#  To PUBLISH a release to GitHub (so users can auto-update), run:
#    GH_TOKEN=ghp_xxxxx ./build_mac.sh --publish
#
#  To build WITHOUT publishing (local .dmg only), just run:
#    ./build_mac.sh
#
#  Create your token at: https://github.com/settings/tokens
#  Required scope: "repo" (private) or "public_repo" (public)
#
PUBLISH_FLAG="never"
if [[ "${1:-}" == "--publish" ]]; then
  if [[ -z "${GH_TOKEN:-}" ]]; then
    echo "[ERROR] GH_TOKEN is not set."
    echo "        Run: GH_TOKEN=ghp_your_token ./build_mac.sh --publish"
    exit 1
  fi
  PUBLISH_FLAG="always"
  echo "[OK] GH_TOKEN found. Will publish release to GitHub."
else
  echo "[INFO] Building local .dmg only. Use --publish to upload to GitHub."
fi
echo

# ── 0. Check prerequisites ────────────────────────────────────────────────────
for cmd in node npm python3 pip3; do
  if ! command -v "$cmd" &>/dev/null; then
    echo "[ERROR] '$cmd' not found. Please install it first."
    exit 1
  fi
done
echo "[OK] Prerequisites found."
echo

# ── 1. Build React frontend ───────────────────────────────────────────────────
echo "[1/4] Building React frontend..."
cd "$SCRIPT_DIR/frontend"
npm install
npm run build
echo "[OK] Frontend built → frontend/dist"
echo

# ── 2. Install Python deps and build PyInstaller backend ─────────────────────
echo "[2/4] Building Python backend (PyInstaller)..."
cd "$SCRIPT_DIR/backend"
pip3 install -r requirements.txt -q
pip3 install pyinstaller -q
pyinstaller scriptovideo.spec --noconfirm
echo "[OK] Backend built → backend/dist/scriptovideo-backend/"
echo

# ── 3. Download / locate FFmpeg ───────────────────────────────────────────────
echo "[3/4] Checking FFmpeg..."
FFMPEG_DIR="$SCRIPT_DIR/ffmpeg_bin"
mkdir -p "$FFMPEG_DIR"

if [[ -f "$FFMPEG_DIR/ffmpeg" ]]; then
  echo "[OK] FFmpeg already present at ffmpeg_bin/ffmpeg"
elif command -v brew &>/dev/null; then
  echo "Downloading FFmpeg via Homebrew..."
  brew install ffmpeg --quiet || true
  BREW_FFMPEG="$(brew --prefix)/bin/ffmpeg"
  if [[ -f "$BREW_FFMPEG" ]]; then
    cp "$BREW_FFMPEG" "$FFMPEG_DIR/ffmpeg"
    chmod +x "$FFMPEG_DIR/ffmpeg"
    echo "[OK] FFmpeg copied from Homebrew."
  else
    echo "[WARN] Could not find Homebrew ffmpeg. Will fall back to system ffmpeg."
  fi
elif command -v ffmpeg &>/dev/null; then
  echo "Copying system ffmpeg..."
  cp "$(command -v ffmpeg)" "$FFMPEG_DIR/ffmpeg"
  chmod +x "$FFMPEG_DIR/ffmpeg"
  echo "[OK] System ffmpeg copied."
else
  echo "[WARN] FFmpeg not found. Install via: brew install ffmpeg"
  echo "       Or manually place the ffmpeg binary at: $FFMPEG_DIR/ffmpeg"
fi
echo

# ── 4. Build Electron DMG ─────────────────────────────────────────────────────
echo "[4/4] Building Electron macOS DMG..."
cd "$SCRIPT_DIR/electron"
npm install
if [[ "$PUBLISH_FLAG" == "always" ]]; then
  npx electron-builder --mac --publish always
else
  npm run build:mac
fi
echo
echo "============================================================"
echo "  BUILD COMPLETE"
echo "============================================================"
echo "  DMG: dist_electron/ScriptToVideo-*.dmg"
echo "============================================================"
