"""
Merge router.
Combines an audio file and a slides video into the final MP4.

sync_mode options:
  pad       — freeze last frame if video ends before audio (original behaviour)
  trim      — cut to the shorter stream
  loop      — loop the video to match audio length
  auto_fit  — measure audio duration, divide evenly across all slides, rebuild video
  per_slide — rebuild video using a custom per-slide duration list from the request
"""
import os
import subprocess
from pathlib import Path
from typing import Optional, List

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from config import settings
from job_store import job_store

router = APIRouter()


class MergeRequest(BaseModel):
    audio_filename: str             # e.g. "abc123.mp3"
    video_filename: str             # e.g. "def456_slides.mp4"
    sync_mode: str = "pad"          # pad | trim | loop | auto_fit | per_slide
    frames_job_id: Optional[str] = None       # required for auto_fit / per_slide
    slide_durations: Optional[List[float]] = None  # per_slide mode: one value per slide
    transition: str = "none"        # transition to use when rebuilding
    resolution: str = "1920x1080"   # resolution to use when rebuilding
    animation: str = "none"         # animation mode used when rebuilding
    transition_clip_id: Optional[str] = None  # custom transition clip ID


# ── Helpers ──────────────────────────────────────────────────────────────────

def get_ffprobe() -> str:
    """Derive the ffprobe binary path from the ffmpeg setting."""
    import shutil
    ffmpeg = settings.ffmpeg_binary
    # Full path: swap ffmpeg → ffprobe in the same directory
    if os.sep in ffmpeg or "/" in ffmpeg:
        if ffmpeg.lower().endswith(".exe"):
            candidate = os.path.join(os.path.dirname(ffmpeg), "ffprobe.exe")
        else:
            candidate = os.path.join(os.path.dirname(ffmpeg), "ffprobe")
        if os.path.exists(candidate):
            return candidate
    # Try PATH
    if shutil.which("ffprobe"):
        return "ffprobe"
    # Heuristic: replace the binary name
    return ffmpeg.replace("ffmpeg.exe", "ffprobe.exe").replace("ffmpeg", "ffprobe")


def get_media_duration(path: str) -> float:
    """Return the duration of a media file in seconds using ffprobe."""
    import json
    probe = get_ffprobe()
    result = subprocess.run(
        [probe, "-v", "quiet", "-print_format", "json", "-show_streams", path],
        capture_output=True, text=True, timeout=30,
    )
    data = json.loads(result.stdout or "{}")
    for stream in data.get("streams", []):
        if "duration" in stream:
            return float(stream["duration"])
    raise RuntimeError(f"Could not determine duration of: {path}")


# ── Background worker ─────────────────────────────────────────────────────────

def run_merge(
    job_id: str,
    audio_path: str,
    video_path: str,
    sync_mode: str,
    frames_job_id: str = None,
    slide_durations: list = None,
    transition: str = "none",
    resolution: str = "1920x1080",
    animation: str = "none",
    transition_clip_id: str = None,
):
    job = job_store.get(job_id)
    try:
        job.update(status="processing", progress=10, message="Starting merge...")

        output_filename = f"{job_id}_final.mp4"
        output_path = str(Path(settings.video_output_dir) / output_filename)

        rebuilt_path = None  # track temporary rebuilt video for cleanup

        # ── Rebuild video with custom timing ─────────────────────────────────
        if sync_mode in ("auto_fit", "per_slide") and frames_job_id:
            from routers.slides import build_video_from_images

            frames_dir = Path(settings.video_output_dir) / f"{frames_job_id}_frames"
            frame_files = sorted(frames_dir.glob("slide_*.png"))
            if not frame_files:
                raise RuntimeError(
                    f"Slide frames not found for job '{frames_job_id}'. "
                    "Please re-upload the PPTX to regenerate frames."
                )

            if sync_mode == "auto_fit":
                job.update(progress=20, message="Measuring audio duration...")
                audio_dur = get_media_duration(audio_path)
                n = len(frame_files)
                dur_per_slide = round(audio_dur / n, 3)
                durations = [dur_per_slide] * n
                job.update(
                    progress=25,
                    message=f"Auto-fit: {n} slides × {dur_per_slide:.1f}s = {audio_dur:.1f}s total",
                )
            else:  # per_slide
                if not slide_durations or len(slide_durations) < len(frame_files):
                    raise RuntimeError(
                        f"slide_durations must have at least {len(frame_files)} entries."
                    )
                durations = slide_durations[: len(frame_files)]

            # Resolve PPTX and transition clip (kept in frames dir / transitions dir)
            pptx_copy  = str(frames_dir / "source.pptx")
            pptx_arg   = pptx_copy if os.path.exists(pptx_copy) else None
            trans_clip = None
            if transition_clip_id:
                c = str(Path(settings.video_output_dir) / "transitions" / transition_clip_id)
                if os.path.exists(c):
                    trans_clip = c

            # Load voiceover-synced element delays if available (written by sync worker)
            element_timing = None
            _timing_path = frames_dir / "element_timing.json"
            if _timing_path.exists() and animation in (
                "text_fade", "text_slide_up", "text_wipe", "char_overshoot_scale"
            ):
                try:
                    import json as _json
                    with open(_timing_path, "r", encoding="utf-8") as _tf:
                        element_timing = _json.load(_tf)
                except Exception as _et_err:
                    print(f"[merge] element_timing load failed: {_et_err}")

            job.update(progress=30, message="Rebuilding video with custom slide timing...")
            rebuilt_path = str(Path(settings.video_output_dir) / f"{job_id}_rebuilt.mp4")

            def _rebuild_progress(frac, _job=job):
                # Maps 0‥1 → 30%‥70% so the bar moves steadily during rendering
                p = 30 + int(frac * 40)
                n = len(frame_files)
                done = max(1, round(frac * n))
                _job.update(progress=p, message=f"Rendering slides… {done}/{n}")

            build_video_from_images(
                [str(f) for f in frame_files],
                rebuilt_path,
                slide_duration=durations[0],
                transition=transition,
                resolution=resolution,
                durations=durations,
                animation=animation,
                pptx_path=pptx_arg,
                transition_clip=trans_clip,
                progress_callback=_rebuild_progress,
                element_timing=element_timing,
            )
            video_path = rebuilt_path

            # Durations now match — simple mux (no padding/looping needed)
            job.update(progress=75, message="Combining audio and video...")
            cmd = [
                settings.ffmpeg_binary, "-y",
                "-i", video_path,
                "-i", audio_path,
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-c:v", "copy",
                "-c:a", "aac",
                "-shortest",
                output_path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if result.returncode != 0:
                raise RuntimeError(f"FFmpeg merge error: {result.stderr[-500:]}")

        # ── Standard sync modes ───────────────────────────────────────────────
        else:
            job.update(progress=30, message="Merging audio and video...")

            if sync_mode == "trim":
                cmd = [
                    settings.ffmpeg_binary, "-y",
                    "-i", video_path,
                    "-i", audio_path,
                    "-shortest",
                    "-c:v", "copy", "-c:a", "aac",
                    output_path,
                ]
            elif sync_mode == "loop":
                cmd = [
                    settings.ffmpeg_binary, "-y",
                    "-stream_loop", "-1", "-i", video_path,
                    "-i", audio_path,
                    "-shortest",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac",
                    output_path,
                ]
            else:  # pad — extend last frame + silence
                cmd = [
                    settings.ffmpeg_binary, "-y",
                    "-i", video_path,
                    "-i", audio_path,
                    "-filter_complex",
                    "[0:v]tpad=stop_mode=clone:stop_duration=60[vpad];"
                    "[1:a]apad[apad]",
                    "-map", "[vpad]",
                    "-map", "[apad]",
                    "-shortest",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac",
                    output_path,
                ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if result.returncode != 0:
                raise RuntimeError(f"FFmpeg merge error: {result.stderr[-500:]}")

        job.update(
            status="done",
            progress=100,
            message="Final video created!",
            result={
                "video_url": f"/videos/{output_filename}",
                "filename": output_filename,
            },
        )
    except Exception as e:
        job.update(error=str(e))
    finally:
        # Clean up the temporary rebuilt video if it exists
        if rebuilt_path and os.path.exists(rebuilt_path):
            try:
                os.remove(rebuilt_path)
            except Exception:
                pass


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/combine")
async def combine(background_tasks: BackgroundTasks, request: MergeRequest):
    """Merge the generated audio and slides video into a final MP4."""
    audio_path = str(Path(settings.audio_output_dir) / request.audio_filename)
    video_path = str(Path(settings.video_output_dir) / request.video_filename)

    if not os.path.exists(audio_path):
        raise HTTPException(status_code=404, detail=f"Audio file not found: {request.audio_filename}")
    if not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail=f"Video file not found: {request.video_filename}")

    job = job_store.create()
    background_tasks.add_task(
        run_merge,
        job.job_id,
        audio_path,
        video_path,
        request.sync_mode,
        request.frames_job_id,
        request.slide_durations,
        request.transition,
        request.resolution,
        request.animation,
        request.transition_clip_id,
    )

    return {"job_id": job.job_id, "status": "pending"}
