# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for ScriptToVideo backend.

Build with:
    cd backend
    pyinstaller scriptovideo.spec

Output: backend/dist/scriptovideo-backend/  (one-dir bundle)
"""

import sys
from pathlib import Path

HERE = Path(SPECPATH)  # backend/
ROOT = HERE.parent     # repo root

# ── Data files bundled into the package ──────────────────────────────────────
datas = [
    # Built React frontend (run `cd frontend && npm run build` first)
    (str(ROOT / "frontend" / "dist"),   "frontend_dist"),
    # .env template (copied to user-data on first run)
    (str(HERE / ".env.template"),       "."),
]

# ── Hidden imports needed by uvicorn / FastAPI / pydantic ─────────────────────
hidden_imports = [
    # uvicorn internals
    "uvicorn.logging",
    "uvicorn.loops", "uvicorn.loops.auto", "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan", "uvicorn.lifespan.on", "uvicorn.lifespan.off",
    # FastAPI / Starlette
    "starlette.routing", "starlette.staticfiles", "starlette.responses",
    # Pydantic
    "pydantic", "pydantic_settings", "pydantic.deprecated.class_validators",
    # multipart (file uploads)
    "multipart", "python_multipart",
    # Pillow
    "PIL", "PIL._imaging", "PIL.Image", "PIL.ImageDraw", "PIL.ImageFont",
    # numpy (used by waveform / animation code)
    "numpy",
    # email (used by some dependencies)
    "email.mime.multipart", "email.mime.text",
    # Google TTS / OpenAI / ElevenLabs
    "google.cloud.texttospeech", "openai", "elevenlabs",
    # requests
    "requests", "urllib3",
    # aiofiles
    "aiofiles",
]

a = Analysis(
    [str(HERE / "startup.py")],
    pathex=[str(HERE)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "scipy", "pandas", "jupyter"],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="scriptovideo-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,   # Keep console visible for debugging; set False for silent
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="scriptovideo-backend",
)
