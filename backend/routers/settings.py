"""
Settings router — read and write the user's .env file (API keys, TTS provider).
Used by the in-app Settings panel so team members don't have to edit files manually.
"""
import os
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

router = APIRouter()

# ── Locate the .env file ─────────────────────────────────────────────────────
def _env_path() -> Path:
    """Return the path to the active .env file."""
    # In packaged mode startup.py sets ENV_FILE
    env_file = os.environ.get("ENV_FILE")
    if env_file and Path(env_file).exists():
        return Path(env_file)
    # Dev fallback
    here = Path(__file__).parent.parent
    for candidate in [here / ".env", here.parent / "backend" / ".env"]:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("Cannot locate .env file")


def _read_env() -> dict:
    """Parse the .env file into a dict."""
    try:
        path = _env_path()
        values = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, _, v = line.partition("=")
                values[k.strip()] = v.strip()
        return values
    except FileNotFoundError:
        return {}


def _write_key(key: str, value: str):
    """Update or add a single key in the .env file."""
    path = _env_path()
    text = path.read_text(encoding="utf-8")
    pattern = rf"^({re.escape(key)}\s*=).*$"
    replacement = rf"\g<1>{value}"
    new_text, count = re.subn(pattern, replacement, text, flags=re.MULTILINE)
    if count == 0:
        # Key not present — append it
        new_text = text.rstrip() + f"\n{key}={value}\n"
    path.write_text(new_text, encoding="utf-8")


# ── Models ────────────────────────────────────────────────────────────────────

class SettingsResponse(BaseModel):
    tts_provider: str
    elevenlabs_api_key: str
    openai_api_key: str
    google_cloud_api_key: str
    gemini_api_key: str
    google_docs_api_key: str
    env_file_path: str
    is_configured: bool   # True if at least one TTS key is set


class SettingsUpdate(BaseModel):
    tts_provider: Optional[str] = None
    elevenlabs_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    google_cloud_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    google_docs_api_key: Optional[str] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=SettingsResponse)
def get_settings():
    """Return current settings (API keys masked after first 8 chars)."""
    env = _read_env()

    def mask(v: str) -> str:
        if not v:
            return ""
        return v[:8] + "*" * max(0, len(v) - 8) if len(v) > 8 else v

    el_key = env.get("ELEVENLABS_API_KEY", "")
    oa_key = env.get("OPENAI_API_KEY", "")
    gc_key = env.get("GOOGLE_CLOUD_API_KEY", "")
    gm_key = env.get("GEMINI_API_KEY", "")

    try:
        env_path = str(_env_path())
    except FileNotFoundError:
        env_path = "Not found"

    return SettingsResponse(
        tts_provider=env.get("TTS_PROVIDER", "elevenlabs"),
        elevenlabs_api_key=mask(el_key),
        openai_api_key=mask(oa_key),
        google_cloud_api_key=mask(gc_key),
        gemini_api_key=mask(gm_key),
        google_docs_api_key=mask(env.get("GOOGLE_DOCS_API_KEY", "")),
        env_file_path=env_path,
        is_configured=bool(el_key or oa_key or gc_key or gm_key),
    )


@router.post("")
def update_settings(body: SettingsUpdate):
    """Update one or more settings in the .env file."""
    try:
        _env_path()  # ensure file exists
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=".env file not found")

    mapping = {
        "tts_provider":        ("TTS_PROVIDER",          body.tts_provider),
        "elevenlabs_api_key":  ("ELEVENLABS_API_KEY",    body.elevenlabs_api_key),
        "openai_api_key":      ("OPENAI_API_KEY",         body.openai_api_key),
        "google_cloud_api_key":("GOOGLE_CLOUD_API_KEY",  body.google_cloud_api_key),
        "gemini_api_key":      ("GEMINI_API_KEY",         body.gemini_api_key),
        "google_docs_api_key": ("GOOGLE_DOCS_API_KEY",   body.google_docs_api_key),
    }

    for _field, (env_key, val) in mapping.items():
        if val is not None:
            _write_key(env_key, val)

    return {"status": "ok", "message": "Settings saved. Restart the app to apply changes."}
