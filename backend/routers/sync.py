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


# ── Slide-number marker helpers ───────────────────────────────────────────────
# When the voice-over script uses "Slide 1", "Slide 2" … as section headers
# and the narrator reads those numbers aloud, Whisper transcribes them as
# perfect positional anchors.  We detect them before falling back to title /
# fuzzy / proportional matching.

_NUM_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20,
    "twentyone": 21, "twentytwo": 22, "twentythree": 23,
    "twentyfour": 24, "twentyfive": 25, "twentysix": 26,
    "twentyseven": 27, "twentyeight": 28, "twentynine": 29,
    "thirty": 30, "thirtyone": 31, "thirtytwo": 32, "thirtythree": 33,
    "thirtyfour": 34, "thirtyfive": 35, "thirtysix": 36,
    "thirtyseven": 37, "thirtyeight": 38, "thirtynine": 39,
    "forty": 40, "fortyone": 41, "fortytwo": 42, "fortythree": 43,
    "fortyfour": 44, "fortyfive": 45, "fortysix": 46,
    "fortyseven": 47, "fortyeight": 48, "fortynine": 49,
    "fifty": 50, "fiftyone": 51, "fiftytwo": 52, "fiftythree": 53,
    "fiftyfour": 54, "fiftyfive": 55, "fiftysix": 56,
    "fiftyseven": 57, "fiftyeight": 58, "fiftynine": 59,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    "hundred": 100,
}

# Tens words used when combining two-word numbers like "twenty one" → 21.
# Defined at module level so both _find_all_slide_markers and Pass 0 share it.
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}


def _word_to_int(w: str) -> int:
    """Convert a digit-string or English number word to int.  Returns -1 if unknown."""
    if w.isdigit():
        return int(w)
    return _NUM_WORDS.get(w.lower(), -1)


def _find_all_slide_markers(transcript_words: list, n_slides: int) -> dict:
    """
    Robustly find 'slide N' spoken markers in the transcript.

    Two-step approach to avoid false-positive poisoning:

    Step 1 — Collect ALL occurrences of "slide N" (or "slide number N") for
             every slide number 1..n_slides.  Multiple occurrences per number
             are kept so we can pick the best one in step 2.
             Also handles two-word numbers: "slide twenty one" → 21.

    Step 2 — Greedy forward pass: iterate slide numbers in order 1, 2, 3 …
             and for each one pick the EARLIEST occurrence that appears AFTER
             the previously accepted marker position.  This means a stray
             "back on slide 10" mentioned early in the narration does NOT
             block detection of slides 1-9, because we process them in order.

    Returns {slide_number_1based: word_pos_of_marker}.
    """
    total = len(transcript_words)

    # ── Step 1: collect ALL occurrences ──────────────────────────────────────
    occurrences: dict[int, list[int]] = {}   # num → sorted list of word positions

    for pos in range(total - 1):
        if transcript_words[pos] != "slide":
            continue
        # Try offsets 1 and 2 (to skip optional word "number")
        for offset in (1, 2):
            nxt = pos + offset
            if nxt >= total:
                break
            w = transcript_words[nxt]
            num = _word_to_int(w)

            # Two-word compound: "slide twenty one" → 21
            # (Whisper usually outputs digits, but word forms happen too)
            if num < 0 and w in _TENS and nxt + 1 < total:
                ones = _word_to_int(transcript_words[nxt + 1])
                if 1 <= ones <= 9:
                    num = _TENS[w] + ones

            if 1 <= num <= n_slides:
                occurrences.setdefault(num, []).append(pos)
                break   # don't try the other offset for this position

    # ── Step 2: greedy forward pass in slide-number order ────────────────────
    found: dict[int, int] = {}
    last_pos = -1
    for num in range(1, n_slides + 1):
        if num not in occurrences:
            continue
        # Pick the earliest occurrence that is strictly after the last accepted pos
        for pos in sorted(occurrences[num]):
            if pos > last_pos:
                found[num] = pos
                last_pos = pos
                break

    return found


# ── Robust matching helpers ───────────────────────────────────────────────────

# Stop words contribute half-weight in title scoring so one mismatched
# preposition / article doesn't tank an otherwise good match.
_TITLE_STOP = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "is", "are", "by", "as", "its", "it", "this", "that",
    "not", "no", "from", "be", "been", "why", "how", "what", "when",
}


def _norm(w: str) -> str:
    """
    Light stemming so Whisper inflection variants don't break title matching.
    Rules (applied in priority order, each only if the remainder is ≥ 3 chars):
      -ing   → strip  (walking → walk, rolling → roll)
      -tion  → keep   (protection is its own root)
      -s     → strip  (risks → risk, matters → matter)  — not -ss / -us / -is
      -ed    → strip  (prevented → prevent)
      -ly    → strip  (properly → proper)
    """
    if len(w) <= 3:
        return w
    if w.endswith("ing") and len(w) > 5:
        return w[:-3] or w
    if w.endswith("s") and not w.endswith(("ss", "us", "is", "as")) and len(w) > 3:
        return w[:-1]
    if w.endswith("ed") and len(w) > 4:
        return w[:-2]
    if w.endswith("ly") and len(w) > 5:
        return w[:-2]
    return w


def _expand_compound(words: list) -> list:
    """
    Split compound words that Whisper may transcribe as two separate words.
    E.g. "logrolling" → ["log", "rolling"].

    For each word longer than 8 chars, tries all 2-part splits where both
    parts are ≥ 3 chars; keeps the first valid split found.
    Returns the expanded list (may be longer than input).
    """
    out = []
    for w in words:
        if len(w) > 8:
            split_done = False
            for k in range(3, len(w) - 2):
                p1, p2 = w[:k], w[k:]
                if len(p2) >= 3:
                    out.extend([p1, p2])
                    split_done = True
                    break
            if not split_done:
                out.append(w)
        else:
            out.append(w)
    return out


# ── Core matching ─────────────────────────────────────────────────────────────

def exact_title_position(title_words: list, transcript_words: list,
                         search_from: int, search_to: int) -> tuple:
    """
    Search for the slide title as a word-sequence in the transcript.

    Improvements over naive char-exact matching:
    • Light stemming (_norm) — handles plural-s, -ing, -ed from Whisper
    • Compound expansion — tries "logrolling" AND "log" + "rolling" (Whisper
      often splits compound words into two tokens)
    • Stop-word weighted scoring — prepositions / articles count 0.5× so one
      mismatched function word doesn't push below the match threshold
    • Score is always relative to ORIGINAL title word count so it's comparable
      across both the single-word and split-word forms

    Returns (position, score):
      score ≥ 0.6  → usable match (threshold previously 0.7)
      score -1     → no hit found in window
    """
    n = len(title_words)
    if n == 0:
        return -1, 0.0

    # Normalised original title + per-word weights
    norm_orig   = [_norm(w) for w in title_words]
    weights_orig = [0.5 if w in _TITLE_STOP else 1.0 for w in title_words]
    total_orig   = max(sum(weights_orig), 1e-9)

    # Compound-expanded title variant
    expanded     = _expand_compound(title_words)
    norm_exp     = [_norm(w) for w in expanded]
    weights_exp  = [0.5 if w in _TITLE_STOP else 1.0 for w in expanded]
    # Score the expanded form relative to original n (fair comparison)
    total_exp_w  = sum(weights_exp)

    search_to = min(search_to, len(transcript_words))
    best_pos, best_score = -1, 0.0

    for pos in range(search_from, search_to):
        # ── Variant A: original (possibly compound) title words ────────────
        end_a = pos + len(norm_orig)
        if end_a <= len(transcript_words):
            raw_a = sum(
                w if _norm(transcript_words[pos + j]) == norm_orig[j] else 0.0
                for j, w in enumerate(weights_orig)
            )
            score_a = raw_a / total_orig
            if score_a > best_score:
                best_score = score_a
                best_pos   = pos

        # ── Variant B: expanded (split) title words ────────────────────────
        if expanded != title_words:
            end_b = pos + len(norm_exp)
            if end_b <= len(transcript_words):
                raw_b = sum(
                    w if _norm(transcript_words[pos + j]) == norm_exp[j] else 0.0
                    for j, w in enumerate(weights_exp)
                )
                # Normalise by original total so scores are comparable
                score_b = raw_b / total_orig
                if score_b > best_score:
                    best_score = score_b
                    best_pos   = pos

        if best_score >= 0.99:
            break

    return best_pos, best_score


def fuzzy_match_position(slide_words: list, transcript_words: list,
                         search_from: int, search_to: int) -> tuple:
    """
    Fuzzy match of slide body words as fallback when title match fails.
    """
    compare_n = min(len(slide_words), 24)   # up from 12
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


def _bag_match_position(content_words: list, transcript_words: list,
                        search_from: int, search_to: int,
                        window_mult: int = 3) -> tuple:
    """
    Bag-of-content-words match: slide through the transcript counting how many
    key words from the title appear in a window of (n × window_mult) words,
    in ANY order.

    This catches titles where the narrator says all key words but not in the
    same contiguous sequence (extra filler words between them, slightly different
    phrasing, etc.).

    Returns (best_position, fraction_of_content_words_found).
    """
    norm_cw = [_norm(w) for w in content_words if len(w) > 2]
    cw_set  = set(norm_cw)
    n_cw    = len(cw_set)
    if n_cw == 0:
        return -1, 0.0

    win_size  = max(len(content_words) * window_mult, 8)
    total_tw  = len(transcript_words)
    search_to = min(search_to, total_tw - win_size + 1)

    best_score, best_pos = -1.0, search_from
    for pos in range(search_from, max(search_from + 1, search_to)):
        window_set = {
            _norm(transcript_words[pos + j])
            for j in range(min(win_size, total_tw - pos))
        }
        matches = sum(1 for w in cw_set if w in window_set)
        score   = matches / n_cw
        if score > best_score:
            best_score = score
            best_pos   = pos
        if best_score >= 0.99:
            break

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
      Pass 1 — exact title match  (≥2-word titles, score ≥ 0.6, with stemming+compound)
      Pass 2 — wider title search (3× radius) if pass 1 weak
      Pass 3 — fuzzy body match   if title still weak
      Pass 4 — proportional fallback
    """
    # ── Build word timeline: [(cleaned_word, timestamp), …] ──────────────────
    # Prefer per-word timestamps from Whisper (timestamp_granularities=["word"])
    # — much more accurate than linear interpolation within each segment.
    # Falls back to linear interpolation if word-level data is unavailable.
    timeline = []
    for seg in segments:
        word_entries = seg.get("words", [])
        if word_entries:
            # Word-level timestamps available — use directly
            for we in word_entries:
                raw = we.get("word", "")
                t   = float(we.get("start", we.get("t", 0)))
                cleaned = re.sub(r"[^a-z0-9]", "", raw.lower().strip())
                if cleaned:
                    timeline.append((cleaned, t))
        else:
            # Fallback: linear interpolation within the segment
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

    # ── Debug: pre-scan for "Slide N" markers (logging only) ────────────────
    # The actual detection now happens inline per-slide in Pass 0 (window-bound).
    # This pre-scan is kept only for the log line so we can see how many markers
    # the narrator uses; it is NOT used for positioning decisions.
    _dbg_markers = _find_all_slide_markers(transcript_words, n)
    print(f"[sync] slide_num pre-scan: {len(_dbg_markers)}/{n} unique markers found "
          f"| keys={sorted(_dbg_markers.keys())[:20]}")

    # Search radius: ±2.5× avg_words around the expected position.
    # Wide enough to capture slides that run 3–4× longer than average.
    radius = max(int(avg_words * 2.5), total_tw // max(n - 1, 1))

    # Minimum word gap to enforce monotonic ordering
    min_gap = max(1, avg_words // 8)

    # ── Confirmed anchors for position interpolation ──────────────────────────
    # Each entry: (slide_index, word_pos).  Only high-confidence matches are
    # used as anchors; proportional/fuzzy guesses are NOT added because their
    # positions can be wrong and would corrupt the interpolation.
    conf_anchors = [(0, 0)]   # slide 0 always starts at word 0

    def _interp_expected(i: int) -> int:
        """
        Interpolate expected word position from the last confirmed anchor to the
        transcript end.  More accurate than i/n*total_tw when early slides have
        very different durations than the average.
        """
        last_ai, last_ap = conf_anchors[-1]
        steps_since   = i - last_ai
        steps_remain  = max(n - last_ai, 1)
        return int(last_ap + steps_since / steps_remain * (total_tw - last_ap))

    # ── Find START word-index for each slide ─────────────────────────────────
    slide_start_idx     = [0]         # slide 0 always starts at word 0
    slide_match_methods = ["slide0"]
    prev_pos            = 0
    prev_is_strong      = True        # slide 0 anchor is always correct

    for i in range(1, n):
        # ── Compute expected position ───────────────────────────────────────
        prop_expected  = int(i / n * total_tw)
        interp_expected = _interp_expected(i)
        # Use the interpolated estimate when we have a recent anchor (≤ 10 slides
        # ago); otherwise fall back to proportional to avoid stale anchors.
        steps_since_anchor = i - conf_anchors[-1][0]
        expected = interp_expected if steps_since_anchor <= 10 else prop_expected

        # ── Build search window ─────────────────────────────────────────────
        # When the previous match was weak (proportional/fuzzy), don't let its
        # possibly-wrong position push win_lo past the actual slide start.
        # Use the interpolated expected as a softer lower bound in that case.
        if prev_is_strong:
            hard_lo = prev_pos + min_gap
        else:
            # Previous was uncertain — let the interpolated estimate dominate
            hard_lo = max(prev_pos + min_gap,
                          interp_expected - radius)

        win_lo = max(hard_lo, expected - radius)
        win_hi = min(total_tw, expected + radius)
        if win_hi - win_lo < avg_words:
            win_hi = min(total_tw, win_lo + avg_words * 2)

        pos, score = -1, 0.0
        match_method = "proportional"
        title_words = title_word_lists[i]

        # ── Pass 0: spoken "Slide N" marker — inline window search ──────────
        # Search for "slide N" (or "slide number N") WITHIN the current
        # proportional window only.  This naturally excludes cross-references
        # to other slide numbers ("see Slide 10 for details") that appear far
        # from where slide N should start, which is the critical flaw of any
        # whole-transcript pre-scan approach.
        # Also handles two-word numbers: "slide twenty one" → 21.
        _snum     = i + 1       # 1-based slide number
        _found_sn = False
        for _p in range(max(win_lo, prev_pos + 1), min(win_hi, total_tw - 1)):
            if transcript_words[_p] != "slide":
                continue
            for _off in (1, 2):   # "slide N" or "slide number N"
                _nxt = _p + _off
                if _nxt >= total_tw:
                    break
                _w  = transcript_words[_nxt]
                _n  = _word_to_int(_w)
                # Two-word: "slide twenty one" → 21
                if _n < 0 and _w in _TENS and _nxt + 1 < total_tw:
                    _ones = _word_to_int(transcript_words[_nxt + 1])
                    if 1 <= _ones <= 9:
                        _n = _TENS[_w] + _ones
                if _n == _snum:
                    pos          = _p
                    score        = 1.0
                    match_method = f"slide_num({_snum})"
                    _found_sn    = True
                    break
            if _found_sn:
                break

        # Passes 1–4 are skipped when Pass 0 (slide_num) already succeeded.
        if score < 1.0:

            # ── Pass 1: title match in proportional window (score ≥ 0.6) ─────
            # Uses stemming + compound expansion + stop-word-weighted scoring.
            # Single-word titles (e.g. "Contraindications") are included since
            # they can be highly distinctive medical/technical terms.
            if len(title_words) >= 1:
                pos, score = exact_title_position(title_words, transcript_words,
                                                  win_lo, win_hi)
                if score >= 0.6:
                    match_method = f"title({score:.2f})"

                # ── Pass 2: wider title search (4× radius) ────────────────────
                if score < 0.6:
                    wide_lo = max(prev_pos + min_gap, expected - radius * 4)
                    wide_hi = min(total_tw, expected + radius * 4)
                    pos2, score2 = exact_title_position(title_words, transcript_words,
                                                        wide_lo, wide_hi)
                    if score2 > score:
                        pos, score = pos2, score2
                    if score >= 0.6:
                        match_method = f"title-wide({score:.2f})"

            # ── Pass 2.5: content-word bag match (unordered, wider window) ────
            # Catches titles where the narrator says all key words but not in the
            # exact same order (e.g. "the log rolling procedure and clinical…").
            if score < 0.6 and len(title_words) >= 1:
                bag_words = [w for w in title_words
                             if w not in _TITLE_STOP and len(w) > 2]
                if len(bag_words) >= 1:
                    bpos, bscore = _bag_match_position(
                        bag_words, transcript_words,
                        max(prev_pos + min_gap, expected - radius * 4),
                        min(total_tw, expected + radius * 4),
                    )
                    if bscore > score:
                        pos, score = bpos, bscore
                        if bscore >= 0.6:
                            match_method = f"bag({bscore:.2f})"

            # ── Pass 3: fuzzy body match ──────────────────────────────────────
            if score < 0.6:
                # Combine title + body for richer text fingerprint
                body_raw   = clean_words(slide_texts[i])
                combined   = (title_words + body_raw)[:24]   # up from 12
                if combined:
                    fpos, fscore = fuzzy_match_position(combined, transcript_words,
                                                        win_lo, win_hi)
                    if fscore > score:
                        pos, score = fpos, fscore
                    if score < 0.30:
                        wide_lo3 = max(prev_pos + min_gap, expected - radius * 4)
                        wide_hi3 = min(total_tw, expected + radius * 4)
                        fpos2, fscore2 = fuzzy_match_position(combined, transcript_words,
                                                              wide_lo3, wide_hi3)
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

        # Update anchors and strong-prev flag
        # slide_num matches are always perfect anchors; high-confidence title
        # matches (≥ 0.65) also qualify.
        is_strong = (
            match_method.startswith("slide_num") or
            (match_method.startswith("title") and _match_score(match_method) >= 0.65)
        )
        if is_strong:
            conf_anchors.append((i, pos))
        prev_is_strong = is_strong

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
            if m.startswith("title") and _match_score(m) >= 0.75
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
                timestamp_granularities=["word", "segment"],
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
                d = {"text": s.text, "start": s.start, "end": s.end}
                # Carry word-level timestamps through if Whisper returned them
                words = getattr(s, "words", None)
                if words:
                    d["words"] = [
                        {"word": w.word, "start": w.start, "end": w.end}
                        if not isinstance(w, dict) else w
                        for w in words
                    ]
                seg_dicts.append(d)

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
                print(f"[sync] element_timing written: {len(element_timing)} slides, "
                      f"element counts: {[len(s) for s in element_timing[:8]]}{'...' if len(element_timing) > 8 else ''}")
        except Exception as _et_err:
            # Non-fatal — animation will fall back to uniform timing
            import traceback as _et_tb
            print(f"[sync] element_timing skipped: {_et_err}")
            _et_tb.print_exc()

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
