"""
Project save / load router.

Projects are stored as JSON files in the video output directory so they
survive backend restarts.  Each project captures everything needed to
resume work without re-uploading or re-running AI: audio file, slides
video, per-slide timing, sync debug table and UI settings.
"""
import os
import json
from uuid import uuid4
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import settings

router = APIRouter()

_PROJECTS_DIR = Path(settings.video_output_dir) / "projects"


def _ensure_dir():
    _PROJECTS_DIR.mkdir(parents=True, exist_ok=True)


# ── Pydantic models ───────────────────────────────────────────────────────────

class ProjectState(BaseModel):
    project_name:  str = "Untitled Project"
    audio_result:  Optional[Dict[str, Any]] = None
    slides_result: Optional[Dict[str, Any]] = None
    slide_times:   Optional[List[float]]    = None
    sync_mode:     str = "auto_fit"
    debug_info:    Optional[List[Dict[str, Any]]] = None   # per-slide timing table


class ProjectMeta(BaseModel):
    project_id:   str
    project_name: str
    saved_at:     str
    slide_count:  int
    audio_file:   str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _project_path(project_id: str) -> Path:
    return _PROJECTS_DIR / f"{project_id}.json"


def _list_projects() -> List[Dict]:
    _ensure_dir()
    projects = []
    for p in sorted(_PROJECTS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            projects.append({
                "project_id":   p.stem,
                "project_name": data.get("project_name", "Untitled"),
                "saved_at":     data.get("saved_at", ""),
                "slide_count":  data.get("slides_result", {}).get("slide_count", 0) if data.get("slides_result") else 0,
                "audio_file":   data.get("audio_result", {}).get("filename", "") if data.get("audio_result") else "",
            })
        except Exception:
            pass
    return projects


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/save")
async def save_project(state: ProjectState):
    """Save the current project state. Returns a project_id for later loading."""
    _ensure_dir()
    project_id = str(uuid4())[:8]
    data = state.dict()
    data["saved_at"] = datetime.now(timezone.utc).isoformat()
    data["project_id"] = project_id
    with open(_project_path(project_id), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return {"project_id": project_id, "saved_at": data["saved_at"]}


@router.put("/save/{project_id}")
async def update_project(project_id: str, state: ProjectState):
    """Overwrite an existing project (Save button when already saved)."""
    _ensure_dir()
    path = _project_path(project_id)
    data = state.dict()
    data["saved_at"] = datetime.now(timezone.utc).isoformat()
    data["project_id"] = project_id
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return {"project_id": project_id, "saved_at": data["saved_at"]}


@router.get("/list")
async def list_projects():
    """Return a list of saved projects (newest first)."""
    return {"projects": _list_projects()}


@router.get("/load/{project_id}")
async def load_project(project_id: str):
    """Load a saved project by ID."""
    path = _project_path(project_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found.")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


@router.delete("/delete/{project_id}")
async def delete_project(project_id: str):
    """Delete a saved project."""
    path = _project_path(project_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found.")
    path.unlink()
    return {"deleted": project_id}
