from __future__ import annotations

import io
import re
from collections import Counter
from typing import Dict, Optional, Tuple


try:  # Optional dependency (preferred).
    from pypdf import PdfReader  # type: ignore
except Exception:  # pragma: no cover
    PdfReader = None  # type: ignore[assignment]


_BOX_RE = re.compile(
    r"/(?P<box>CropBox|MediaBox)\s*\[\s*(?P<x0>-?\d+(?:\.\d+)?)\s+(?P<y0>-?\d+(?:\.\d+)?)\s+(?P<x1>-?\d+(?:\.\d+)?)\s+(?P<y1>-?\d+(?:\.\d+)?)\s*\]"
)


def get_pdf_page_sizes(pdf_bytes: bytes) -> Dict[int, Tuple[float, float]]:
    """
    Return per-page (width_pt, height_pt) sizes.

    Preferred: parse PDF properly via pypdf and read CropBox/MediaBox + Rotate per page.
    Fallback: best-effort heuristic that returns a dominant document size as page 0 only.
    """
    if not pdf_bytes:
        return {}

    if PdfReader is not None:
        try:
            reader = PdfReader(io.BytesIO(pdf_bytes))
            out: Dict[int, Tuple[float, float]] = {}
            for i, page in enumerate(reader.pages):
                # Prefer CropBox as it matches viewer display area; fall back to MediaBox.
                box = getattr(page, "cropbox", None) or getattr(page, "mediabox", None)
                if not box:
                    continue

                w = float(box.width)
                h = float(box.height)

                rotate = 0
                try:
                    rotate = int(getattr(page, "rotation", 0) or 0)
                except Exception:
                    rotate = 0
                if rotate % 180 != 0:
                    w, h = h, w

                if w > 0 and h > 0:
                    out[i] = (w, h)
            if out:
                return out
        except Exception:
            # Fall back to heuristic below.
            pass

    # Heuristic fallback: estimate a dominant size for the document, expose as page 0.
    est = estimate_dominant_pdf_page_size(pdf_bytes)
    return {0: est} if est else {}


def estimate_dominant_pdf_page_size(pdf_bytes: bytes) -> Optional[Tuple[float, float]]:
    """
    Best-effort dominant page size estimation from raw PDF bytes (no parsing).
    Prefer CropBox over MediaBox. Returns (width_pt, height_pt) in PDF points, or None.
    """
    if not pdf_bytes:
        return None

    try:
        s = pdf_bytes.decode("latin-1", errors="ignore")
    except Exception:
        return None

    candidates: list[tuple[tuple[float, float], int]] = []
    for m in _BOX_RE.finditer(s):
        box = m.group("box")
        try:
            x0 = float(m.group("x0"))
            y0 = float(m.group("y0"))
            x1 = float(m.group("x1"))
            y1 = float(m.group("y1"))
        except ValueError:
            continue
        w = x1 - x0
        h = y1 - y0
        if w <= 0 or h <= 0:
            continue

        key = (round(w, 2), round(h, 2))
        score = 2 if box == "CropBox" else 1
        candidates.append((key, score))

    if not candidates:
        return None

    counts = Counter([k for k, _ in candidates])
    pref: dict[tuple[float, float], int] = {}
    for k, score in candidates:
        pref[k] = pref.get(k, 0) + score

    best_key = None
    best = (-1, -1)
    for k, c in counts.items():
        p = pref.get(k, 0)
        cur = (c, p)
        if cur > best:
            best = cur
            best_key = k

    return best_key


def get_page_size(page_sizes: Dict[int, Tuple[float, float]], page_index: int) -> Optional[Tuple[float, float]]:
    if page_index in page_sizes:
        return page_sizes[page_index]
    if 0 in page_sizes:
        return page_sizes[0]
    return None
