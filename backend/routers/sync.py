"""
Sync router.
Uses OpenAI Whisper to transcribe the audio with timestamps, then matches
each slide's text to the transcript to calculate the exact duration per slide.

Runs as a background job (same polling pattern as audio/video) so long
Whisper transcriptions never cause browser timeouts.
"""
import os
import re
import json
from pathlib import Path
from difflib import SequenceMatcher

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from config import settings
from job_store import job_store

router = APIRouter()


class SyncRequest(BaseModel):
    audio_filename: str   # e.g. "abc123.mp3"
    frames_job_id: str    # used to locate slide_texts.json + frames


# ── Text helpers ──────────────────────────────────────────────────────────────

def clean_words(text: str) -> list:
    return re.sub(r"[^a-z0-9\s]", "", text.lower()).split()


# ── Core matching ─────────────────────────────────────────────────────────────

def exact_title_position(title_words: list, transcript_words: list,
                         search_from: int, search_to: int) -> tuple:
    """
    Search for the slide title as an exact word sequence in the transcript.
    Slide headings are spoken verbatim, so an exact hit is highly reliable.

    Returns (position, score):
      - score 1.0 = all words match
      - score 0.7–1.0 = partial match (one word off — Whisper mishear tolerance)
      - score -1 = no hit found in window
    """
    n = len(title_words)
    if n == 0:
        return -1, 0.0

    search_to = min(search_to, len(transcript_words) - n + 1)
    best_pos, best_score = -1, 0.0

    for pos in range(search_from, search_to):
        window = transcript_words[pos: pos + n]
        matches = sum(a == b for a, b in zip(title_words, window))
        score = matches / n
        if score > best_score:
            best_score = score
            best_pos = pos
        if score == 1.0:
            break  # perfect match found — stop searching

    return best_pos, best_score


def fuzzy_match_position(slide_words: list, transcript_words: list,
                         search_from: int, search_to: int) -> tuple:
    """
    Fuzzy match of slide body words as fallback when title match fails.
    """
    compare_n = min(len(slide_words), 12)
    probe     = slide_words[:compare_n]
    total_tw  = len(transcript_words)
    search_to = min(search_to, total_tw - compare_n + 1)

    best_score, best_pos = -1.0, search_from
    for pos in range(search_from, search_to):
        candidate = transcript_words[pos: pos + compare_n]
        score = SequenceMatcher(None, probe, candidate).ratio()
        if score > best_score:
            best_score = score
            best_pos   = pos

    return best_pos, best_score


def compute_slide_durations(slide_texts: list, segments: list, total_duration: float,
                            slide_titles: list = None) -> list:
    """
    Proportionally-anchored slide sync algorithm.

    KEY INSIGHT: Instead of a greedy forward scan (which compounds errors if one
    match is wrong), each slide's search window is CENTERED on its proportional
    expected position in the transcript.  This makes every slide independently
    robust — a bad match for slide 5 does not cascade into slides 6, 7, 8 …

    Strategy per slide i (i ≥ 1):
      expected_pos  = i/n * total_words          (proportional anchor)
      search window = [max(prev_pos+gap, expected-radius),
                       min(total_words,  expected+radius)]
      Pass 1 — exact title match  (≥3-word titles only, score ≥ 0.7)
      Pass 2 — wider title search (2× radius) if pass 1 weak
      Pass 3 — fuzzy body match   if title still weak
      Pass 4 — proportional fallback
    """
    # ── Build word timeline: [(cleaned_word, timestamp), …] ──────────────────
    timeline = []
    for seg in segments:
        raw_words = seg.get("text", "").split()
        if not raw_words:
            continue
        t_start = float(seg.get("start", 0))
        t_end   = float(seg.get("end", t_start))
        span    = t_end - t_start
        for idx, w in enumerate(raw_words):
            t = t_start + (idx / len(raw_words)) * span
            timeline.append((re.sub(r"[^a-z0-9]", "", w.lower()), t))

    n = len(slide_texts)

    if not timeline:
        per = round(total_duration / max(n, 1), 1)
        return [per] * n, []

    transcript_words = [t[0] for t in timeline]
    total_tw  = len(transcript_words)
    avg_words = max(1, total_tw // n)

    # ── Normalise titles ──────────────────────────────────────────────────────
    if not slide_titles:
        slide_titles = [""] * n
    while len(slide_titles) < n:
        slide_titles.append("")
    title_word_lists = [clean_words(t) for t in slide_titles]

    # Search radius: ±2× avg_words around the expected position.
    # This is wide enough to capture slides that run 3–4× longer than average
    # while still preventing a match from the first/last 10% of the transcript
    # being assigned to a middle slide.
    radius = max(avg_words * 2, total_tw // max(n - 1, 1))

    # Minimum word gap to enforce monotonic ordering
    min_gap = max(1, avg_words // 6)

    # ── Find START word-index for each slide ─────────────────────────────────
    slide_start_idx = [0]   # slide 0 always starts at word 0
    slide_match_methods = ["slide0"]  # parallel list for debug output
    prev_pos = 0

    for i in range(1, n):
        # Proportional expected start for this slide
        expected = int(i / n * total_tw)

        # Search window: anchored on expected, but must be after prev_pos+gap
        win_lo = max(prev_pos + min_gap, expected - radius)
        win_hi = min(total_tw, expected + radius)
        # If window collapsed (very short audio or many slides), widen it
        if win_hi - win_lo < avg_words:
            win_hi = min(total_tw, win_lo + avg_words * 2)

        pos, score = -1, 0.0
        match_method = "proportional"
        title_words = title_word_lists[i]

        # ── Pass 1: exact title match in proportional window ─────────────
        if len(title_words) >= 2:
            pos, score = exact_title_position(title_words, transcript_words,
                                              win_lo, win_hi)
            if score >= 0.7:
                match_method = f"title({score:.2f})"

            # ── Pass 2: wider title search (2× radius) ────────────────────
            if score < 0.7:
                wide_lo = max(prev_pos + min_gap, expected - radius * 2)
                wide_hi = min(total_tw, expected + radius * 2)
                pos2, score2 = exact_title_position(title_words, transcript_words,
                                                    wide_lo, wide_hi)
                if score2 > score:
                    pos, score = pos2, score2
                if score >= 0.7:
                    match_method = f"title-wide({score:.2f})"

        # ── Pass 3: fuzzy body match ──────────────────────────────────────
        if score < 0.7:
            body_words = clean_words(slide_texts[i])
            if body_words:
                fpos, fscore = fuzzy_match_position(body_words, transcript_words,
                                                    win_lo, win_hi)
                if fscore > score:
                    pos, score = fpos, fscore
                # Wider fuzzy attempt
                if score < 0.25:
                    wide_lo2 = max(prev_pos + min_gap, expected - radius * 2)
                    wide_hi2 = min(total_tw, expected + radius * 2)
                    fpos2, fscore2 = fuzzy_match_position(body_words, transcript_words,
                                                          wide_lo2, wide_hi2)
                    if fscore2 > score:
                        pos, score = fpos2, fscore2
                if score >= 0.35:
                    match_method = f"fuzzy({score:.2f})"

        # ── Pass 4: proportional fallback ─────────────────────────────────
        if pos < 0 or score < 0.35:
            pos = expected
            match_method = "proportional"

        # Enforce monotonic: pos must be strictly after prev_pos
        pos = max(pos, prev_pos + min_gap)
        pos = min(pos, total_tw - 1)

        slide_start_idx.append(pos)
        slide_match_methods.append(match_method)
        prev_pos = pos

    # ── Convert start-indices to durations ────────────────────────────────────
    durations = []
    debug_info = []   # saved alongside result for diagnosis
    for i in range(n):
        idx_s = min(slide_start_idx[i], total_tw - 1)
        t_s   = timeline[idx_s][1]

        if i == n - 1:
            t_e = total_duration
        else:
            idx_e = min(slide_start_idx[i + 1], total_tw - 1)
            t_e   = timeline[idx_e][1]

        dur = max(1.0, round(t_e - t_s, 2))
        durations.append(dur)
        debug_info.append({
            "slide": i + 1,
            "word_index": slide_start_idx[i],
            "word": transcript_words[min(slide_start_idx[i], total_tw - 1)],
            "start_sec": round(t_s, 2),
            "duration_sec": dur,
            "title": slide_titles[i] if slide_titles else "",
            "match": slide_match_methods[i] if i < len(slide_match_methods) else "?",
        })

    # Ensure full audio is covered (rounding / last-slide padding)
    gap = round(total_duration - sum(durations), 2)
    if gap > 0:
        durations[-1] = round(durations[-1] + gap, 2)
        debug_info[-1]["duration_sec"] = durations[-1]

    # ── Duration cap/floor: prevent one weak-match slide absorbing neighbours ─
    # Only applied to non-strong-title slides (< 0.85 title confidence).
    # Cap:   slide > 2.0× avg → trim to 2.0× avg; excess absorbed by last slide.
    # Floor: middle slide < max(10s, 0.25× avg) → boost to floor; last slide absorbs diff.
    # Using the last slide as the slack absorber avoids cascading shifts mid-timeline.
    if n > 2:
        avg_dur = total_duration / n
        strong_matches = {
            i for i, m in enumerate(slide_match_methods)
            if m.startswith("title") and _match_score(m) >= 0.85
        }
        cap_dur   = avg_dur * 2.0
        floor_dur = max(10.0, avg_dur * 0.25)

        for i in range(n - 1):   # never touch last slide directly
            if i not in strong_matches and durations[i] > cap_dur:
                durations[i] = round(cap_dur, 2)
            if i > 0 and durations[i] < floor_dur:   # skip first slide floor
                durations[i] = round(floor_dur, 2)

        # Restore total by adjusting last slide
        total_after = round(sum(durations[:-1]), 2)
        durations[-1] = round(max(floor_dur, total_duration - total_after), 2)

        # Update debug_info
        for i in range(n):
            debug_info[i]["duration_sec"] = round(durations[i], 2)

    return durations, debug_info, timeline, slide_start_idx


def _match_score(method_str: str) -> float:
    """Extract numeric confidence from a match_method string like 'title(0.92)'."""
    try:
        return float(method_str.split("(")[1].rstrip(")"))
    except Exception:
        return 1.0 if method_str in ("slide0",) else 0.0


def compute_element_timestamps(
    timeline: list,
    slide_start_idx: list,
    slide_paragraph_texts: list,
    total_duration: float,
) -> list:
    """
    For each slide, find the narration timestamp (relative to slide start)
    when each element's text is first spoken.

    Parameters
    ----------
    timeline              : [(cleaned_word, timestamp_sec), …]  from compute_slide_durations
    slide_start_idx       : [word_index_of_slide_start, …]      from compute_slide_durations
    slide_paragraph_texts : [[para_text, …], …]  one list per slide, same order as
                            get_element_boxes() / get_slide_paragraph_texts()
    total_duration        : total audio length in seconds

    Returns
    -------
    [[delay_sec, …], …]  — per-slide list of element delays relative to slide start.
    0.0 means "show immediately when slide appears".
    """
    # Common stop-words to skip when matching slide text → spoken words
    _STOP = {
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "is", "are", "was", "were", "be", "been", "being",
        "it", "its", "this", "that", "these", "those", "by", "as", "from",
        "has", "have", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "can", "not", "no", "if", "then", "when",
    }

    def key_words(text: str) -> list:
        words = re.sub(r"[^a-z0-9\s]", "", text.lower()).split()
        return [w for w in words if w not in _STOP and len(w) > 1]

    n_slides  = len(slide_start_idx)
    total_tw  = len(timeline)
    result    = []

    for i in range(n_slides):
        wi_start  = slide_start_idx[i]
        wi_end    = slide_start_idx[i + 1] if i < n_slides - 1 else total_tw

        t_slide   = timeline[min(wi_start, total_tw - 1)][1]
        slide_words = timeline[wi_start:wi_end]          # [(word, t), …]
        n_sw      = len(slide_words)

        elem_texts = (slide_paragraph_texts[i]
                      if i < len(slide_paragraph_texts) else [])
        n_elems    = len(elem_texts)

        if not elem_texts or not slide_words:
            result.append([0.0] * n_elems)
            continue

        slide_dur = max(0.1, slide_words[-1][1] - t_slide) if slide_words else 1.0
        delays    = []
        last_wi   = 0   # monotonic forward pointer within slide_words

        for ei, elem_text in enumerate(elem_texts):
            kw = key_words(elem_text)

            if not kw:
                # Image or symbol-only — show proportionally
                delays.append(round((ei / max(n_elems, 1)) * slide_dur * 0.85, 3))
                continue

            best_wi    = -1
            best_score = 0.0

            for si in range(last_wi, n_sw):
                win_end = min(n_sw, si + max(len(kw) * 4, 15))
                window  = [slide_words[j][0] for j in range(si, win_end)]
                matches = sum(1 for w in kw if w in window)
                score   = matches / len(kw)
                if score > best_score:
                    best_score = score
                    best_wi    = si
                if score >= 0.6:
                    break   # good enough — stop early

            if best_wi >= 0 and best_score >= 0.25:
                delay   = max(0.0, round(slide_words[best_wi][1] - t_slide, 3))
                last_wi = best_wi   # enforce monotonic ordering
            else:
                # Proportional fallback — spread evenly across slide
                delay = round((ei / max(n_elems, 1)) * slide_dur * 0.85, 3)

            delays.append(delay)

        result.append(delays)

    return result


# ── Background worker ─────────────────────────────────────────────────────────

def run_sync_analysis(job_id: str, audio_filename: str, frames_job_id: str):
    from openai import OpenAI

    job = job_store.get(job_id)
    try:
        audio_path = Path(settings.audio_output_dir) / audio_filename
        frames_dir = Path(settings.video_output_dir) / f"{frames_job_id}_frames"
        texts_file = frames_dir / "slide_texts.json"

        if not audio_path.exists():
            raise FileNotFoundError("Audio file not found.")
        if not frames_dir.exists():
            raise FileNotFoundError("Slide frames not found. Please re-convert the PPTX.")

        # Load slide texts and titles
        titles_file = frames_dir / "slide_titles.json"
        if texts_file.exists():
            with open(texts_file, "r", encoding="utf-8") as f:
                slide_texts = json.load(f)
        else:
            slide_texts = [""] * len(sorted(frames_dir.glob("slide_*.png")))

        slide_titles = []
        if titles_file.exists():
            with open(titles_file, "r", encoding="utf-8") as f:
                slide_titles = json.load(f)

        if not slide_texts:
            raise ValueError("No slide text data found. Please re-convert the PPTX.")

        job.update(progress=20, message=f"Transcribing audio with Whisper ({len(slide_texts)} slides)…")

        # Transcribe — Whisper supports up to 25 MB
        client = OpenAI(api_key=settings.openai_api_key)
        file_size_mb = audio_path.stat().st_size / (1024 * 1024)

        if file_size_mb > 24:
            # Large file: compress to opus via ffmpeg before sending
            import subprocess, tempfile
            job.update(progress=25, message="Audio is large — compressing for Whisper…")
            tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            tmp.close()
            subprocess.run([
                settings.ffmpeg_binary, "-y", "-i", str(audio_path),
                "-ar", "16000", "-ac", "1", "-b:a", "32k", tmp.name
            ], capture_output=True, timeout=300)
            whisper_path = tmp.name
        else:
            whisper_path = str(audio_path)
            tmp = None

        job.update(progress=35, message="Sending audio to Whisper API…")
        with open(whisper_path, "rb") as f:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                response_format="verbose_json",
            )

        if tmp:
            try:
                os.remove(whisper_path)
            except Exception:
                pass

        job.update(progress=70, message="Matching slide text to transcript…")

        segments = getattr(transcript, "segments", None) or []
        seg_dicts = []
        for s in segments:
            if isinstance(s, dict):
                seg_dicts.append(s)
            else:
                seg_dicts.append({"text": s.text, "start": s.start, "end": s.end})

        total_duration = float(
            getattr(transcript, "duration", None) or
            (seg_dicts[-1]["end"] if seg_dicts else 60.0)
        )

        durations, debug_info, _timeline, _slide_start_idx = compute_slide_durations(
            slide_texts, seg_dicts, total_duration, slide_titles=slide_titles
        )

        # Save debug info so the user can inspect what the algorithm decided
        debug_path = frames_dir / "sync_debug.json"
        with open(debug_path, "w", encoding="utf-8") as f:
            json.dump({
                "total_duration": round(total_duration, 2),
                "slide_count": len(durations),
                "total_words_in_transcript": sum(1 for s in seg_dicts for _ in s.get("text","").split()),
                "slides": debug_info,
            }, f, ensure_ascii=False, indent=2)

        # Compute per-element voiceover timestamps and save for the renderer
        try:
            pptx_copy = frames_dir / "source.pptx"
            if pptx_copy.exists():
                from routers.slides import get_slide_paragraph_texts
                slide_para_texts = [
                    get_slide_paragraph_texts(str(pptx_copy), i)
                    for i in range(len(durations))
                ]
                element_timing = compute_element_timestamps(
                    _timeline, _slide_start_idx, slide_para_texts, total_duration
                )
                timing_path = frames_dir / "element_timing.json"
                with open(timing_path, "w", encoding="utf-8") as f:
                    json.dump(element_timing, f, ensure_ascii=False)
        except Exception as _et_err:
            # Non-fatal — animation will fall back to uniform timing
            print(f"[sync] element_timing skipped: {_et_err}")

        job.update(
            status="done",
            progress=100,
            message=f"Synced {len(durations)} slides to {total_duration:.1f}s audio",
            result={
                "slide_durations": durations,
                "total_duration": round(total_duration, 2),
                "slide_count": len(durations),
                "transcript_preview": (getattr(transcript, "text", "") or "")[:300],
                "debug": debug_info,
            },
        )

    except Exception as e:
        job.update(error=str(e))


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/analyze")
async def analyze_sync(background_tasks: BackgroundTasks, request: SyncRequest):
    """Start a background Whisper sync job. Poll /api/status/{job_id} for progress."""
    audio_path = Path(settings.audio_output_dir) / request.audio_filename
    frames_dir = Path(settings.video_output_dir) / f"{request.frames_job_id}_frames"

    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found.")
    if not frames_dir.exists():
        raise HTTPException(status_code=404, detail="Slide frames not found. Re-convert the PPTX first.")

    job = job_store.create()
    job.update(status="processing", progress=10, message="Starting AI sync…")
    background_tasks.add_task(run_sync_analysis, job.job_id, request.audio_filename, request.frames_job_id)

    return {"job_id": job.job_id, "status": "pending"}
