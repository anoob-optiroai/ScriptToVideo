"""
startup.py — PyInstaller entry point for the packaged desktop app.

When frozen (PyInstaller), this script:
  1. Resolves paths for outputs, uploads, ffmpeg, LibreOffice, and the
     embedded React frontend into the user's app-data directory.
  2. Copies the default .env template if none exists (so API keys can be set).
  3. Launches the FastAPI/uvicorn server on 127.0.0.1:8000.

In development, run the app normally via:
    uvicorn main:app --reload
"""
import sys
import os
from pathlib import Path


def _setup_packaged_paths():
    """Configure environment variables for the PyInstaller bundle."""
    # The directory containing the bundled files (_MEIPASS)
    bundle_dir = Path(sys._MEIPASS)

    # ── User-data directory (writable, persists between runs) ─────────────────
    if sys.platform == "win32":
        app_data = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "ScriptToVideo"
    elif sys.platform == "darwin":
        app_data = Path.home() / "Library" / "Application Support" / "ScriptToVideo"
    else:
        app_data = Path.home() / ".scripttovideo"

    for sub in ["outputs/audio", "outputs/video", "uploads"]:
        (app_data / sub).mkdir(parents=True, exist_ok=True)

    # ── Output / upload dirs ──────────────────────────────────────────────────
    os.environ.setdefault("AUDIO_OUTPUT_DIR", str(app_data / "outputs" / "audio"))
    os.environ.setdefault("VIDEO_OUTPUT_DIR", str(app_data / "outputs" / "video"))
    os.environ.setdefault("UPLOAD_DIR",        str(app_data / "uploads"))

    # ── Embedded React frontend ───────────────────────────────────────────────
    os.environ.setdefault("FRONTEND_DIST", str(bundle_dir / "frontend_dist"))

    # ── FFmpeg binary (bundled alongside the app) ─────────────────────────────
    ffmpeg_ext  = ".exe" if sys.platform == "win32" else ""
    ffmpeg_path = bundle_dir / "ffmpeg" / f"ffmpeg{ffmpeg_ext}"
    if ffmpeg_path.exists():
        os.environ.setdefault("FFMPEG_BINARY", str(ffmpeg_path))

    # ── LibreOffice (check bundled, then well-known system locations) ─────────
    if sys.platform == "win32":
        lo_candidates = [
            bundle_dir / "LibreOffice" / "program" / "soffice.exe",
            Path("C:/Program Files/LibreOffice/program/soffice.exe"),
            Path("C:/Program Files (x86)/LibreOffice/program/soffice.exe"),
        ]
    elif sys.platform == "darwin":
        lo_candidates = [
            bundle_dir / "LibreOffice" / "program" / "soffice",
            Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"),
        ]
    else:
        lo_candidates = [Path("/usr/bin/soffice"), Path("/usr/lib/libreoffice/program/soffice")]

    for lo in lo_candidates:
        if lo.exists():
            os.environ.setdefault("LIBREOFFICE_BINARY", str(lo))
            break

    # ── .env file for API keys ────────────────────────────────────────────────
    env_file = app_data / ".env"
    env_template = bundle_dir / ".env.template"
    if not env_file.exists() and env_template.exists():
        import shutil
        shutil.copy2(str(env_template), str(env_file))

    # Point pydantic-settings to the user's .env
    os.environ.setdefault("ENV_FILE", str(env_file))

    # Run from the user-data directory so relative paths resolve correctly
    os.chdir(str(app_data))

    print(f"[ScriptToVideo] App data: {app_data}")
    print(f"[ScriptToVideo] Bundle:   {bundle_dir}")


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if getattr(sys, "frozen", False):
        _setup_packaged_paths()

    import uvicorn
    # Import app AFTER setting env vars so config picks them up
    from main import app  # noqa: F401

    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        log_level="info",
        # No --reload in packaged mode
        reload=False,
    )
