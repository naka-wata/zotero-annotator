from __future__ import annotations

import re
from hashlib import sha1
from statistics import median
from typing import List

from zotero_annotator.config import CoreSettings
from zotero_annotator.services.paragraphs import Paragraph, ParagraphCoord
from zotero_annotator.services.pymupdf_paragraphs import ExtractionConfig, extract_paragraphs_pymupdf_bytes
from zotero_annotator.utils.text import normalize_text


_LEADING_CONTINUATION_RE = re.compile(r"^([a-z]|[,\)\]])")
_SENTENCE_END_RE = re.compile(r'[.!?][\"\'\)\]]*\s*$')
_CONNECTORISH_RE = re.compile(r"^(?:[a-z]|[,)\]\}]|and\b|or\b|where\b|which\b|that\b)")
_CAPTION_START_RE = re.compile(
    r"^(?:Figure|Fig\.?|Table|Tbl\.?|FIGURE|TABLE|図|表)\s*(?:\d+|[IVXLC]+)\s*(?:[:\.])",
    flags=re.IGNORECASE,
)

# Section headings like:
# - "6 Conclusion"
# - "4.1 Preprocessing and Model Architecture"
# - "IV Results"
# Allow lowercase connector words (and/of/in/for/...) to avoid missing common titles.
_SECTION_HEADING_RE = re.compile(
    r"^(?:(?:\d{1,2}(?:\.\d{1,2})*)|(?:[IVXLC]{1,6}))\s+"
    r"(?:[A-Za-z][A-Za-z0-9-]*)(?:\s+(?:[A-Za-z][A-Za-z0-9-]*|and|or|of|in|on|for|to|with|without|via|vs\.?|the|a|an|by|from|into|over|under|between|across|using))*$",
    flags=re.IGNORECASE,
)
_BARE_HEADING_RE = re.compile(
    r"^(?:Abstract|Introduction|Background|Conclusion|Conclusions|Related Work|References|Acknowledg(?:e)?ments?)$",
    flags=re.IGNORECASE,
)

_REFERENCES_HEADING_RE = re.compile(r"^\s*(?:References|Bibliography)\s*$", flags=re.IGNORECASE)
_BIB_ENTRY_RE = re.compile(r"^\s*(?:\[\s*\d{1,4}\s*\]|\d{1,4}\.)\s+\S")

def _is_sentence_like(text: str) -> bool:
    s = normalize_text(text)
    if not s:
        return False
    if not re.search(r"[a-z]", s):
        return False
    words = s.split()
    if len(words) < 6:
        return False
    return bool(_SENTENCE_END_RE.search(s))


def _table_like_score(text: str) -> float:
    """
    Score how much a paragraph looks like a table row / table body text.
    (0.0 -> not table-like, 1.0 -> very table-like)
    """
    s = normalize_text(text)
    if not s:
        return 0.0
    tokens = [t for t in re.split(r"\s+", s) if t]
    if not tokens:
        return 0.0

    num = 0
    short = 0
    alpha = 0
    caps = 0
    for t in tokens:
        if re.fullmatch(r"[\+\-−]?\d+(?:\.\d+)?%?", t):
            num += 1
        if len(t) <= 2:
            short += 1
        if re.search(r"[A-Za-z]", t):
            alpha += 1
            if t[:1].isupper() or t.endswith("."):
                caps += 1

    numeric_ratio = num / max(1, len(tokens))
    short_ratio = short / max(1, len(tokens))
    cap_ratio = caps / max(1, alpha)
    sentencey = 1.0 if _is_sentence_like(s) else 0.0
    score = (
        0.55 * numeric_ratio
        + 0.22 * short_ratio
        + 0.18 * cap_ratio
        + 0.15 * (1.0 if len(tokens) >= 12 else 0.0)
        - 0.7 * sentencey
    )
    return max(0.0, min(1.0, score))


def _is_caption_start(text: str) -> bool:
    return bool(_CAPTION_START_RE.search((text or "").strip()))


def _is_caption_continuation(text: str) -> bool:
    """
    Heuristic: short, list-like fragment that likely continues a caption.

    Example: "Seaquest, Beam Rider"
    """
    s = (text or "").strip()
    if not s:
        return False
    if len(s) > 120:
        return False
    # Avoid merging real body text that starts with lowercase.
    if s[:1].islower():
        return False
    if "," in s:
        return True
    words = s.split()
    return len(words) <= 6



def _is_section_heading(text: str) -> bool:
    """
    Detect section/chapter headings we don't want to annotate.

    Examples:
      - "6 Conclusion"
      - "2.3 Experimental Setup"
      - "IV Results"
      - "References"
    """
    s = normalize_text(text)
    if not s:
        return False
    if len(s) > 80:
        return False
    # Avoid catching captions or sentence-like lines.
    if _is_caption_start(s):
        return False
    if _SENTENCE_END_RE.search(s):
        return False
    # Headings rarely contain commas/semicolons; these often indicate real sentences.
    if any(ch in s for ch in (",", ";")):
        return False
    # Avoid math / code-ish lines.
    if any(ch in s for ch in ("=", "∈", "→", "←", "{", "}", "\\", "_")):
        return False

    # Strong heuristic for numbered headings: "4.1 Title ..." (common in papers).
    # Keep it simple and conservative to reduce false positives.
    if re.match(r"^\d{1,2}(?:\.\d{1,2})*\s+", s):
        words = s.split()
        if 2 <= len(words) <= 18 and re.search(r"[A-Za-z]", s) and not s.endswith((".", ":", ";")):
            return True

    # Roman numeral headings: "IV Results"
    if re.match(r"^[IVXLC]{1,6}\s+", s, flags=re.IGNORECASE):
        words = s.split()
        if 2 <= len(words) <= 12 and re.search(r"[A-Za-z]", s) and not s.endswith((".", ":", ";")):
            return True

    if _SECTION_HEADING_RE.match(s):
        # Guard against accidental matches to long-ish prose.
        if len(s.split()) > 18:
            return False
        return True
    if _BARE_HEADING_RE.match(s):
        return True
    return False


def _hash_text(text: str) -> str:
    return sha1(normalize_text(text).encode("utf-8")).hexdigest()


def _merge_leading_continuations(paragraphs: List[Paragraph]) -> List[Paragraph]:
    if not paragraphs:
        return paragraphs

    out: List[Paragraph] = []
    for p in paragraphs:
        if not out:
            out.append(p)
            continue

        prev = out[-1]
        cur_text = (p.text or "").lstrip()
        prev_text = (prev.text or "").rstrip()

        prev_is_captionish = _is_caption_start(prev_text) or _is_caption_continuation(prev_text)
        cur_is_caption_cont = _is_caption_continuation(cur_text)

        # Allow merge within the same page, and also across a page break (prev_end_page -> cur_start_page).
        can_merge_across_pages = True
        if prev.coords and p.coords:
            prev_end_page = max(c.page for c in prev.coords)
            cur_start_page = min(c.page for c in p.coords)
            if not (cur_start_page == prev_end_page or cur_start_page == prev_end_page + 1):
                can_merge_across_pages = False
        else:
            if prev.page is not None and p.page is not None and prev.page != p.page:
                can_merge_across_pages = False

        should_try_merge = bool(_LEADING_CONTINUATION_RE.match(cur_text))
        prev_ends_sentence = bool(_SENTENCE_END_RE.search(prev_text))

        # Never merge body text into caption-like paragraphs.
        # This prevents: "Figure 1: ... Space Invaders," + "an experience ..." -> merged.
        if prev_is_captionish and not cur_is_caption_cont:
            out.append(p)
            continue

        # But do merge short caption continuation fragments into the caption.
        if can_merge_across_pages and prev_is_captionish and cur_is_caption_cont:
            merged = f"{prev.text.rstrip()} {p.text.lstrip()}".strip()
            out[-1] = Paragraph(
                text=merged,
                hash=_hash_text(merged),
                dedup_hashes=[_hash_text(merged)],
                coords=(prev.coords or []) + (p.coords or []),
                page=prev.page,
            )
            continue

        if can_merge_across_pages and should_try_merge and not prev_ends_sentence:
            merged = f"{prev.text.rstrip()} {p.text.lstrip()}".strip()
            out[-1] = Paragraph(
                text=merged,
                hash=_hash_text(merged),
                dedup_hashes=[_hash_text(merged)],
                coords=(prev.coords or []) + (p.coords or []),
                page=prev.page,
            )
            continue

        out.append(p)

    return out


def _split_pymupdf_paragraph_by_lines(
    *,
    text: str,
    line_items: list,
    max_chars: int,
) -> list[tuple[str, list]]:
    """
    Split a PyMuPDF paragraph using its per-line items, so we can keep accurate bboxes.

    Returns: [(chunk_text, chunk_line_items), ...]
    """
    norm = normalize_text(text)
    if not norm:
        return []
    if max_chars <= 0 or len(norm) <= max_chars or not line_items:
        return [(norm, list(line_items))]

    chunks: list[tuple[str, list]] = []
    cur: list = []
    cur_len = 0

    def flush(n: int) -> None:
        nonlocal cur, cur_len
        take = cur[:n]
        cur = cur[n:]
        cur_len = sum(len((li.get("text") or "").strip()) + 1 for li in cur if isinstance(li, dict))
        chunk_text = normalize_text(
            " ".join((li.get("text") or "").strip() for li in take if isinstance(li, dict) and (li.get("text") or "").strip())
        )
        if chunk_text:
            chunks.append((chunk_text, take))

    for li in line_items:
        if not isinstance(li, dict):
            continue
        lt = (li.get("text") or "").strip()
        if not lt:
            continue

        add_len = len(lt) + (1 if cur else 0)
        if cur and (cur_len + add_len) > max_chars:
            # Prefer breaking at a sentence-ending line inside current buffer.
            break_at = None
            for i in range(len(cur) - 1, -1, -1):
                if not isinstance(cur[i], dict):
                    continue
                if _SENTENCE_END_RE.search((cur[i].get("text") or "").rstrip()):
                    break_at = i + 1
                    break
            if break_at is None:
                break_at = max(1, len(cur))
            flush(break_at)

        cur.append(li)
        cur_len += add_len

    if cur:
        flush(len(cur))

    return chunks


def extract_paragraphs_from_pdf_bytes(
    pdf_bytes: bytes,
    *,
    settings: CoreSettings,
) -> List[Paragraph]:
    """
    Paragraph extraction entrypoint (PyMuPDF-only backend).

    Returns Paragraph objects compatible with the rest of the pipeline.
    """
    # Note: PyMuPDF extraction returns JSON-like dicts:
    # {text, pages, bboxes, is_caption, _median_font_size}.
    cfg = ExtractionConfig(drop_algorithms=bool(settings.para_skip_algorithms))
    raw = extract_paragraphs_pymupdf_bytes(pdf_bytes, config=cfg)

    # Optionally drop captions at this stage (keep for debugging when disabled).
    if settings.para_skip_captions:
        raw = [p for p in raw if not p.get("is_caption")]

    paras: List[Paragraph] = []
    font_medians = [
        float(p.get("_median_font_size") or 0.0)
        for p in raw
        if float(p.get("_median_font_size") or 0.0) > 0
    ]

    # Reuse PARA_MIN_MEDIAN_COORD_H as "min median font size" when using PyMuPDF backend.
    min_med = settings.para_min_median_coord_h
    font_threshold = 0.0
    if isinstance(min_med, (int, float)):
        font_threshold = float(min_med)
    elif min_med == "auto" and font_medians:
        q75 = sorted(font_medians)[int(round(0.75 * (len(font_medians) - 1)))]
        font_threshold = float(q75) * float(settings.para_min_median_coord_h_auto_ratio)

    in_refs = False
    for p in raw:
        text = (p.get("text") or "").strip()
        if not text:
            continue
        if settings.para_skip_references and _REFERENCES_HEADING_RE.match(text):
            in_refs = True
            continue
        if settings.para_skip_references and (in_refs or _BIB_ENTRY_RE.match(text)):
            continue
        if _is_section_heading(text):
            continue
        if settings.para_skip_table_like and (not p.get("is_caption")):
            # Avoid annotating dense numeric table rows like:
            # "B. Rider Breakout ... Random 354 1.2 0 ..."
            # Keep this conservative so prose with occasional numbers survives.
            toks = normalize_text(text).split()
            if len(toks) >= 14 and _table_like_score(text) >= 0.35:
                continue
        if len(text) < int(settings.para_min_chars):
            continue
        if len(text) > int(settings.para_max_chars):
            continue

        med_fs = float(p.get("_median_font_size") or 0.0)
        if font_threshold and med_fs and med_fs < font_threshold:
            continue

        coords: List[ParagraphCoord] = []

        # Prefer a small anchor bbox (topmost line) for note placement.
        anchor = p.get("_anchor")
        if isinstance(anchor, dict) and all(k in anchor for k in ("page", "x0", "y0", "x1", "y1")):
            try:
                page = int(anchor["page"])
                x0 = float(anchor["x0"])
                y0 = float(anchor["y0"])
                x1 = float(anchor["x1"])
                y1 = float(anchor["y1"])
            except Exception:
                page = 0
            else:
                coords.append(ParagraphCoord(page=page, x=x0, y=y0, w=(x1 - x0), h=(y1 - y0)))
        else:
            for bb in (p.get("bboxes") or []):
                if not isinstance(bb, dict):
                    continue
                try:
                    page = int(bb["page"])
                    x0 = float(bb["x0"])
                    y0 = float(bb["y0"])
                    x1 = float(bb["x1"])
                    y1 = float(bb["y1"])
                except Exception:
                    continue
                coords.append(ParagraphCoord(page=page, x=x0, y=y0, w=(x1 - x0), h=(y1 - y0)))

        pages = p.get("pages") or []
        first_page = int(pages[0]) if pages else (coords[0].page if coords else None)
        h = _hash_text(text)
        paras.append(Paragraph(text=text, hash=h, dedup_hashes=[h], coords=coords, page=first_page))

    paras = _merge_leading_continuations(paras)
    return paras
