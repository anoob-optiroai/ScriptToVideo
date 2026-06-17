"""
Audio generation router.
Accepts: Google Doc URL, Word file upload (.docx), or plain text.
Returns: job_id for polling, plus the final .mp3 URL when done.
"""
import os
import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks

from config import settings
from job_store import job_store

router = APIRouter()

# ── Static voice lists for non-ElevenLabs providers ─────────────────────────

OPENAI_VOICES = [
    {"id": "alloy",   "name": "Alloy (Neutral)"},
    {"id": "echo",    "name": "Echo (Male)"},
    {"id": "fable",   "name": "Fable (British)"},
    {"id": "onyx",    "name": "Onyx (Male, deep)"},
    {"id": "nova",    "name": "Nova (Female, warm)"},
    {"id": "shimmer", "name": "Shimmer (Female, soft)"},
]

GOOGLE_VOICES = [
    {"id": "en-US", "name": "English (US)"},
    {"id": "en-GB", "name": "English (UK)"},
    {"id": "en-AU", "name": "English (Australia)"},
]

# Full Gemini TTS voice list (gemini-2.5-flash-preview-tts)
# Organised: Neutral/Male/Female with character descriptions
GEMINI_VOICES = [
    # ── Bright / Upbeat ──────────────────────────────────────────────────────
    {"id": "Zephyr",       "name": "Zephyr — Bright"},
    {"id": "Puck",         "name": "Puck — Upbeat"},
    {"id": "Leda",         "name": "Leda — Youthful"},
    {"id": "Autonoe",      "name": "Autonoe — Bright"},
    {"id": "Laomedeia",    "name": "Laomedeia — Upbeat"},
    {"id": "Sadachbia",    "name": "Sadachbia — Lively"},
    # ── Calm / Easy-going ────────────────────────────────────────────────────
    {"id": "Aoede",        "name": "Aoede — Breezy"},
    {"id": "Callirrhoe",   "name": "Callirrhoe — Easy-going"},
    {"id": "Umbriel",      "name": "Umbriel — Easy-going"},
    {"id": "Zubenelgenubi","name": "Zubenelgenubi — Casual"},
    {"id": "Vindemiatrix", "name": "Vindemiatrix — Gentle"},
    {"id": "Sulafat",      "name": "Sulafat — Warm"},
    {"id": "Achird",       "name": "Achird — Friendly"},
    # ── Informative / Clear ───────────────────────────────────────────────────
    {"id": "Charon",       "name": "Charon — Informative"},
    {"id": "Rasalgethi",   "name": "Rasalgethi — Informative"},
    {"id": "Iapetus",      "name": "Iapetus — Clear"},
    {"id": "Erinome",      "name": "Erinome — Clear"},
    {"id": "Sadaltager",   "name": "Sadaltager — Knowledgeable"},
    # ── Firm / Authoritative ─────────────────────────────────────────────────
    {"id": "Kore",         "name": "Kore — Firm"},
    {"id": "Orus",         "name": "Orus — Firm"},
    {"id": "Alnilam",      "name": "Alnilam — Firm"},
    {"id": "Fenrir",       "name": "Fenrir — Excitable"},
    {"id": "Pulcherrima",  "name": "Pulcherrima — Forward"},
    # ── Smooth / Deep ─────────────────────────────────────────────────────────
    {"id": "Algieba",      "name": "Algieba — Smooth"},
    {"id": "Despina",      "name": "Despina — Smooth"},
    {"id": "Algenib",      "name": "Algenib — Gravelly"},
    {"id": "Gacrux",       "name": "Gacrux — Mature"},
    {"id": "Schedar",      "name": "Schedar — Even"},
    {"id": "Achernar",     "name": "Achernar — Soft"},
    {"id": "Enceladus",    "name": "Enceladus — Breathy"},
]


ELEVENLABS_MODELS = [
    {"id": "eleven_multilingual_v2", "name": "Multilingual v2 — High Quality",  "cost": "$0.10/1K chars"},
    {"id": "eleven_flash_v2_5",      "name": "Flash v2.5 — Fast & Cheap",        "cost": "$0.05/1K chars"},
    {"id": "eleven_turbo_v2_5",      "name": "Turbo v2.5 — Balanced",            "cost": "$0.05/1K chars"},
]


def fetch_elevenlabs_voices():
    """Fetch voices from the user's ElevenLabs account, including preview URLs."""
    import requests
    # Read key fresh from .env each time so saving in Settings works without restarting
    try:
        from routers.settings import _read_env
        api_key = _read_env().get("ELEVENLABS_API_KEY", "") or settings.elevenlabs_api_key
    except Exception:
        api_key = settings.elevenlabs_api_key
    try:
        response = requests.get(
            "https://api.elevenlabs.io/v1/voices",
            headers={"xi-api-key": api_key},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        voices = []
        for v in data.get("voices", []):
            label = v.get("name", "Unknown")
            category = v.get("category", "")
            if category:
                label = f"{label} ({category})"
            voices.append({
                "id":          v["voice_id"],
                "name":        label,
                "preview_url": v.get("preview_url", ""),
            })
        return voices if voices else [{"id": "", "name": "No voices found", "preview_url": ""}]
    except Exception as e:
        return [{"id": "", "name": f"Could not load voices: {e}", "preview_url": ""}]


@router.post("/test-key")
def test_elevenlabs_key(body: dict):
    """Test an ElevenLabs API key and return voice count or error."""
    import requests as _requests
    key = (body.get("api_key") or "").strip()
    if not key:
        # Test the currently saved key
        try:
            from routers.settings import _read_env
            key = _read_env().get("ELEVENLABS_API_KEY", "") or settings.elevenlabs_api_key
        except Exception:
            key = settings.elevenlabs_api_key
    if not key:
        return {"ok": False, "error": "No API key saved. Enter your key in the field above and click Save first."}
    try:
        r = _requests.get(
            "https://api.elevenlabs.io/v1/voices",
            headers={"xi-api-key": key},
            timeout=10,
        )
        r.raise_for_status()
        count = len(r.json().get("voices", []))
        return {"ok": True, "voices": count, "message": f"Connected — {count} voices available"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/config")
def get_audio_config():
    """Return the current TTS provider, voices (with preview URLs), and available models."""
    # Read provider fresh from .env so Settings changes take effect without restart
    try:
        from routers.settings import _read_env
        provider = (_read_env().get("TTS_PROVIDER", "") or settings.tts_provider).lower()
    except Exception:
        provider = settings.tts_provider.lower()

    if provider == "elevenlabs":
        voices = fetch_elevenlabs_voices()
    elif provider == "openai":
        voices = OPENAI_VOICES
    elif provider == "google":
        voices = GOOGLE_VOICES
    elif provider == "gemini":
        voices = GEMINI_VOICES
    else:
        voices = OPENAI_VOICES

    models        = ELEVENLABS_MODELS if provider == "elevenlabs" else []
    default_model = ELEVENLABS_MODELS[0]["id"] if provider == "elevenlabs" else ""

    return {
        "provider":      provider,
        "voices":        voices,
        "default_voice": voices[0]["id"] if voices else "",
        "models":        models,
        "default_model": default_model,
    }


# ── Text extraction helpers ──────────────────────────────────────────────────

def extract_text_from_docx(file_bytes: bytes) -> str:
    from docx import Document
    import io
    doc = Document(io.BytesIO(file_bytes))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def extract_text_from_google_doc(url: str) -> str:
    import requests
    match = re.search(r"/d/([a-zA-Z0-9_-]+)", url)
    if not match:
        raise ValueError("Could not extract Google Doc ID from URL")
    doc_id = match.group(1)
    export_url = f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
    response = requests.get(export_url, timeout=30)
    response.raise_for_status()
    return response.text


# ── Text chunking ────────────────────────────────────────────────────────────

def split_text_into_chunks(text: str, max_chars: int = 9500) -> list:
    """
    Split text into chunks of max_chars, breaking only at sentence boundaries.
    This avoids the ElevenLabs 10,000 character limit per request.
    """
    # Split into sentences
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    chunks = []
    current = ""
    for sentence in sentences:
        # If a single sentence is too long, split it at commas/newlines
        if len(sentence) > max_chars:
            parts = re.split(r'(?<=,)\s+|\n', sentence)
            for part in parts:
                if len(current) + len(part) + 1 <= max_chars:
                    current += (" " if current else "") + part
                else:
                    if current:
                        chunks.append(current.strip())
                    current = part
        elif len(current) + len(sentence) + 1 <= max_chars:
            current += (" " if current else "") + sentence
        else:
            if current:
                chunks.append(current.strip())
            current = sentence
    if current:
        chunks.append(current.strip())
    return chunks


def concatenate_audio_files(chunk_paths: list, output_path: str):
    """Join multiple MP3 chunks into one file using FFmpeg."""
    import subprocess

    # Always use absolute paths so FFmpeg doesn't resolve them relative to the
    # list file's directory (which would double the path on Windows).
    abs_output = os.path.abspath(output_path)
    abs_chunks = [os.path.abspath(p) for p in chunk_paths]

    list_file = abs_output + "_list.txt"
    with open(list_file, "w", encoding="utf-8") as f:
        for p in abs_chunks:
            # Forward slashes keep FFmpeg happy on Windows
            f.write("file '{}'\n".format(p.replace("\\", "/")))

    cmd = [
        settings.ffmpeg_binary, "-y",
        "-f", "concat", "-safe", "0",
        "-i", list_file,
        "-c", "copy",
        abs_output,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    try:
        os.remove(list_file)
    except Exception:
        pass
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg concat error: {result.stderr[-300:]}")


# ── TTS providers ────────────────────────────────────────────────────────────

def tts_elevenlabs_chunk(text: str, voice_id: str, output_path: str,
                         model: str = "eleven_multilingual_v2"):
    """Send one chunk to ElevenLabs (max 9500 chars)."""
    import requests
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": settings.elevenlabs_api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "text": text,
        "model_id": model,
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }
    response = requests.post(url, json=payload, headers=headers, timeout=120)
    if not response.ok:
        try:
            detail = response.json().get("detail", {})
            msg = detail.get("message", response.text) if isinstance(detail, dict) else str(detail)
        except Exception:
            msg = response.text
        raise RuntimeError(f"ElevenLabs error {response.status_code}: {msg}")
    with open(output_path, "wb") as f:
        f.write(response.content)


def tts_elevenlabs(text: str, voice_id: str, output_path: str, job=None,
                   model: str = "eleven_multilingual_v2"):
    """Split long text into chunks and concatenate audio output."""
    chunks = split_text_into_chunks(text, max_chars=9500)
    if len(chunks) == 1:
        tts_elevenlabs_chunk(chunks[0], voice_id, output_path, model)
        return

    chunk_paths = []
    base = output_path.replace(".mp3", "")
    for i, chunk in enumerate(chunks):
        if job:
            pct = 30 + int((i / len(chunks)) * 60)
            job.update(progress=pct, message=f"Generating audio part {i+1} of {len(chunks)}...")
        chunk_path = f"{base}_part{i}.mp3"
        tts_elevenlabs_chunk(chunk, voice_id, chunk_path, model)
        chunk_paths.append(chunk_path)

    concatenate_audio_files(chunk_paths, output_path)

    for p in chunk_paths:
        try:
            os.remove(p)
        except Exception:
            pass


def tts_openai_chunk(text: str, voice: str, output_path: str, speed: float = 1.0):
    """Send one chunk to OpenAI TTS (max 4000 chars)."""
    from openai import OpenAI
    client = OpenAI(api_key=settings.openai_api_key)
    response = client.audio.speech.create(
        model="tts-1-hd",
        voice=voice,
        input=text,
        speed=speed,
    )
    response.stream_to_file(output_path)


def tts_openai(text: str, voice: str, output_path: str, speed: float = 1.0, job=None):
    """Split long text into chunks and concatenate audio output."""
    chunks = split_text_into_chunks(text, max_chars=4000)
    if len(chunks) == 1:
        tts_openai_chunk(chunks[0], voice, output_path, speed)
        return

    chunk_paths = []
    base = output_path.replace(".mp3", "")
    for i, chunk in enumerate(chunks):
        if job:
            pct = 30 + int((i / len(chunks)) * 60)
            job.update(progress=pct, message=f"Generating audio part {i+1} of {len(chunks)}...")
        chunk_path = f"{base}_part{i}.mp3"
        tts_openai_chunk(chunk, voice, chunk_path, speed)
        chunk_paths.append(chunk_path)

    concatenate_audio_files(chunk_paths, output_path)

    # Clean up chunk files
    for p in chunk_paths:
        try:
            os.remove(p)
        except Exception:
            pass


def tts_google(text: str, language_code: str, output_path: str):
    from google.cloud import texttospeech
    client = texttospeech.TextToSpeechClient()
    synthesis_input = texttospeech.SynthesisInput(text=text)
    voice = texttospeech.VoiceSelectionParams(
        language_code=language_code,
        ssml_gender=texttospeech.SsmlVoiceGender.NEUTRAL,
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3
    )
    response = client.synthesize_speech(
        input=synthesis_input, voice=voice, audio_config=audio_config
    )
    with open(output_path, "wb") as f:
        f.write(response.audio_content)


def _sanitize_for_tts(text: str) -> str:
    """
    Strip characters that can cause Gemini TTS 500 errors:
    control characters, null bytes, excessive whitespace.
    """
    import unicodedata
    # Remove ASCII control chars (except tab, newline, carriage return)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cc" or ch in "\t\n\r")
    # Collapse runs of whitespace / newlines into a single space
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def tts_gemini_chunk(text: str, voice: str, output_path: str, api_key: str):
    """
    Generate one chunk of audio via Google Gemini TTS API.
    The API returns raw 24 kHz / 16-bit / mono PCM; we pipe it through
    ffmpeg to produce a standard MP3 file.
    Retries up to 3 times with exponential back-off on transient 500 errors.
    """
    import base64
    import subprocess
    import tempfile
    import time
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    clean_text = _sanitize_for_tts(text)

    last_exc = None
    for attempt in range(3):            # try up to 3 times
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash-preview-tts",
                contents=clean_text,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=voice,
                            )
                        )
                    ),
                ),
            )
            break                       # success — exit retry loop
        except Exception as exc:
            last_exc = exc
            err_str = str(exc)
            # Only retry on 500/503 server-side errors; raise immediately otherwise
            if "500" not in err_str and "503" not in err_str and "INTERNAL" not in err_str:
                raise
            if attempt < 2:
                wait = 2 ** attempt     # 1 s, 2 s
                time.sleep(wait)
    else:
        raise RuntimeError(
            f"Gemini TTS failed after 3 attempts: {last_exc}"
        )

    part = response.candidates[0].content.parts[0]
    audio_data = part.inline_data.data
    # Gemini may return bytes or a base64 string depending on SDK version
    if isinstance(audio_data, str):
        audio_data = base64.b64decode(audio_data)

    # Write raw PCM to a temp file, then convert to MP3 via ffmpeg
    tmp = tempfile.NamedTemporaryFile(suffix=".pcm", delete=False)
    tmp.write(audio_data)
    tmp.close()
    try:
        result = subprocess.run(
            [
                settings.ffmpeg_binary, "-y",
                "-f", "s16le",   # signed 16-bit little-endian PCM
                "-ar", "24000",  # 24 kHz sample rate (Gemini output)
                "-ac", "1",      # mono
                "-i", tmp.name,
                "-codec:a", "libmp3lame", "-q:a", "2",
                output_path,
            ],
            capture_output=True, timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"ffmpeg PCM→MP3 failed: {result.stderr[-300:]}"
            )
    finally:
        try:
            os.remove(tmp.name)
        except Exception:
            pass


def _generate_silence_mp3(output_path: str, duration_sec: float = 0.4):
    """
    Write a short silent MP3 (mono 24 kHz) using ffmpeg lavfi.
    Used as a natural breath-gap between Gemini TTS chunks to reset pacing.
    """
    import subprocess
    subprocess.run(
        [
            settings.ffmpeg_binary, "-y",
            "-f", "lavfi",
            "-i", f"anullsrc=channel_layout=mono:sample_rate=24000",
            "-t", str(duration_sec),
            "-codec:a", "libmp3lame", "-q:a", "2",
            output_path,
        ],
        capture_output=True, timeout=30,
    )


def tts_gemini(text: str, voice: str, output_path: str, api_key: str, job=None):
    """
    Split script into ~2 500-char paragraph-aware chunks and concatenate.

    Why 2 500 chars?  Gemini TTS gradually accelerates within a single request
    as the text gets longer.  Shorter chunks keep each call brief so the model
    finishes before it has a chance to speed up.  A 400 ms silence is inserted
    between chunks to give a natural breath-gap and avoid the chunks sounding
    like they're running together.
    """
    chunks = split_text_into_chunks(text, max_chars=2500)
    if len(chunks) == 1:
        tts_gemini_chunk(chunks[0], voice, output_path, api_key)
        return

    base = output_path.replace(".mp3", "")
    silence_path = f"{base}_silence.mp3"
    _generate_silence_mp3(silence_path, duration_sec=0.4)

    chunk_paths = []
    for i, chunk in enumerate(chunks):
        if job:
            pct = 30 + int((i / len(chunks)) * 60)
            job.update(progress=pct, message=f"Generating audio part {i + 1} of {len(chunks)}…")
        chunk_path = f"{base}_part{i}.mp3"
        tts_gemini_chunk(chunk, voice, chunk_path, api_key)
        chunk_paths.append(chunk_path)

    # Interleave silence between chunks: [c0, sil, c1, sil, c2, ...]
    interleaved = []
    for i, p in enumerate(chunk_paths):
        interleaved.append(p)
        if i < len(chunk_paths) - 1:
            interleaved.append(silence_path)

    concatenate_audio_files(interleaved, output_path)

    for p in chunk_paths:
        try:
            os.remove(p)
        except Exception:
            pass
    try:
        os.remove(silence_path)
    except Exception:
        pass


# ── Background worker ────────────────────────────────────────────────────────

def run_audio_generation(job_id: str, text: str, voice: str, speed: float, language: str,
                         model: str = "eleven_multilingual_v2"):
    job = job_store.get(job_id)
    try:
        job.update(status="processing", progress=10, message="Preparing text...")

        output_filename = f"{job_id}.mp3"
        output_path = str(Path(settings.audio_output_dir) / output_filename)

        provider = settings.tts_provider.lower()
        job.update(progress=30, message=f"Generating audio with {provider}...")

        if provider == "elevenlabs":
            tts_elevenlabs(text, voice, output_path, job=job, model=model)
        elif provider == "openai":
            openai_voice = voice if voice else "alloy"
            tts_openai(text, openai_voice, output_path, speed, job=job)
        elif provider == "google":
            tts_google(text, language, output_path)
        elif provider == "gemini":
            if not settings.gemini_api_key:
                raise ValueError("Gemini API key not set. Add it in Settings.")
            gemini_voice = voice if voice else "Charon"
            tts_gemini(text, gemini_voice, output_path, settings.gemini_api_key, job=job)
        else:
            raise ValueError(f"Unknown TTS provider: {provider}")

        job.update(
            status="done",
            progress=100,
            message="Audio generated successfully!",
            result={
                "audio_url": f"/downloads/{output_filename}",
                "filename": output_filename,
            },
        )
    except Exception as e:
        job.update(error=str(e))


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/upload")
async def upload_audio(file: UploadFile = File(...)):
    """Accept a pre-recorded audio file and save it to the audio output directory."""
    allowed = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac")
    if not file.filename.lower().endswith(allowed):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported audio format. Allowed: {', '.join(allowed)}"
        )
    import uuid
    ext = os.path.splitext(file.filename)[1].lower()
    filename = f"{uuid.uuid4()}{ext}"
    output_path = str(Path(settings.audio_output_dir) / filename)
    with open(output_path, "wb") as f:
        f.write(await file.read())
    return {"audio_url": f"/downloads/{filename}", "filename": filename}


@router.get("/duration/{filename}")
def get_audio_duration(filename: str):
    """Return the duration (in seconds) of a generated audio file."""
    import subprocess, json
    audio_path = str(Path(settings.audio_output_dir) / filename)
    if not os.path.exists(audio_path):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Audio file not found: {filename}")

    # Derive ffprobe path from ffmpeg setting
    import shutil
    ffmpeg = settings.ffmpeg_binary
    if os.sep in ffmpeg or "/" in ffmpeg:
        ext = ".exe" if ffmpeg.lower().endswith(".exe") else ""
        candidate = os.path.join(os.path.dirname(ffmpeg), f"ffprobe{ext}")
        probe = candidate if os.path.exists(candidate) else "ffprobe"
    else:
        probe = "ffprobe" if shutil.which("ffprobe") else ffmpeg.replace("ffmpeg", "ffprobe")

    result = subprocess.run(
        [probe, "-v", "quiet", "-print_format", "json", "-show_streams", audio_path],
        capture_output=True, text=True, timeout=30,
    )
    data = json.loads(result.stdout or "{}")
    duration = 0.0
    for stream in data.get("streams", []):
        if "duration" in stream:
            duration = float(stream["duration"])
            break

    return {"filename": filename, "duration": duration}


@router.post("/generate")
async def generate_audio(
    background_tasks: BackgroundTasks,
    text: Optional[str] = Form(None),
    google_doc_url: Optional[str] = Form(None),
    voice: Optional[str] = Form(None),
    speed: Optional[float] = Form(1.0),
    language: Optional[str] = Form("en-US"),
    model: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
):
    script_text = None

    if text and text.strip():
        script_text = text.strip()
    elif google_doc_url:
        try:
            script_text = extract_text_from_google_doc(google_doc_url)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Could not fetch Google Doc: {e}")
    elif file:
        file_bytes = await file.read()
        if file.filename.endswith(".docx"):
            try:
                script_text = extract_text_from_docx(file_bytes)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Could not read .docx: {e}")
        elif file.filename.endswith(".txt"):
            script_text = file_bytes.decode("utf-8", errors="ignore")
        else:
            raise HTTPException(status_code=400, detail="Unsupported file type. Use .docx or .txt")

    if not script_text:
        raise HTTPException(status_code=400, detail="No script text provided.")

    el_model = model or "eleven_multilingual_v2"
    job = job_store.create()
    background_tasks.add_task(run_audio_generation, job.job_id, script_text, voice, speed, language, el_model)

    return {"job_id": job.job_id, "status": "pending"}
