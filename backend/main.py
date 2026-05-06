import sys
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

from config import settings
from routers import audio, slides, merge, status, sync, project
from routers import settings as settings_router

app = FastAPI(
    title="ScriptToVideo API",
    description="Generate audio from scripts and combine with slides to produce videos",
    version="1.0.0",
)

# CORS — allow the React frontend to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Range", "Accept-Ranges", "Content-Length", "Content-Disposition"],
)

# Create output directories if they don't exist
for folder in [settings.audio_output_dir, settings.video_output_dir, settings.upload_dir]:
    Path(folder).mkdir(parents=True, exist_ok=True)

# Serve generated files as static downloads
app.mount("/downloads", StaticFiles(directory=settings.audio_output_dir), name="audio_downloads")
app.mount("/videos", StaticFiles(directory=settings.video_output_dir), name="video_downloads")

# Register routers
app.include_router(audio.router, prefix="/api/audio", tags=["Audio Generation"])
app.include_router(slides.router, prefix="/api/slides", tags=["Slides to Video"])
app.include_router(merge.router,  prefix="/api/merge",  tags=["Merge"])
app.include_router(status.router, prefix="/api/status", tags=["Job Status"])
app.include_router(sync.router,    prefix="/api/sync",    tags=["AI Sync"])
app.include_router(project.router,   prefix="/api/project",  tags=["Project Save/Load"])
app.include_router(settings_router.router, prefix="/api/settings", tags=["Settings"])


@app.get("/health")
def health():
    return {"status": "ok"}


# ── Serve built React frontend (packaged mode) ────────────────────────────────
# Priority order for finding the dist folder:
#   1. FRONTEND_DIST env var (set by startup.py when frozen)
#   2. Sibling frontend/dist (dev / manual build)
def _find_frontend_dist() -> Path | None:
    if os.environ.get("FRONTEND_DIST"):
        p = Path(os.environ["FRONTEND_DIST"])
        if p.exists():
            return p
    # Dev fallback: repo root's frontend/dist
    candidates = [
        Path(__file__).parent.parent / "frontend" / "dist",
        Path(__file__).parent / "frontend_dist",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None

_FRONTEND_DIST = _find_frontend_dist()

if _FRONTEND_DIST:
    # Mount /assets so hashed JS/CSS bundles are served efficiently
    _assets = _FRONTEND_DIST / "assets"
    if _assets.exists():
        app.mount("/assets", StaticFiles(directory=str(_assets)), name="spa_assets")

    @app.get("/", include_in_schema=False)
    def _spa_root():
        return FileResponse(str(_FRONTEND_DIST / "index.html"))

    @app.get("/{full_path:path}", include_in_schema=False)
    async def _spa_catch_all(full_path: str):
        """Serve React SPA — return index.html for unknown paths (client-side routing)."""
        target = _FRONTEND_DIST / full_path
        if target.exists() and target.is_file():
            return FileResponse(str(target))
        return FileResponse(str(_FRONTEND_DIST / "index.html"))
else:
    @app.get("/")
    def root():
        return {"message": "ScriptToVideo API is running. Frontend not built yet — run: cd frontend && npm run build"}
