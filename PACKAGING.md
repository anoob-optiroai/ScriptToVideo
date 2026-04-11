# ScriptToVideo — Packaging Guide

This document explains how to build the installable desktop application for Windows (.exe) and macOS (.dmg).

## Architecture

```
ScriptToVideo/
├── frontend/          React UI (Vite)
├── backend/           FastAPI + Python logic
│   ├── startup.py     PyInstaller entry point
│   └── scriptovideo.spec  PyInstaller build spec
├── electron/          Electron shell
│   ├── main.js        Electron main process
│   └── package.json   electron-builder config
├── ffmpeg_bin/        FFmpeg binary (you provide — see below)
├── build_windows.bat  One-click Windows build
└── build_mac.sh       One-click Mac build
```

The packaged app works like this:

1. **Electron** launches and shows a splash screen
2. Electron spawns the **PyInstaller-bundled Python backend** (scriptovideo-backend.exe / scriptovideo-backend)
3. Electron polls `http://127.0.0.1:8000/health` until ready (up to 60 s)
4. The main window opens at `http://127.0.0.1:8000/` (which serves the bundled React app)
5. On quit, Electron kills the backend process

---

## Prerequisites

### All platforms
- **Node.js 18+** — https://nodejs.org
- **Python 3.10+** — https://python.org
- **pip** (comes with Python)

### Windows only
- Run the build from **Command Prompt** or **PowerShell** (not Git Bash)
- FFmpeg is auto-downloaded during the build (requires internet access)

### macOS only
- **Homebrew** (recommended) — https://brew.sh — used to fetch FFmpeg
- Xcode Command Line Tools: `xcode-select --install`
- For `.icns` icon: if you have a Mac, run `./make_icns.sh` (see below)

---

## Building

### Windows — one click

```bat
build_windows.bat
```

Output: `dist_electron\ScriptToVideo Setup 1.0.0.exe`

### macOS — one click

```bash
chmod +x build_mac.sh
./build_mac.sh
```

Output: `dist_electron/ScriptToVideo-1.0.0.dmg`

---

## What the build scripts do

1. **Build React frontend** — `cd frontend && npm run build` → `frontend/dist/`
2. **Build Python backend** — `pyinstaller scriptovideo.spec` → `backend/dist/scriptovideo-backend/`
3. **Copy FFmpeg** — places `ffmpeg[.exe]` into `ffmpeg_bin/`
4. **Build Electron installer** — `electron-builder --win` or `--mac`
   - Copies `backend/dist/scriptovideo-backend/` → `resources/backend/`
   - Copies `ffmpeg_bin/` → `resources/ffmpeg/`
   - Produces final installer

---

## macOS Icon (.icns)

Electron-builder will use `electron/assets/icon.png` if `icon.icns` is absent, but the quality is better with a proper `.icns`. On a Mac:

```bash
mkdir ScriptToVideo.iconset
sips -z 16 16     electron/assets/icon.png --out ScriptToVideo.iconset/icon_16x16.png
sips -z 32 32     electron/assets/icon.png --out ScriptToVideo.iconset/icon_16x16@2x.png
sips -z 32 32     electron/assets/icon.png --out ScriptToVideo.iconset/icon_32x32.png
sips -z 64 64     electron/assets/icon.png --out ScriptToVideo.iconset/icon_32x32@2x.png
sips -z 128 128   electron/assets/icon.png --out ScriptToVideo.iconset/icon_128x128.png
sips -z 256 256   electron/assets/icon.png --out ScriptToVideo.iconset/icon_128x128@2x.png
sips -z 256 256   electron/assets/icon.png --out ScriptToVideo.iconset/icon_256x256.png
sips -z 512 512   electron/assets/icon.png --out ScriptToVideo.iconset/icon_256x256@2x.png
cp electron/assets/icon.png ScriptToVideo.iconset/icon_512x512.png
iconutil -c icns ScriptToVideo.iconset -o electron/assets/icon.icns
rm -rf ScriptToVideo.iconset
```

---

## Auto-Update (Online Updates)

ScriptToVideo includes automatic update support via **electron-updater** and **GitHub Releases**. When a new version is published, users are notified inside the app and can install the update with one click.

### How it works

1. 3 seconds after the app opens, it silently checks GitHub for a newer version
2. It also checks every 4 hours while the app is running
3. If a new version is found, a dialog appears:
   > *"ScriptToVideo 1.2.0 is available — Download Update / Later"*
4. While downloading, a progress banner appears at the bottom of the app
5. When done:
   > *"Update Ready — Restart & Install / Later"*
6. Clicking **Restart & Install** closes the app, installs the update, and relaunches
7. Users can also manually check: **Help → Check for Updates…**

### One-time setup — point to your GitHub repo

Open `electron/package.json` and replace `YOUR_GITHUB_USERNAME`:

```json
"publish": {
  "provider": "github",
  "owner":    "YOUR_GITHUB_USERNAME",
  "repo":     "ScriptToVideo",
  "releaseType": "release"
}
```

### How to release a new version

**Step 1 — bump the version** in `electron/package.json`:
```json
"version": "1.1.0"
```

**Step 2 — create a GitHub Personal Access Token**

Go to https://github.com/settings/tokens → "Generate new token (classic)"
- Required scope: `public_repo` (public repo) or `repo` (private repo)
- Copy the token (starts with `ghp_…`)

**Step 3 — build and publish**

Windows:
```bat
set GH_TOKEN=ghp_your_token_here
build_windows.bat --publish
```

Mac:
```bash
GH_TOKEN=ghp_your_token_here ./build_mac.sh --publish
```

This will:
- Build the installer as normal
- Automatically create a GitHub Release tagged `v1.1.0`
- Upload the `.exe` / `.dmg` + update metadata files (`latest.yml`, `latest-mac.yml`)

**Step 4 — publish the draft release on GitHub**

After the build, go to your GitHub repo → Releases → find the draft release → click **Publish release**. Users running the app will be notified within 4 hours (or immediately if they use Help → Check for Updates).

### Building locally without publishing

Simply run the build scripts without `--publish` — this produces an installer you can share manually, but installed copies won't auto-update from it.

---

## API Keys

After installation, the app creates a config file on first launch:

- **Windows:** `%APPDATA%\ScriptToVideo\.env`
- **macOS:** `~/Library/Application Support/ScriptToVideo/.env`

Edit this file to add your API keys:

```ini
TTS_PROVIDER=elevenlabs       # or "openai" or "google"
ELEVENLABS_API_KEY=sk-...
OPENAI_API_KEY=sk-...
GOOGLE_CLOUD_API_KEY=...
```

You can also open this file from the app menu: **File → Open Config (.env)**

---

## Output Files

Generated videos and audio are saved to:

- **Windows:** `%APPDATA%\ScriptToVideo\outputs\`
- **macOS:** `~/Library/Application Support/ScriptToVideo/outputs/`

Open this folder from the app menu: **File → Open Outputs Folder**

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Backend did not start" | Check port 8000 isn't in use: `netstat -ano \| findstr 8000` (Win) or `lsof -i:8000` (Mac) |
| Missing backend executable | Re-run the build script. Check `backend/dist/scriptovideo-backend/` exists |
| FFmpeg errors | Ensure `ffmpeg_bin/ffmpeg[.exe]` exists. Run `ffmpeg -version` to verify |
| LibreOffice not found | Install LibreOffice from https://www.libreoffice.org — the app detects it automatically |
| API key errors | Edit the `.env` file (File → Open Config) and restart the app |
| App won't open on Mac (security warning) | Right-click the app → Open, or run: `xattr -dr com.apple.quarantine /Applications/ScriptToVideo.app` |

---

## Development Mode

Run backend and frontend separately (no Electron needed):

```bash
# Terminal 1 — backend
cd backend
pip install -r requirements.txt
uvicorn main:app --reload

# Terminal 2 — frontend
cd frontend
npm install
npm run dev
```

Then open http://localhost:5173 in your browser.

To run with Electron in dev mode:
```bash
cd electron
npm install
NODE_ENV=development npx electron .
```
