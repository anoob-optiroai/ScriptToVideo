"""
Slides-to-video router.
Accepts a .pptx file, converts each slide to a PNG using LibreOffice,
then stitches them into a silent .mp4 using FFmpeg with optional transitions.
Frames are stored persistently so the merge step can rebuild with custom timing.
"""
import os
import glob
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, List

from fastapi import APIRouter, UploadFile, File, Form, BackgroundTasks, HTTPException

from config import settings
from job_store import job_store

router = APIRouter()


def find_libreoffice() -> str:
    """Find the LibreOffice binary on the current system."""
    if settings.libreoffice_binary not in ("libreoffice", "soffice"):
        return settings.libreoffice_binary

    windows_paths = [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        r"C:\Program Files\LibreOffice 7\program\soffice.exe",
        r"C:\Program Files\LibreOffice 24\program\soffice.exe",
    ]
    for path in windows_paths:
        if os.path.exists(path):
            return path

    if shutil.which("soffice"):
        return "soffice"
    if shutil.which("libreoffice"):
        return "libreoffice"

    raise RuntimeError(
        "LibreOffice not found. Please install it from https://www.libreoffice.org/download/ "
        "and restart the backend."
    )


def convert_pptx_to_images(pptx_path: str, output_dir: str) -> list:
    """
    Convert PPTX to images via two steps:
      1. LibreOffice: PPTX -> PDF  (all slides reliably exported)
      2. PyMuPDF (fitz): PDF pages -> PNG images
    """
    import fitz  # PyMuPDF

    libreoffice_bin = find_libreoffice()

    cmd = [
        libreoffice_bin,
        "--headless",
        "--convert-to", "pdf",
        "--outdir", output_dir,
        pptx_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"LibreOffice PDF export error: {result.stderr}")

    pdf_files = glob.glob(os.path.join(output_dir, "*.pdf"))
    if not pdf_files:
        raise RuntimeError("LibreOffice did not produce a PDF file.")
    pdf_path = pdf_files[0]

    doc = fitz.open(pdf_path)
    images = []
    for i, page in enumerate(doc):
        mat = fitz.Matrix(2.0, 2.0)
        pix = page.get_pixmap(matrix=mat)
        img_path = os.path.join(output_dir, f"slide_{i+1:03d}.png")
        pix.save(img_path)
        images.append(img_path)
    doc.close()

    # Remove the intermediate PDF (keep only PNGs)
    try:
        os.remove(pdf_path)
    except Exception:
        pass

    return sorted(images)


def _iter_shapes(shapes):
    """
    Recursively yield all leaf shapes, descending into group shapes.
    python-pptx's slide.shapes only returns top-level shapes — grouped
    shapes must be walked manually.
    """
    for shape in shapes:
        try:
            # GroupShape has a .shapes attribute
            if shape.shape_type == 6:   # MSO_SHAPE_TYPE.GROUP == 6
                yield from _iter_shapes(shape.shapes)
                continue
        except Exception:
            pass
        yield shape


def extract_slide_texts(pptx_path: str, n_slides: int) -> dict:
    """
    Extract title and body text from each slide using python-pptx.
    Returns {"titles": [...], "bodies": [...]} — titles are used for
    exact matching in AI sync since they are identical in the voiceover.

    Title detection strategy (most-specific first):
      1. Shape with PP_PLACEHOLDER.TITLE / CENTER_TITLE / VERTICAL_TITLE
      2. Shape whose placeholder idx == 0 (index-0 placeholder is always the title)
      3. Shape whose name contains "title" (case-insensitive)
      4. First text shape on the slide (fallback — better than nothing)

    Group shapes are recursively walked so text inside groups is found.
    """
    try:
        from pptx import Presentation
        from pptx.enum.shapes import PP_PLACEHOLDER

        TITLE_PH_TYPES = {PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE,
                          PP_PLACEHOLDER.VERTICAL_TITLE}

        prs = Presentation(pptx_path)
        titles, bodies = [], []

        for slide in prs.slides:
            title_text = ""
            body_parts = []
            first_text_shape = None   # fallback

            title_candidate = None
            title_priority  = 99      # lower = better match

            # Walk ALL shapes including those nested inside groups
            for shape in _iter_shapes(slide.shapes):
                if not shape.has_text_frame:
                    continue
                try:
                    text = shape.text_frame.text.strip()
                except Exception:
                    continue
                if not text:
                    continue

                if first_text_shape is None:
                    first_text_shape = text

                try:
                    ph = shape.placeholder_format
                except (ValueError, AttributeError):
                    ph = None
                ph_type  = ph.type if ph else None
                ph_idx   = ph.idx  if ph else None

                priority = 99
                if ph_type in TITLE_PH_TYPES:
                    priority = 0
                elif ph_idx == 0:
                    priority = 1
                elif shape.name and "title" in shape.name.lower():
                    priority = 2

                if priority < title_priority:
                    title_candidate = text
                    title_priority  = priority

            # Assign title — if no placeholder found, use the TOPMOST text
            # shape (lowest Y value) rather than the first in XML order.
            # Slides like "HOW AED WORKS" have their header shape listed late
            # in the XML but positioned at the top of the slide visually.
            # We skip all-emoji/symbol shapes (< 3 ASCII letters) so that
            # decorative icon shapes (🚨, ⚡, etc.) at Y≈0 aren't picked.
            if title_candidate:
                title_text = title_candidate
            else:
                import re as _re
                def _has_word_chars(s: str) -> bool:
                    return len(_re.sub(r"[^A-Za-z0-9]", "", s)) >= 3

                topmost_text = None
                topmost_y = float("inf")
                for shape in _iter_shapes(slide.shapes):
                    if not shape.has_text_frame:
                        continue
                    try:
                        text = shape.text_frame.text.strip()
                    except Exception:
                        continue
                    if not text or not _has_word_chars(text):
                        continue
                    y = getattr(shape, "top", None) or 0
                    if y < topmost_y:
                        topmost_y = y
                        topmost_text = text
                title_text = topmost_text or first_text_shape or ""

            # Collect body text (all non-title shapes)
            for shape in _iter_shapes(slide.shapes):
                if not shape.has_text_frame:
                    continue
                try:
                    text = shape.text_frame.text.strip()
                except Exception:
                    continue
                if not text or text == title_text:
                    continue
                for para in shape.text_frame.paragraphs:
                    try:
                        line = " ".join(run.text for run in para.runs).strip()
                    except Exception:
                        line = para.text.strip()
                    if line:
                        body_parts.append(line)

            titles.append(title_text)
            bodies.append(" ".join(body_parts))

        while len(titles) < n_slides:
            titles.append("")
            bodies.append("")

        return {"titles": titles[:n_slides], "bodies": bodies[:n_slides]}
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print(f"[extract_slide_texts] WARNING: fell back to empty titles — {exc}")
        return {"titles": [""] * n_slides, "bodies": [""] * n_slides}


# ── Text-animation helpers ────────────────────────────────────────────────────

def get_element_boxes(pptx_path: str, slide_idx: int, img_w: int, img_h: int) -> list:
    """
    Return a list of (l, t, r, b, kind) tuples for every animatable element on
    a slide, sorted top→bottom by their vertical midpoint.

    kind values: "text" | "image"

    Text shapes are split into per-paragraph rows so each line animates
    individually.  The paragraph heights are approximated by dividing the
    shape's pixel height equally among non-empty paragraphs — not pixel-perfect
    but visually convincing.

    Image shapes (pictures / filled shapes without text) are returned as-is.
    """
    try:
        from pptx import Presentation
        from pptx.util import Pt
        prs = Presentation(pptx_path)
        if slide_idx >= len(prs.slides):
            return []
        slide = prs.slides[slide_idx]
        sx = img_w / prs.slide_width
        sy = img_h / prs.slide_height
        elements = []

        for shape in slide.shapes:
            sl = max(0, int(shape.left  * sx))
            st = max(0, int(shape.top   * sy))
            sr = min(img_w, int((shape.left + shape.width)  * sx))
            sb = min(img_h, int((shape.top  + shape.height) * sy))
            if sr <= sl + 10 or sb <= st + 10:
                continue

            # ── Text shape: split into per-paragraph rows ────────────────────
            if shape.has_text_frame:
                tf = shape.text_frame
                # Collect non-empty paragraph texts
                paras = [p for p in tf.paragraphs
                         if "".join(r.text for r in p.runs).strip()]
                if not paras:
                    continue
                n_p = len(paras)
                shape_h = sb - st
                row_h   = max(4, shape_h // n_p)
                for pi, _ in enumerate(paras):
                    pt = st + pi * row_h
                    pb = min(sb, st + (pi + 1) * row_h)
                    if pb > pt + 2:
                        elements.append((sl, pt, sr, pb, "text"))
                continue

            # ── Table shape: split into per-row animatable bands ─────────────
            # shape_type 19 = MSO_SHAPE_TYPE.TABLE
            shape_type = getattr(shape, "shape_type", None)
            if shape_type == 19 or getattr(shape, "has_table", False):
                try:
                    tbl = shape.table
                    n_rows = len(tbl.rows)
                    if n_rows > 0:
                        row_h = max(4, (sb - st) // n_rows)
                        for ri in range(n_rows):
                            rt = st + ri * row_h
                            rb = min(sb, st + (ri + 1) * row_h)
                            if rb > rt + 2:
                                elements.append((sl, rt, sr, rb, "table_row"))
                except Exception:
                    elements.append((sl, st, sr, sb, "image"))
                continue

            # ── Image / picture shape ────────────────────────────────────────
            # shape_type 13 = MSO_SHAPE_TYPE.PICTURE
            # Also catch filled shapes that render as images
            try:
                from pptx.enum.shapes import MSO_SHAPE_TYPE
                is_pic = shape.shape_type == MSO_SHAPE_TYPE.PICTURE
            except Exception:
                is_pic = (shape_type == 13)

            if is_pic:
                elements.append((sl, st, sr, sb, "image"))

        # Sort by vertical midpoint so reading order is respected
        elements.sort(key=lambda e: (e[1] + e[3]) / 2)
        return elements
    except Exception:
        import traceback
        traceback.print_exc()
        return []


# Keep old name as alias so any other callers don't break
def get_text_boxes(pptx_path: str, slide_idx: int, img_w: int, img_h: int) -> list:
    return [(l, t, r, b) for l, t, r, b, _ in get_element_boxes(pptx_path, slide_idx, img_w, img_h)]


def get_slide_paragraph_texts(pptx_path: str, slide_idx: int) -> list:
    """
    Return the text of every animatable element on a slide in the same
    top-to-bottom order as get_element_boxes().

    Used by compute_element_timestamps() in sync.py to match each visual
    element to the moment it is spoken in the voiceover.

    • Text paragraphs  → paragraph text string
    • Table rows       → space-joined cell text
    • Images           → empty string  (no spoken text to match)
    """
    try:
        from pptx import Presentation
        prs = Presentation(pptx_path)
        if slide_idx >= len(prs.slides):
            return []
        slide  = prs.slides[slide_idx]
        items  = []   # [(raw_mid_y, text)]

        for shape in slide.shapes:
            l_r = shape.left  or 0
            t_r = shape.top   or 0
            r_r = l_r + (shape.width  or 0)
            b_r = t_r + (shape.height or 0)
            if (r_r - l_r) < 10 or (b_r - t_r) < 10:
                continue

            if shape.has_text_frame:
                tf    = shape.text_frame
                paras = [p for p in tf.paragraphs
                         if "".join(run.text for run in p.runs).strip()]
                if not paras:
                    continue
                n_p     = len(paras)
                h_r     = b_r - t_r
                row_h_r = max(1, h_r // n_p)
                for pi, p in enumerate(paras):
                    pt_r = t_r + pi * row_h_r
                    pb_r = min(b_r, t_r + (pi + 1) * row_h_r)
                    text = "".join(run.text for run in p.runs).strip()
                    items.append(((pt_r + pb_r) / 2, text))
                continue

            shape_type = getattr(shape, "shape_type", None)
            if shape_type == 19 or getattr(shape, "has_table", False):
                try:
                    tbl   = shape.table
                    n_r   = len(tbl.rows)
                    rh_r  = max(1, (b_r - t_r) // max(n_r, 1))
                    for ri in range(n_r):
                        rt_r = t_r + ri * rh_r
                        rb_r = min(b_r, t_r + (ri + 1) * rh_r)
                        row_text = " ".join(
                            cell.text_frame.text
                            for cell in tbl.rows[ri].cells
                            if hasattr(cell, "text_frame")
                        ).strip()
                        items.append(((rt_r + rb_r) / 2, row_text))
                except Exception:
                    items.append(((t_r + b_r) / 2, ""))
                continue

            try:
                from pptx.enum.shapes import MSO_SHAPE_TYPE
                is_pic = shape.shape_type == MSO_SHAPE_TYPE.PICTURE
            except Exception:
                is_pic = (shape_type == 13)
            if is_pic:
                items.append(((t_r + b_r) / 2, ""))

        items.sort(key=lambda x: x[0])
        return [text for _, text in items]
    except Exception:
        return []


def _get_char_element_boxes(pptx_path: str, slide_idx: int, img_w: int, img_h: int) -> list:
    """
    Like get_element_boxes but splits every text paragraph into individual
    per-character column boxes so that char_overshoot_scale can animate one
    letter at a time.

    For each paragraph, character widths are measured with PIL (proportional
    scaling so the columns always span the full shape width).

    Non-text shapes (images, tables) are returned at their normal granularity
    (same as get_element_boxes).
    """
    try:
        from pptx import Presentation
        from PIL import ImageFont as _IF

        prs = Presentation(pptx_path)
        if slide_idx >= len(prs.slides):
            return []
        slide   = prs.slides[slide_idx]
        sx      = img_w / prs.slide_width
        sy      = img_h / prs.slide_height
        elements = []

        # Ordered list of font paths to try for glyph-width measurement
        _FONT_PATHS = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
            "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
        ]

        def _load_font(size_px):
            for fp in _FONT_PATHS:
                try:
                    return _IF.truetype(fp, max(8, size_px))
                except Exception:
                    pass
            try:
                return _IF.load_default(max(8, size_px))
            except Exception:
                return _IF.load_default()

        def _char_width(font, ch):
            try:
                if hasattr(font, "getlength"):
                    return max(1.0, float(font.getlength(ch)))
                elif hasattr(font, "getsize"):
                    return max(1.0, float(font.getsize(ch)[0]))
            except Exception:
                pass
            return max(1.0, font.size * 0.6)

        for shape in slide.shapes:
            sl = max(0, int(shape.left  * sx))
            st = max(0, int(shape.top   * sy))
            sr = min(img_w, int((shape.left + shape.width)  * sx))
            sb = min(img_h, int((shape.top  + shape.height) * sy))
            if sr <= sl + 10 or sb <= st + 10:
                continue

            # ── Text shape: split into per-character column boxes ────────────
            if shape.has_text_frame:
                tf    = shape.text_frame
                paras = [p for p in tf.paragraphs
                         if "".join(r.text for r in p.runs).strip()]
                if not paras:
                    continue
                n_p     = len(paras)
                shape_h = sb - st
                row_h   = max(4, shape_h // n_p)

                for pi, para in enumerate(paras):
                    pt = st + pi * row_h
                    pb = min(sb, st + (pi + 1) * row_h)
                    if pb <= pt + 2:
                        continue

                    para_text = "".join(r.text for r in para.runs).strip()
                    if not para_text:
                        continue

                    # Measure glyphs at ~75 % of row height for accuracy
                    font_size_px = max(8, int((pb - pt) * 0.75))
                    font         = _load_font(font_size_px)

                    char_widths = [_char_width(font, ch) for ch in para_text]
                    total_w     = sum(char_widths) or 1.0
                    # Scale so columns fill the full shape width
                    scale_x = (sr - sl) / total_w

                    # Use the full paragraph row height for each character column.
                    # This ensures that when we copy pixels from the rendered slide
                    # image (full_np) we restore exactly the right region — no
                    # vertical clipping of ascenders / descenders.
                    x = float(sl)
                    for ch, cw in zip(para_text, char_widths):
                        cl = int(x)
                        cr = min(sr, int(x + cw * scale_x))
                        if cr > cl:
                            elements.append((cl, pt, cr, pb, "char"))
                        x += cw * scale_x

                    # Close any rounding gap in the last character
                    if elements and elements[-1][4] == "char":
                        last = elements[-1]
                        elements[-1] = (last[0], last[1], sr, last[3], "char")
                continue

            # ── Table: per-row (unchanged from get_element_boxes) ────────────
            shape_type = getattr(shape, "shape_type", None)
            if shape_type == 19 or getattr(shape, "has_table", False):
                try:
                    tbl    = shape.table
                    n_rows = len(tbl.rows)
                    if n_rows > 0:
                        row_h = max(4, (sb - st) // n_rows)
                        for ri in range(n_rows):
                            rt = st + ri * row_h
                            rb = min(sb, st + (ri + 1) * row_h)
                            if rb > rt + 2:
                                elements.append((sl, rt, sr, rb, "table_row"))
                except Exception:
                    elements.append((sl, st, sr, sb, "image"))
                continue

            # ── Pictures ─────────────────────────────────────────────────────
            try:
                from pptx.enum.shapes import MSO_SHAPE_TYPE
                is_pic = shape.shape_type == MSO_SHAPE_TYPE.PICTURE
            except Exception:
                is_pic = (shape_type == 13)
            if is_pic:
                elements.append((sl, st, sr, sb, "image"))

        # Sort top→bottom by row midpoint, left→right within each row
        elements.sort(key=lambda e: ((e[1] + e[3]) / 2, e[0]))
        return elements
    except Exception:
        import traceback
        traceback.print_exc()
        return []


def _sample_bg_color(img_np, l: int, t: int, r: int, b: int) -> tuple:
    """Return the median RGB of pixels just outside the bounding box."""
    import numpy as np
    h, w = img_np.shape[:2]
    pad  = 20
    strips = []
    if t >= pad:
        strips.append(img_np[t - pad : t,         max(0, l) : min(w, r)])
    if b + pad <= h:
        strips.append(img_np[b : min(h, b + pad),  max(0, l) : min(w, r)])
    if l >= pad:
        strips.append(img_np[max(0, t) : min(h, b), l - pad : l])
    if r + pad <= w:
        strips.append(img_np[max(0, t) : min(h, b), r : min(w, r + pad)])

    pixels = [px for s in strips if s.size > 0 for px in s.reshape(-1, 3).tolist()]
    if not pixels:
        return (255, 255, 255)
    med = np.median(pixels, axis=0).astype(int)
    return (int(med[0]), int(med[1]), int(med[2]))


def _apply_elem_anim(frame, full_np, bg_np,
                     l: int, t_b: int, r: int, b: int,
                     anim_type: str, progress: float):
    """
    Blend one element region of *frame* (numpy array, in-place) from the
    background toward the fully-revealed image at the given progress (0→1).

    Extracted so the same pixel logic is shared between the uniform animation
    path and the voiceover-synced path.
    """
    import numpy as _np
    import math  as _math

    if anim_type == "text_fade":
        frame[t_b:b, l:r] = (
            bg_np[t_b:b, l:r]   * (1.0 - progress) +
            full_np[t_b:b, l:r] * progress
        ).astype(_np.uint8)

    elif anim_type == "text_slide_up":
        reveal = int(progress * (b - t_b))
        if reveal > 0:
            frame[b - reveal:b, l:r] = full_np[b - reveal:b, l:r]

    elif anim_type == "text_wipe":
        reveal = int(progress * (r - l))
        if reveal > 0:
            frame[t_b:b, l:l + reveal] = full_np[t_b:b, l:l + reveal]

    elif anim_type == "char_overshoot_scale":
        from PIL import Image as _PILImg
        _c, _omega = 8.0, 14.0
        _t = progress * 0.7
        _sc = max(0.001, min(
            1.0 - _math.exp(-_c * _t) * _math.cos(_omega * _t), 2.5
        ))
        _ew, _eh = r - l, b - t_b
        _cx, _cy = (l + r) // 2, (t_b + b) // 2
        _nw = max(1, int(_ew * _sc));  _nh = max(1, int(_eh * _sc))
        _scaled = _np.array(
            _PILImg.fromarray(full_np[t_b:b, l:r]).resize((_nw, _nh), _PILImg.LANCZOS)
        )
        _dl = _cx - _nw // 2;  _dt = _cy - _nh // 2
        _dr = _dl + _nw;       _db = _dt + _nh
        _sl = max(0, -_dl);    _dl = max(0, _dl)
        _st = max(0, -_dt);    _dt = max(0, _dt)
        _dr = min(_dr, frame.shape[1]);  _db = min(_db, frame.shape[0])
        _sr = _sl + (_dr - _dl);        _sb = _st + (_db - _dt)
        if _dr > _dl and _db > _dt and _sr > _sl and _sb > _st:
            frame[_dt:_db, _dl:_dr] = _scaled[_st:_sb, _sl:_sr]


def build_text_animated_clip(
    full_png: str,
    pptx_path: str,
    slide_idx: int,
    duration: float,
    anim_type: str,   # "text_fade" | "text_slide_up" | "text_wipe" | "char_overshoot_scale"
    out_path: str,
    fps: int = 25,
    anim_dur: float = 1.0,
    out_width: int = 1920,
    out_height: int = 1080,
    element_delays: list = None,  # per-element delay in seconds (voiceover-synced)
):
    """
    Build a single-slide MP4 where the text elements animate in (PIL-based).
    Falls back to a plain fade-in on the whole slide if python-pptx / PIL are
    unavailable or no text shapes are found.
    """
    import numpy as np
    from PIL import Image, ImageDraw

    img      = Image.open(full_png).convert("RGB")
    iw, ih   = img.size
    full_np  = np.array(img)

    # Shape-level elements — used for background erasure regardless of mode
    elements = get_element_boxes(pptx_path, slide_idx, iw, ih) if pptx_path else []

    if not elements:
        # Fallback: whole-slide fade-in via FFmpeg at target resolution
        _scale = (f"scale={out_width}:{out_height}:force_original_aspect_ratio=decrease,"
                  f"pad={out_width}:{out_height}:(ow-iw)/2:(oh-ih)/2")
        _cmd = [
            settings.ffmpeg_binary, "-y",
            "-loop", "1", "-t", str(duration), "-i", os.path.abspath(full_png),
            "-vf", f"{_scale},fade=t=in:st=0:d={min(anim_dur, duration * 0.4)}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps), out_path,
        ]
        subprocess.run(_cmd, capture_output=True, timeout=120)
        return

    # For char_overshoot_scale: get per-character column boxes for the animation
    # loop while the background is still erased at shape granularity above.
    anim_elements = elements
    if anim_type == "char_overshoot_scale" and pptx_path:
        _char_elems = _get_char_element_boxes(pptx_path, slide_idx, iw, ih)
        if _char_elems:
            anim_elements = _char_elems

    # ── Create background PNG (all animated elements hidden with sampled BG) ──
    # Always erase at shape-level so the full text area is blanked before
    # character-by-character animation draws each glyph column back in.
    bg_img = img.copy()
    _draw  = ImageDraw.Draw(bg_img)
    for (l, t, r, b, _kind) in elements:
        color = _sample_bg_color(full_np, l, t, r, b)
        _draw.rectangle([l, t, r, b], fill=color)
    bg_np = np.array(bg_img)

    n_elems   = len(anim_elements)
    frame_dur = round(1.0 / fps, 6)

    frame_dir  = out_path + "_frs"
    concat_txt = out_path + "_frs.txt"
    os.makedirs(frame_dir, exist_ok=True)
    # frame_list: [(path, duration_sec), …]
    frame_list = []
    _fi_ctr    = [0]   # mutable counter shared by inner helper

    def _save_frame(arr):
        fp = os.path.join(frame_dir, f"f{_fi_ctr[0]:07d}.png")
        Image.fromarray(arr).save(fp)
        _fi_ctr[0] += 1
        return fp

    def _compose(revealed_set, active_ei=None, progress=0.0):
        """Build one numpy frame: revealed elements fully shown, active element animating."""
        f = bg_np.copy()
        for ri in revealed_set:
            rl, rt, rr, rb, _ = anim_elements[ri]
            f[rt:rb, rl:rr] = full_np[rt:rb, rl:rr]
        if active_ei is not None:
            al, at, ar, ab, _ = anim_elements[active_ei]
            _apply_elem_anim(f, full_np, bg_np, al, at, ar, ab, anim_type, progress)
        return f

    try:
        # ── Voiceover-synced path ─────────────────────────────────────────────
        if element_delays is not None and len(element_delays) == n_elems:
            # Each element fades/wipes in over ELEM_ANIM_DUR seconds, starting
            # exactly when the narrator begins speaking about it.
            ELEM_ANIM_DUR = 0.4                      # seconds per element entrance
            n_ea          = max(2, int(fps * ELEM_ANIM_DUR))

            # Clamp every delay so the element + its animation burst fits inside
            # the slide duration.  This is essential when the user manually edits
            # slide durations in the debug table — the Whisper-computed delays can
            # exceed the new (shorter) duration, which would make the clip longer
            # than requested and shift every subsequent transition cut point.
            max_delay     = max(0.0, duration - ELEM_ANIM_DUR)
            safe_delays   = [max(0.0, min(d, max_delay)) for d in element_delays]

            # Sort elements by their (clamped) voiceover delay
            order    = sorted(range(n_elems), key=lambda i: safe_delays[i])
            revealed = set()
            t_cursor = 0.0   # seconds already accounted for

            for ei in order:
                d   = safe_delays[ei]
                gap = d - t_cursor

                # Static frame covering the gap before this element appears
                if gap > frame_dur * 0.5:
                    fp = _save_frame(_compose(revealed))
                    frame_list.append((fp, round(gap, 6)))

                # Short animation burst for this element
                for fi in range(n_ea):
                    prog = fi / max(n_ea - 1, 1)
                    fp   = _save_frame(_compose(revealed, active_ei=ei, progress=prog))
                    frame_list.append((fp, frame_dur))

                revealed.add(ei)
                t_cursor = d + ELEM_ANIM_DUR

            # Final hold: all elements fully visible for the rest of the slide.
            remaining = duration - t_cursor
            if remaining > frame_dur * 0.5:
                fp = _save_frame(full_np.copy())
                frame_list.append((fp, round(remaining, 6)))

            # Safety: always have at least one frame
            if not frame_list:
                fp = _save_frame(full_np.copy())
                frame_list.append((fp, duration))

            # Correct floating-point drift so the clip's total duration is exactly
            # `duration`.  Even 1-2 ms of cumulative error across many slides will
            # throw transition cut points off by a frame.
            actual_total = sum(d for _, d in frame_list)
            drift = duration - actual_total
            if abs(drift) > 1e-6 and frame_list:
                last_fp, last_dur = frame_list[-1]
                frame_list[-1] = (last_fp, round(max(frame_dur, last_dur + drift), 6))

        # ── Uniform animation path (original behaviour, unchanged) ────────────
        else:
            if anim_type == "char_overshoot_scale":
                FRAMES_PER_CHAR = 8
                n_anim     = max(2, min(n_elems * FRAMES_PER_CHAR, int(fps * 5.0)))
                total_anim = n_anim / fps
            else:
                total_anim = min(anim_dur * n_elems, 3.0)
                n_anim     = max(2, int(fps * total_anim))
            n_hold = max(1, int(fps * max(0.04, duration - total_anim)))

            for fi in range(n_anim):
                t_frac = fi / max(n_anim - 1, 1)
                frame  = bg_np.copy()
                for bi, (l, t_b, r, b, _kind) in enumerate(anim_elements):
                    ei_start = bi / n_elems
                    ei_end   = (bi + 1) / n_elems
                    progress = min(1.0, max(0.0,
                        (t_frac - ei_start) / max(ei_end - ei_start, 0.001)))
                    if progress <= 0:
                        continue
                    if t_frac >= ei_end:
                        frame[t_b:b, l:r] = full_np[t_b:b, l:r]
                        continue
                    _apply_elem_anim(frame, full_np, bg_np, l, t_b, r, b,
                                     anim_type, progress)
                fp = _save_frame(frame)
                frame_list.append((fp, frame_dur))

            for fi in range(n_hold):
                fp = _save_frame(full_np.copy())
                frame_list.append((fp, frame_dur))

        # ── Write FFmpeg concat list and encode ───────────────────────────────
        with open(concat_txt, "w", encoding="utf-8") as cf:
            for fp, dur in frame_list:
                cf.write(f"file '{fp.replace(chr(92), '/')}'\n")
                cf.write(f"duration {dur}\n")
            if frame_list:
                cf.write(f"file '{frame_list[-1][0].replace(chr(92), '/')}'\n")

        scale_vf = (f"scale={out_width}:{out_height}:force_original_aspect_ratio=decrease,"
                    f"pad={out_width}:{out_height}:(ow-iw)/2:(oh-ih)/2")
        cmd = [
            settings.ffmpeg_binary, "-y",
            "-f", "concat", "-safe", "0", "-i", concat_txt,
            "-vf", scale_vf,
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps),
            out_path,
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            raise RuntimeError(f"FFmpeg text-anim error slide {slide_idx + 1}: {r.stderr[-250:]}")

    finally:
        # Clean up temp frames
        try:
            import shutil as _sh
            _sh.rmtree(frame_dir, ignore_errors=True)
        except Exception:
            pass
        try:
            os.remove(concat_txt)
        except Exception:
            pass


def _concat_clips(clip_paths: list, abs_out: str):
    """Concatenate MP4 clips using the FFmpeg concat demuxer. Cleans up clips afterward."""
    list_file = abs_out + "_cl.txt"
    with open(list_file, "w", encoding="utf-8") as f:
        for p in clip_paths:
            f.write(f"file '{p.replace(chr(92), '/')}'\n")
    cmd = [
        settings.ffmpeg_binary, "-y",
        "-f", "concat", "-safe", "0", "-i", list_file,
        "-c", "copy", abs_out,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    for p in clip_paths:
        try:
            os.remove(p)
        except Exception:
            pass
    try:
        os.remove(list_file)
    except Exception:
        pass
    if r.returncode != 0:
        raise RuntimeError(f"FFmpeg concat error: {r.stderr[-300:]}")


def _get_video_duration(path: str) -> float:
    """Return video duration in seconds using ffprobe."""
    import json
    ffprobe = settings.ffmpeg_binary.replace("ffmpeg", "ffprobe").replace("ffmpeg.exe", "ffprobe.exe")
    r = subprocess.run(
        [ffprobe, "-v", "quiet", "-print_format", "json", "-show_streams", path],
        capture_output=True, text=True, timeout=30,
    )
    try:
        for s in json.loads(r.stdout or "{}").get("streams", []):
            if "duration" in s:
                return float(s["duration"])
    except Exception:
        pass
    return 0.0


def _apply_alpha_transitions(
    slide_clips: list,
    transition_clip: str,
    width: str,
    height: str,
    abs_out: str,
    overlap_frames: int = 15,
    fps: int = 25,
    slide_durations: list = None,   # optional: avoids probing each clip
) -> str:
    """
    Composite the custom transition clip over each slide cut so that it
    OVERLAPS the end of the outgoing clip and the start of the incoming clip.

    How it works
    ────────────
    1.  Concatenate all slide clips into a single base video (hard cuts).
    2.  Compute the cut points (seconds) = cumulative slide durations.
    3.  For every cut point T, offset the transition clip by (T - overlap_secs)
        using setpts, then overlay it with format=auto so the alpha channel is
        respected.  eof_action=pass restores the base video after the transition
        finishes.
    4.  Chain all overlays and encode once.

    Timeline illustration (overlap = 15 frames at 25 fps = 0.60 s):
        ┌──── slide A ────┬──── slide B ────┐
                    ↑ cut point T  (= transition frame 15 at 25 fps)
        ┌──── slide A ───[=== trans ===]─────────── slide B ──────┐
                       ↑ overlay starts at T - 0.60 s
    NOTE: fps here is the transition clip's frame rate (25), which also
    matches the base video fps.  The hard cut in the base video aligns with
    exactly frame 15 of the transition — the frame where the screen is fully
    covered — so the cover phase hides the cut and the reveal phase uncovers
    the incoming slide seamlessly.
    """
    overlap_secs = overlap_frames / fps
    ffmpeg = settings.ffmpeg_binary

    # ── Step 1: measure clip durations BEFORE building base (clips still exist)
    if slide_durations and len(slide_durations) == len(slide_clips):
        clip_durs = slide_durations
    else:
        clip_durs = [_get_video_duration(p) for p in slide_clips]

    # Quantize each clip duration to the nearest video-frame boundary (1/25 s).
    # Without this, floating-point accumulation in cut_times grows to 2–3 frames
    # of error by slide 20+, causing the transition overlay to land at the wrong
    # moment.  Rounding to the nearest frame keeps all cut_times sub-frame accurate.
    VIDEO_FPS = 25
    clip_durs = [round(round(d * VIDEO_FPS) / VIDEO_FPS, 6) for d in clip_durs]

    # ── Step 2: build base video (all slides, hard cuts) ─────────────────────
    base = abs_out + "_base.mp4"
    list_file = abs_out + "_base_cl.txt"
    with open(list_file, "w", encoding="utf-8") as f:
        for p in slide_clips:
            f.write(f"file '{p.replace(chr(92), '/')}'\n")
    r = subprocess.run(
        [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", list_file,
         "-c", "copy", base],
        capture_output=True, text=True, timeout=600,
    )
    try:
        os.remove(list_file)
    except Exception:
        pass
    if r.returncode != 0:
        raise RuntimeError(f"Base concat error: {r.stderr[-200:]}")

    # Clean up slide clips now that base is built
    for p in slide_clips:
        try:
            os.remove(p)
        except Exception:
            pass

    # ── Step 3: compute cut points (cumulative durations) ─────────────────────
    cut_times = []
    t_acc = 0.0
    for d in clip_durs[:-1]:   # last slide has no transition after it
        t_acc += d
        cut_times.append(round(t_acc, 4))

    if not cut_times:
        try:
            os.rename(base, abs_out)
        except Exception:
            pass
        return abs_out

    # ── Step 3: build filter_complex with chained overlays ────────────────────
    # Inputs: [0] base, [1..N] one copy of transition per cut
    n_cuts   = len(cut_times)
    w, h     = width, height
    scale_vf = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2")

    input_args = [ffmpeg, "-y", "-i", base]
    for _ in cut_times:
        input_args += ["-i", transition_clip]

    filter_parts = []
    prev_label   = "0:v"

    for idx, t_cut in enumerate(cut_times):
        t_start     = max(0.0, t_cut - overlap_secs)
        trans_input = idx + 1
        tr_label    = f"tr{idx}"
        ov_label    = f"ov{idx}"

        # Offset the transition so it starts at t_start in the base timeline
        filter_parts.append(
            f"[{trans_input}:v]{scale_vf},setpts=PTS+{t_start:.4f}/TB[{tr_label}]"
        )
        # Overlay with alpha support; after transition EOF, pass through base
        filter_parts.append(
            f"[{prev_label}][{tr_label}]overlay=0:0:format=auto:eof_action=pass[{ov_label}]"
        )
        prev_label = ov_label

    filter_complex = ";".join(filter_parts)

    cmd = input_args + [
        "-filter_complex", filter_complex,
        "-map",   f"[{prev_label}]",
        "-c:v",   "libx264",
        "-pix_fmt", "yuv420p",
        abs_out,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    try:
        os.remove(base)
    except Exception:
        pass
    if r.returncode != 0:
        raise RuntimeError(f"Alpha transition overlay error: {r.stderr[-400:]}")
    return abs_out


def build_video_from_images(
    images: list,
    output_path: str,
    slide_duration: float = 3.0,
    transition: str = "fade",
    resolution: str = "1920x1080",
    durations: list = None,        # per-slide durations; overrides slide_duration when given
    animation: str = "none",       # "none" | "fade_in" | "slide_in_right" | "zoom_in"
                                   # | "text_fade" | "text_slide_up" | "text_wipe"
    pptx_path: str = None,         # needed for text_* animation modes
    transition_clip: str = None,   # path to custom alpha/bumper transition video
    progress_callback=None,        # optional callable(fraction: float 0‥1)
    element_timing: list = None,   # [[delay_sec, …], …] voiceover-synced element delays
):
    """Use FFmpeg to stitch images into a video with transitions."""
    def _report(frac):
        if progress_callback:
            try:
                progress_callback(max(0.0, min(1.0, frac)))
            except Exception:
                pass
    width, height = resolution.split("x")

    # Build per-slide duration list
    if durations is None:
        durations = [slide_duration] * len(images)
    # Pad or trim to match image count
    while len(durations) < len(images):
        durations.append(slide_duration)
    durations = durations[:len(images)]

    # ── Text animation modes (PIL-based per-element animation) ───────────────
    TEXT_ANIM_MODES = {"text_fade", "text_slide_up", "text_wipe", "char_overshoot_scale"}
    if animation in TEXT_ANIM_MODES:
        clip_paths = []
        abs_out    = os.path.abspath(output_path)
        anim_dur   = 1.0   # seconds for text entrance
        out_w      = int(width)
        out_h      = int(height)

        n_slides = len(images)
        for i, (img, dur) in enumerate(zip(images, durations)):
            _report(i / n_slides)          # progress: 0% … (n-1)/n before concat
            clip = abs_out.replace(".mp4", f"_tclip{i}.mp4")
            # Per-slide element delays from voiceover sync (None → uniform fallback)
            slide_elem_delays = (
                element_timing[i]
                if element_timing and i < len(element_timing)
                else None
            )
            try:
                build_text_animated_clip(
                    full_png       = os.path.abspath(img),
                    pptx_path      = pptx_path,
                    slide_idx      = i,
                    duration       = dur,
                    anim_type      = animation,
                    out_path       = clip,
                    fps            = 25,
                    anim_dur       = min(anim_dur, dur * 0.4),
                    out_width      = out_w,
                    out_height     = out_h,
                    element_delays = slide_elem_delays,
                )
            except Exception as e:
                # Text animation failed — log and fall back to plain clip at target res
                import traceback
                print(f"[text_anim] Slide {i+1} failed: {e}")
                traceback.print_exc()
                cmd = [
                    settings.ffmpeg_binary, "-y",
                    "-loop", "1", "-t", str(dur), "-i", os.path.abspath(img),
                    "-vf", (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "25", clip,
                ]
                subprocess.run(cmd, capture_output=True, timeout=120)
            clip_paths.append(clip)

        _report(0.9)  # 90% — about to concatenate
        if transition_clip and os.path.exists(transition_clip) and len(clip_paths) > 1:
            _apply_alpha_transitions(clip_paths, transition_clip, width, height,
                                     abs_out, slide_durations=durations)
        else:
            _concat_clips(clip_paths, abs_out)
        _report(1.0)
        return

    # ── Per-slide slide/fade/zoom animation ──────────────────────────────────
    if animation != "none":
        anim_dur = 0.8  # seconds for the entrance effect
        clip_paths = []
        abs_out = os.path.abspath(output_path)

        n_slides = len(images)
        for i, (img, dur) in enumerate(zip(images, durations)):
            _report(i / n_slides)
            clip = abs_out.replace(".mp4", f"_aclip{i}.mp4")

            if animation == "fade_in":
                vf = (f"fade=t=in:st=0:d={anim_dur},"
                      f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                      f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2")
            elif animation == "slide_in_right":
                # Slide image in from the right edge
                vf = (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                      f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
                      f"crop={width}:{height}:"
                      f"'if(lt(t,{anim_dur}),(1-t/{anim_dur})*{width},0)':0")
            elif animation == "zoom_in":
                # Gentle zoom from 110% → 100%
                vf = (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                      f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
                      f"zoompan=z='if(lt(t,{anim_dur}),1.1-(0.1*t/{anim_dur}),1)'"
                      f":d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                      f":s={width}x{height}")
            else:
                vf = (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                      f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2")

            cmd = [
                settings.ffmpeg_binary, "-y",
                "-loop", "1", "-t", str(dur), "-i", os.path.abspath(img),
                "-vf", vf,
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-r", "25",
                clip,
            ]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if r.returncode != 0:
                raise RuntimeError(f"FFmpeg animation error slide {i+1}: {r.stderr[-300:]}")
            clip_paths.append(clip)

        _report(0.9)
        if transition_clip and os.path.exists(transition_clip) and len(clip_paths) > 1:
            _apply_alpha_transitions(clip_paths, transition_clip, width, height, abs_out)
        else:
            _concat_clips(clip_paths, abs_out)
        _report(1.0)
        return   # done

    # ── Static (no per-slide animation) ──────────────────────────────────────
    # When a custom transition clip is provided, build individual slide clips
    # then apply alpha transitions between them.
    abs_out = os.path.abspath(output_path)
    if transition_clip and os.path.exists(transition_clip) and len(images) > 1:
        plain_clips = []
        n_slides = len(images)
        for i, (img, dur) in enumerate(zip(images, durations)):
            _report(i / n_slides)
            clip = abs_out.replace(".mp4", f"_plain{i}.mp4")
            cmd = [
                settings.ffmpeg_binary, "-y",
                "-loop", "1", "-t", str(dur), "-i", os.path.abspath(img),
                "-vf", (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "25", clip,
            ]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if r.returncode != 0:
                raise RuntimeError(f"FFmpeg slide clip error {i+1}: {r.stderr[-200:]}")
            plain_clips.append(clip)
        _report(0.9)
        _apply_alpha_transitions(plain_clips, transition_clip, width, height,
                                 abs_out, slide_durations=durations)
        _report(1.0)
        return

    if transition == "none" or len(images) == 1:
        # concat demuxer — supports per-slide durations natively
        list_file = abs_out + ".txt"
        with open(list_file, "w", encoding="utf-8") as f:
            for img, dur in zip(images, durations):
                abs_img = os.path.abspath(img).replace("\\", "/")
                f.write(f"file '{abs_img}'\n")
                f.write(f"duration {dur}\n")
        cmd = [
            settings.ffmpeg_binary,
            "-y", "-f", "concat", "-safe", "0",
            "-i", list_file,
            "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                   f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            abs_out,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        try:
            os.remove(list_file)
        except Exception:
            pass
    else:
        # xfade transitions — use per-slide durations for each segment
        # Quantize each duration to a 25 fps frame boundary before accumulating
        # offsets; without this, floating-point drift reaches 3-4 frames by the
        # 6-7 minute mark (~80-90 slides at ~5 s/slide).
        _XFADE_FPS = 25
        q_durations = [round(round(d * _XFADE_FPS) / _XFADE_FPS, 6) for d in durations]

        inputs = []
        for img, dur in zip(images, q_durations):
            inputs += ["-loop", "1", "-t", str(dur + 0.5), "-i", img]

        n = len(images)
        filter_parts = []
        for i in range(n):
            filter_parts.append(
                f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1[v{i}]"
            )

        xfade_parts = []
        prev = "v0"
        offset = q_durations[0] - 0.5
        for i in range(1, n):
            out = f"xf{i}"
            xfade_parts.append(
                f"[{prev}][v{i}]xfade=transition={transition}:duration=0.5:offset={offset:.6f}[{out}]"
            )
            prev = out
            offset += q_durations[i] - 0.5

        filter_complex = ";".join(filter_parts + xfade_parts)
        cmd = [settings.ffmpeg_binary, "-y"] + inputs + [
            "-filter_complex", filter_complex,
            "-map", f"[{prev}]",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            abs_out,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg error: {result.stderr[-500:]}")


def run_slides_to_video(
    job_id: str,
    pptx_path: str,
    slide_duration: float,
    transition: str,
    resolution: str,
    animation: str = "none",
    transition_clip_id: str = None,   # filename inside video_output_dir/transitions/
):
    job = job_store.get(job_id)

    # Persistent frames directory — NOT deleted after conversion so merge can reuse them
    frames_dir = str(Path(settings.video_output_dir) / f"{job_id}_frames")
    Path(frames_dir).mkdir(parents=True, exist_ok=True)

    # Resolve custom transition clip path
    transition_clip_path = None
    if transition_clip_id:
        candidate = str(Path(settings.video_output_dir) / "transitions" / transition_clip_id)
        if os.path.exists(candidate):
            transition_clip_path = candidate

    try:
        job.update(status="processing", progress=10, message="Converting slides to images...")

        # Copy PPTX into frames dir so sync can extract text later
        import shutil as _shutil
        import json as _json
        pptx_copy = str(Path(frames_dir) / "source.pptx")
        _shutil.copy2(pptx_path, pptx_copy)

        images = convert_pptx_to_images(pptx_path, frames_dir)
        if not images:
            raise RuntimeError("No slides found in the uploaded file.")

        # Extract and save per-slide text for AI sync
        slide_data = extract_slide_texts(pptx_copy, len(images))
        with open(str(Path(frames_dir) / "slide_texts.json"), "w", encoding="utf-8") as f:
            _json.dump(slide_data["bodies"], f, ensure_ascii=False)
        with open(str(Path(frames_dir) / "slide_titles.json"), "w", encoding="utf-8") as f:
            _json.dump(slide_data["titles"], f, ensure_ascii=False)

        job.update(progress=50, message=f"Stitching {len(images)} slides into video...")
        output_filename = f"{job_id}_slides.mp4"
        output_path = str(Path(settings.video_output_dir) / output_filename)

        def _stitch_progress(frac, _job=job, _n=len(images)):
            # Maps 0‥1 → 50%‥95% so the bar moves through rendering
            p = 50 + int(frac * 45)
            done = max(1, round(frac * _n))
            _job.update(progress=p, message=f"Rendering slide {done}/{_n}…")

        build_video_from_images(
            images, output_path, slide_duration, transition, resolution,
            animation=animation,
            pptx_path=pptx_copy,
            transition_clip=transition_clip_path,
            progress_callback=_stitch_progress,
        )

        job.update(
            status="done",
            progress=100,
            message="Slides video created successfully!",
            result={
                "video_url": f"/videos/{output_filename}",
                "filename": output_filename,
                "slide_count": len(images),
                "frames_job_id": job_id,
                "transition": transition,
                "resolution": resolution,
                "animation": animation,
                "transition_clip_id": transition_clip_id,
            },
        )
    except Exception as e:
        job.update(error=str(e))
    finally:
        # Only clean up the uploaded PPTX — keep the frames directory
        if os.path.exists(pptx_path):
            try:
                os.remove(pptx_path)
            except Exception:
                pass


@router.post("/convert")
async def convert_slides(
    background_tasks: BackgroundTasks,
    slide_duration: float = Form(3.0),
    transition: str = Form("fade"),
    resolution: str = Form("1920x1080"),
    animation: str = Form("none"),
    transition_clip_id: str = Form(""),    # ID returned by /upload-transition
    file: UploadFile = File(...),
):
    """
    Convert a .pptx file into a silent video.
    Slide frames are kept for per-slide timing during merge.
    """
    if not file.filename.lower().endswith((".pptx", ".ppt", ".pdf")):
        raise HTTPException(status_code=400, detail="Please upload a .pptx, .ppt, or .pdf file.")

    upload_path = str(Path(settings.upload_dir) / f"{file.filename}")
    with open(upload_path, "wb") as f:
        content = await file.read()
        f.write(content)

    job = job_store.create()
    background_tasks.add_task(
        run_slides_to_video, job.job_id, upload_path, slide_duration, transition, resolution,
        animation, transition_clip_id or None,
    )

    return {"job_id": job.job_id, "status": "pending"}


@router.post("/upload-transition")
async def upload_transition(file: UploadFile = File(...)):
    """
    Accept a custom transition clip (MP4, WebM with alpha, MOV ProRes 4444, etc.)
    and store it in the transitions directory.  Returns a transition_clip_id that
    can be passed back to /convert.
    """
    import uuid as _uuid
    allowed = (".mp4", ".mov", ".avi", ".webm", ".mkv")
    if not file.filename.lower().endswith(allowed):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format. Allowed: {', '.join(allowed)}"
        )
    trans_dir = Path(settings.video_output_dir) / "transitions"
    trans_dir.mkdir(parents=True, exist_ok=True)
    ext = os.path.splitext(file.filename)[1].lower()
    clip_id  = f"{_uuid.uuid4()}_trans{ext}"
    out_path = str(trans_dir / clip_id)
    with open(out_path, "wb") as fp:
        fp.write(await file.read())
    return {"transition_clip_id": clip_id, "filename": file.filename}


@router.post("/upload-video")
async def upload_video(file: UploadFile = File(...)):
    """Accept a pre-made video file and save it to the video output directory."""
    import uuid
    allowed = (".mp4", ".mov", ".avi", ".mkv", ".webm")
    if not file.filename.lower().endswith(allowed):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported video format. Allowed: {', '.join(allowed)}"
        )
    ext = os.path.splitext(file.filename)[1].lower()
    filename = f"{uuid.uuid4()}_slides{ext}"
    output_path = str(Path(settings.video_output_dir) / filename)
    with open(output_path, "wb") as f:
        f.write(await file.read())
    return {
        "video_url": f"/videos/{filename}",
        "filename": filename,
        "slide_count": None,      # unknown for uploaded videos
        "frames_job_id": None,    # no frames — auto_fit/per_slide unavailable
        "transition": "none",
        "resolution": "1920x1080",
    }


@router.post("/refresh-texts/{job_id}")
def refresh_texts(job_id: str):
    """
    Re-extract slide titles and body text from the stored source.pptx WITHOUT
    re-converting the whole presentation.  Call this after upgrading the backend
    when old frames dirs have stale / empty slide_titles.json files.
    """
    import json as _json
    frames_dir = Path(settings.video_output_dir) / f"{job_id}_frames"
    pptx_copy  = frames_dir / "source.pptx"

    if not frames_dir.exists():
        raise HTTPException(status_code=404, detail="Frames directory not found.")
    if not pptx_copy.exists():
        raise HTTPException(status_code=404, detail="source.pptx not found in frames dir.")

    frame_files = sorted(frames_dir.glob("slide_*.png"))
    n_slides    = len(frame_files)
    if n_slides == 0:
        raise HTTPException(status_code=404, detail="No slide frames found.")

    slide_data = extract_slide_texts(str(pptx_copy), n_slides)

    with open(str(frames_dir / "slide_texts.json"),  "w", encoding="utf-8") as f:
        _json.dump(slide_data["bodies"], f, ensure_ascii=False)
    with open(str(frames_dir / "slide_titles.json"), "w", encoding="utf-8") as f:
        _json.dump(slide_data["titles"], f, ensure_ascii=False)

    non_empty = sum(1 for t in slide_data["titles"] if t)
    return {
        "job_id": job_id,
        "slide_count": n_slides,
        "titles_extracted": non_empty,
        "titles": slide_data["titles"],
    }


@router.get("/debug-texts/{job_id}")
def debug_texts(job_id: str, slide: int = 1):
    """
    Diagnostic: return every shape found on a given slide (1-based) with its
    text, shape type, placeholder info and name.  Use this when titles are not
    being extracted to understand the PPTX structure.
    """
    frames_dir = Path(settings.video_output_dir) / f"{job_id}_frames"
    pptx_copy  = frames_dir / "source.pptx"
    if not pptx_copy.exists():
        raise HTTPException(status_code=404, detail="source.pptx not found.")

    try:
        from pptx import Presentation
        prs       = Presentation(str(pptx_copy))
        slide_idx = slide - 1
        if slide_idx >= len(prs.slides):
            raise HTTPException(status_code=404, detail=f"Slide {slide} not found.")

        result = []
        for shape in _iter_shapes(prs.slides[slide_idx].shapes):
            ph     = getattr(shape, "placeholder_format", None)
            text   = ""
            if shape.has_text_frame:
                try:
                    text = shape.text_frame.text.strip()[:120]
                except Exception:
                    text = "<error reading text>"
            result.append({
                "name":       shape.name,
                "shape_type": str(shape.shape_type),
                "has_text":   shape.has_text_frame,
                "text":       text,
                "ph_type":    str(ph.type) if ph else None,
                "ph_idx":     ph.idx if ph else None,
            })

        return {"slide": slide, "total_slides": len(prs.slides), "shapes": result}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/frames/{job_id}")
def get_frames(job_id: str):
    """Return thumbnail URLs for each slide frame stored from a previous conversion."""
    frames_dir = Path(settings.video_output_dir) / f"{job_id}_frames"
    if not frames_dir.exists():
        raise HTTPException(status_code=404, detail="Frames not found for this job.")

    frame_files = sorted(frames_dir.glob("slide_*.png"))
    if not frame_files:
        raise HTTPException(status_code=404, detail="No frame images found.")

    return {
        "frames": [
            {"index": i + 1, "url": f"/videos/{job_id}_frames/{f.name}"}
            for i, f in enumerate(frame_files)
        ]
    }
