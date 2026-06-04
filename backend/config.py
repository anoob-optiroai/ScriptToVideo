from pydantic_settings import BaseSettings
from typing import List
import os


class Settings(BaseSettings):
    # TTS Provider: "elevenlabs", "openai", or "google"
    tts_provider: str = "elevenlabs"

    # API Keys (set in .env file)
    elevenlabs_api_key: str = ""
    openai_api_key: str = ""
    google_cloud_api_key: str = ""
    gemini_api_key: str = ""

    # Google Docs API (for importing from Google Docs URLs)
    google_docs_api_key: str = ""

    # Output directories — startup.py overrides these via env vars when packaged
    audio_output_dir: str = os.environ.get("AUDIO_OUTPUT_DIR", "outputs/audio")
    video_output_dir: str = os.environ.get("VIDEO_OUTPUT_DIR", "outputs/video")
    upload_dir:       str = os.environ.get("UPLOAD_DIR",       "uploads")

    # CORS — keep dev origins; packaged app is same-origin so CORS not strictly needed
    cors_origins: List[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8000",
    ]

    # FFmpeg — overridden to bundled binary path by startup.py when packaged
    ffmpeg_binary: str = os.environ.get("FFMPEG_BINARY", "ffmpeg")

    # LibreOffice — overridden to detected/bundled path by startup.py when packaged
    libreoffice_binary: str = os.environ.get("LIBREOFFICE_BINARY", "libreoffice")

    # Max upload size in MB
    max_upload_size_mb: int = 50

    class Config:
        # startup.py sets ENV_FILE to the user-data .env when packaged
        env_file = os.environ.get("ENV_FILE", ".env")
        env_file_encoding = "utf-8"


settings = Settings()
