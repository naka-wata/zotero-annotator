from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median
from typing import Any, Dict, List, Optional, Sequence, Tuple
from xml.etree import ElementTree as ET


try:
    import fitz  # PyMuPDF
except Exception as exc:  # pragma: no cover
    fitz = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc
else:  # pragma: no cover
    _IMPORT_ERROR = None


@dataclass(frozen=True)
class ExtractionConfig:
    # Column detection
    column_split_ratio: float = 0.5  # page_w * ratio

    # Line/paragraph thresholds
    paragraph_gap_line_height_mult: float = 1.5
    # Secondary paragraph break: sentence boundary + moderate vertical gap.
    # Useful for papers that do not insert a full blank line between paragraphs.
    sentence_gap_line_height_mult: float = 0.6
    # Allow a paragraph to continue from the bottom of the left column to the top of the
    # right column on the same page (common in 2-column papers).
    allow_cross_column_continuations: bool = True
    cross_column_prev_bottom_ratio: float = 0.18  # prev line must end within bottom 18% of page
    cross_column_next_top_ratio: float = 0.22  # next line must start within top 22% of page
    cross_page_gap_line_height_mult: float = 2.0
    block_merge_gap_line_height_mult: float = 1.5
    # Cross-page merge when captions intervene (本文段落の途中にキャプションが割り込むケース)
    cross_page_skip_captions: bool = True
    cross_page_skip_caption_max_paragraphs: int = 3
    cross_page_prev_bottom_max_lines: float = 8.0  # remaining space < lines * avg_h
    # If the previous paragraph ends mid-page (due to floats), allow a slightly larger remaining space
    # when the paragraph ends with a connector (", where", "and", etc.).
    cross_page_prev_bottom_max_lines_relaxed: float = 14.0
    cross_page_next_top_max_ratio: float = 0.45  # continuation starts within top 45% of page
    # When there are figure/table captions at the top of the next page, the continuation can start much lower.
    cross_page_next_top_max_ratio_with_captions: float = 0.85
    cross_page_x0_tol_ratio: float = 0.05  # abs(x0 diff) < ratio * page_w
    cross_page_require_lowercase_start: bool = True
    cross_page_search_back: int = 40  # scan up to N previous paragraphs for a better merge candidate

    # Block merge heuristics
    overlap_min_ratio: float = 0.2
    font_size_rel_tol: float = 0.25

    # Caption detection
    caption_re: str = r"^(?:Figure|Fig\.?|Table|Tbl\.?)\s*(?:\d+|[IVXLC]+)\s*(?:[:\.])"
    caption_center_tol_ratio: float = 0.12
    caption_width_ratio: float = 0.75
    # Avoid misclassifying centered headings / author lists as captions.
    caption_centered_requires_number: bool = True
    caption_centered_number_re: str = r"\b\d+\b"
    caption_centered_keyword_re: str = r"\b(?:Figure|Fig\.?|Table|Tbl\.?)\b"

    # Noise filtering (e.g., vertical arXiv sidebar text with a tall bbox)
    drop_narrow_tall_lines: bool = True
    narrow_line_width_ratio: float = 0.08  # width < page_w * ratio
    tall_line_height_ratio: float = 0.25  # height > page_h * ratio

    # Headings (e.g., "Abstract", section titles)
    split_headings: bool = True
    heading_font_size_mult: float = 1.2
    heading_max_chars: int = 40
    # Heading detection by text pattern (font-size independent)
    heading_numbered_re: str = r"^(?:\d{1,2}(?:\.\d{1,2})*)\s+\S"
    heading_numbered_max_chars: int = 90
    heading_numbered_max_words: int = 14
    # After splitting headings into separate paragraphs, drop heading-only entries from output.
    drop_heading_paragraphs: bool = True

    # Caption multiline handling
    caption_multiline_max_lines: int = 12
    caption_multiline_gap_line_height_mult: float = 1.6

    # Page number removal (header/footer)
    drop_page_numbers: bool = True
    page_number_re: str = r"^\d{1,4}$"
    page_number_margin_ratio: float = 0.08  # within top/bottom 8% of page height
    page_number_center_tol_ratio: float = 0.12  # center near page center (optional)

    # Footnote removal (bottom-of-page notes like "1In fact ...")
    drop_footnotes: bool = True
    footnote_margin_ratio: float = 0.12  # within bottom 12% of page height
    footnote_font_size_mult: float = 0.92  # footnotes are often smaller than body text
    footnote_start_re: str = r"^\s*\d{1,2}\s*[A-Za-z]"
    footnote_continuation_max_lines: int = 6
    footnote_continuation_gap_line_height_mult: float = 1.3
    # Prefer statistical body-band detection (within-page) over fixed ratios.
    # When disabled or when body-band stats cannot be computed, fall back to ratio-based rules.
    prefer_statistical_body_band: bool = True
    body_band_q_low: float = 0.06   # lower quantile for body lines' y0
    body_band_q_high: float = 0.94  # upper quantile for body lines' y1
    body_band_pad_lines: float = 2.0  # expand body band by N * body_line_height
    outside_body_band_pad_lines: float = 1.0  # how far outside band we consider "header/footer region"

    # Repeated running headers/footers (e.g., "Published as ...", paper title on every page)
    drop_running_headers_footers: bool = True
    running_header_footer_margin_ratio: float = 0.08
    running_header_footer_min_pages: int = 3
    running_header_footer_min_len: int = 12

    # Front matter (title / authors / affiliations) removal on the first page.
    # This keeps the main content (typically starting at Abstract/Introduction) while
    # avoiding noisy annotations on metadata.
    drop_front_matter: bool = True
    front_matter_stop_re: str = r"^\s*(?:Abstract|(?:\d+\s+)?Introduction)\b"
    # Treat everything after REFERENCES as non-main-paper content.
    skip_after_references: bool = True
    references_heading_re: str = r"^(?:(?:\d{1,2}(?:\.\d{1,2})*)\s+)?(?:references|bibliography|works cited|literature cited)\b"
    references_min_position_ratio: float = 0.30
    references_confirmation_window: int = 2
    references_confirmation_needed: int = 1
    # Drop tiny standalone noise fragments (e.g., "n-1", "140%") that often come from figures/tables.
    drop_tiny_noise_paragraphs: bool = True
    tiny_noise_max_chars: int = 8

    # Figure handling: drop diagram labels / axis ticks near figure captions.
    # NOTE: This can accidentally remove math variables or short tokens in some papers.
    # Keep it opt-in (disabled by default).
    figure_handling: bool = False
    figure_caption_re: str = r"^(?:Figure|Fig\.?)\s*(?:\d+|[IVXLC]+)\s*(?:[:\.])"
    figure_caption_window_ratio: float = 0.45
    figure_body_drop_max_chars: int = 20

    # Algorithm blocks (pseudocode boxes like "Algorithm 1 ...")
    # We generally don't want to annotate these as prose paragraphs.
    drop_algorithms: bool = True
    algorithm_caption_re: str = r"^\s*Algorithm\s+\d+\b"
    algorithm_block_max_gap_line_height_mult: float = 2.2
    algorithm_block_max_height_ratio: float = 0.55
    algorithm_block_max_lines: int = 120

    # Table handling
    table_handling: bool = True
    table_caption_re: str = r"^(?:Table|Tbl\.?)\s*(?:\d+|[IVXLC]+)\s*(?:[:\.])"
    table_caption_window_ratio: float = 0.55  # search window relative to page height
    table_min_body_paragraphs: int = 8
    table_like_min_score: float = 0.22

    # Merge lines on the same baseline that PyMuPDF split horizontally.
    same_baseline_merge: bool = True
    same_baseline_y_tol_mult: float = 0.25  # tol = avg_h * mult
    same_baseline_x_gap_font_mult: float = 1.4  # gap <= font_size * mult

    # Text cleanup
    normalize_whitespace: bool = True
    dehyphenate_linebreaks: bool = True

    # Display math handling (equation blocks)
    replace_display_math_with_placeholder: bool = True
    display_math_placeholder: str = "[MATH]"
    # Equation numbers sometimes appear as a tiny right-margin line, occasionally preceded by punctuation.
    # Keep this strict enough to avoid matching journal issue formats like "20(1):30-42".
    display_math_eqno_re: str = r"^[\.\s]*\(\s*\d{1,3}(?:\.\d{1,2}|[a-z])?\s*\)\s*$"
    display_math_eqno_right_x0_ratio: float = 0.72
    display_math_eqno_max_width_ratio: float = 0.18
    display_math_merge_eqno_y_tol_mult: float = 0.35  # tol = avg_h * mult
    # Unnumbered display-math blocks (no "(n)" equation number) are common and can fragment into
    # tiny stray paragraphs (e.g., a standalone "β"). Replace them with a placeholder too.
    replace_unnumbered_display_math_with_placeholder: bool = True
    unnumbered_display_math_min_lines: int = 2
    unnumbered_display_math_gap_line_height_mult: float = 1.3
    # Merge standalone [MATH] paragraphs into the previous prose paragraph.
    # Only numbered equations are safe to merge; unnumbered blocks can be unrelated
    # (tables/figures/inline fragments) and will corrupt prose if merged.
    merge_unnumbered_math_placeholders_into_previous: bool = False
    # Context-aware math merge: classify by continuity and select merge direction.
    math_context_score_threshold: int = 6
    math_context_skip_ambiguous: bool = True
    math_context_max_gap_line_height_mult: float = 3.0

    # Inline-math fragments sometimes appear on the far right of a text row (e.g., "Qi+1(s,a) ="),
    # causing them to drift in column-major ordering. Merge such right-floating fragments into the
    # nearest left-column line on the same baseline.
    inline_math_right_x0_ratio: float = 0.68
    inline_math_max_width_ratio: float = 0.28
    inline_math_y_tol_mult: float = 0.3
    inline_math_max_chars: int = 48


@dataclass(frozen=True)
class _Line:
    page_index: int  # 0-based
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    font_size: float
    block_no: int

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0


@dataclass
class _Paragraph:
    paragraph_id: int
    lines: List[_Line]
    is_caption: bool

    @property
    def pages(self) -> List[int]:
        return sorted({l.page_index + 1 for l in self.lines})

    @property
    def text(self) -> str:
        return _join_line_texts(self.lines)

    def bboxes_by_page(self) -> List[Dict[str, float | int]]:
        by_page: Dict[int, List[_Line]] = {}
        for l in self.lines:
            by_page.setdefault(l.page_index + 1, []).append(l)
        out: List[Dict[str, float | int]] = []
        for page, ls in sorted(by_page.items(), key=lambda t: t[0]):
            x0 = min(l.x0 for l in ls)
            y0 = min(l.y0 for l in ls)
            x1 = max(l.x1 for l in ls)
            y1 = max(l.y1 for l in ls)
            out.append({"page": page, "x0": float(x0), "y0": float(y0), "x1": float(x1), "y1": float(y1)})
        return out

    def anchor_bbox(self) -> Dict[str, float | int]:
        """
        Return a small bbox used to place note icons.

        We prefer the topmost line on the earliest page of this paragraph, so that
        note placement is stable and does not drift to the bottom of long paragraphs.
        """
        if not self.lines:
            return {"page": 1, "x0": 0.0, "y0": 0.0, "x1": 0.0, "y1": 0.0}
        first_page = min(l.page_index for l in self.lines)
        candidates = [l for l in self.lines if l.page_index == first_page]
        # Avoid anchoring on synthetic placeholders (e.g., "[MATH](1)") when the paragraph
        # contains real prose lines too; placeholders can drift and cause visible misplacement.
        non_placeholder = [
            l
            for l in candidates
            if not (l.text or "").strip().startswith("[MATH]")
        ]
        pool = non_placeholder or candidates
        top = min(pool, key=lambda l: (l.y0, l.x0))
        return {
            "page": int(top.page_index + 1),
            "x0": float(top.x0),
            "y0": float(top.y0),
            "x1": float(top.x1),
            "y1": float(top.y1),
        }

def _require_pymupdf() -> None:
    if fitz is None:  # pragma: no cover
        raise RuntimeError(
            "PyMuPDF (fitz) がインストールされていません。`pip install pymupdf` を実行してください。"
        ) from _IMPORT_ERROR


def _merge_spans_into_line_text(spans: Sequence[dict], *, font_size_hint: float) -> str:
    """
    Merge spans in the same line into a single string.
    PyMuPDF often omits literal spaces; insert spaces by bbox gaps.
    """
    items: List[Tuple[float, float, str, float]] = []
    sizes: List[float] = []
    for sp in spans:
        if not isinstance(sp, dict):
            continue
        t = sp.get("text") or ""
        if not isinstance(t, str) or not t.strip():
            continue
        bbox = sp.get("bbox")
        if not (isinstance(bbox, (list, tuple)) and len(bbox) == 4):
            continue
        x0, _y0, x1, _y1 = map(float, bbox)
        fs = float(sp.get("size")) if isinstance(sp.get("size"), (int, float)) else 0.0
        if fs > 0:
            sizes.append(fs)
        items.append((x0, x1, t, fs))
    if not items:
        return ""
    items.sort(key=lambda it: (it[0], it[1]))

    base_fs = float(median(sizes)) if sizes else float(font_size_hint or 10.0)
    gap_thresh = max(0.5, 0.06 * base_fs)

    parts: List[str] = []
    prev_x1: Optional[float] = None
    for x0, x1, t, _fs in items:
        if prev_x1 is not None and (x0 - prev_x1) >= gap_thresh:
            if parts and not parts[-1].endswith(" "):
                parts.append(" ")
        parts.append(t)
        prev_x1 = x1
    text = "".join(parts)
    # Remove C0 control chars (XML/JSON safe)
    text = "".join(ch if (ord(ch) >= 0x20 or ord(ch) in (0x09, 0x0A, 0x0D)) else " " for ch in text)
    return re.sub(r"\s+", " ", text).strip()


def _iter_lines_from_page_dict(page_dict: dict, *, page_index: int, config: ExtractionConfig) -> List[_Line]:
    out: List[_Line] = []
    blocks = page_dict.get("blocks") or []
    for b_i, b in enumerate(blocks):
        if not isinstance(b, dict) or b.get("type") != 0:
            continue
        for ln in (b.get("lines") or []):
            if not isinstance(ln, dict):
                continue
            bbox = ln.get("bbox")
            if not (isinstance(bbox, (list, tuple)) and len(bbox) == 4):
                continue
            x0, y0, x1, y1 = map(float, bbox)
            spans = ln.get("spans") or []
            sizes = [float(sp.get("size")) for sp in spans if isinstance(sp, dict) and isinstance(sp.get("size"), (int, float))]
            fs = float(median(sizes)) if sizes else 0.0
            text = _merge_spans_into_line_text(spans, font_size_hint=fs)
            if not text:
                continue
            out.append(
                _Line(
                    page_index=page_index,
                    x0=float(x0),
                    y0=float(y0),
                    x1=float(x1),
                    y1=float(y1),
                    text=text,
                    font_size=fs,
                    block_no=b_i,
                )
            )
    return out


def _column_of(line: _Line, *, page_w: float, config: ExtractionConfig) -> int:
    mid = page_w * float(config.column_split_ratio)
    # Use x0 (not x-center) per spec: bbox.x0 relative to midpoint.
    # x-center breaks single-column pages and full-width lines close to the midpoint.
    return 0 if line.x0 < mid else 1


def _line_gap(current: _Line, next_: _Line) -> float:
    return float(next_.y0 - current.y1)


def _x_overlap_ratio(a: _Line, b: _Line) -> float:
    overlap = min(a.x1, b.x1) - max(a.x0, b.x0)
    if overlap <= 0:
        return 0.0
    return float(overlap) / float(min(a.width, b.width) or 1.0)


_CONTINUATION_START_RE = re.compile(r"^(?:[a-z]|[,\)\]\}]|and\b|or\b|where\b|which\b|that\b|with\b|for\b|to\b)")


def _looks_like_continuation_start(text: str) -> bool:
    s = (text or "").lstrip()
    if not s:
        return False
    return bool(_CONTINUATION_START_RE.match(s))


def _line_pair_continuity_score(
    left: _Line,
    right: _Line,
    *,
    page_w: float,
    avg_h: float,
    config: ExtractionConfig,
) -> int:
    score = 0

    if left.page_index == right.page_index:
        score += 1
    if _column_of(left, page_w=page_w, config=config) == _column_of(right, page_w=page_w, config=config):
        score += 2

    if abs(left.x0 - right.x0) <= max(6.0, page_w * 0.03):
        score += 1
    elif _x_overlap_ratio(left, right) >= 0.35:
        score += 1

    gap = _line_gap(left, right)
    max_gap = max(1.0, avg_h * float(config.math_context_max_gap_line_height_mult))
    if -0.4 * avg_h <= gap <= max_gap:
        score += 2
    elif gap <= (max_gap * 1.3):
        score += 1

    if _font_size_consistent(left, right, config=config):
        score += 1

    left_text = (left.text or "").rstrip()
    right_text = (right.text or "").lstrip()
    if left_text and not left_text.endswith((".", ":", ";")):
        score += 2
    if _looks_like_continuation_start(right_text):
        score += 2
    return score


def _replace_last_line_text(para: _Paragraph, text: str) -> _Paragraph:
    if not para.lines:
        return para
    last = para.lines[-1]
    new_last = _Line(
        page_index=last.page_index,
        x0=last.x0,
        y0=last.y0,
        x1=last.x1,
        y1=last.y1,
        text=text,
        font_size=last.font_size,
        block_no=last.block_no,
    )
    return _Paragraph(paragraph_id=-1, lines=para.lines[:-1] + [new_last], is_caption=para.is_caption)


def _replace_first_line_text(para: _Paragraph, text: str) -> _Paragraph:
    if not para.lines:
        return para
    first = para.lines[0]
    new_first = _Line(
        page_index=first.page_index,
        x0=first.x0,
        y0=first.y0,
        x1=first.x1,
        y1=first.y1,
        text=text,
        font_size=first.font_size,
        block_no=first.block_no,
    )
    return _Paragraph(paragraph_id=-1, lines=[new_first] + para.lines[1:], is_caption=para.is_caption)


def _font_size_consistent(a: _Line, b: _Line, *, config: ExtractionConfig) -> bool:
    if a.font_size <= 0 or b.font_size <= 0:
        return True
    rel = abs(a.font_size - b.font_size) / max(a.font_size, b.font_size)
    return rel <= float(config.font_size_rel_tol)


def _page_avg_line_height(lines: Sequence[_Line]) -> float:
    hs_all = [l.height for l in lines if l.height > 0]
    if not hs_all:
        return 10.0

    # Prefer body-like text heights to avoid being dominated by tiny tick-label / table-cell fonts.
    hs_body = [
        l.height
        for l in lines
        if l.height > 0 and len((l.text or "").strip()) >= 10 and re.search(r"[A-Za-z]", (l.text or ""))
    ]
    if len(hs_body) >= 8:
        return float(median(hs_body))

    # Fallback: median of all lines (robust to occasional tall bboxes).
    return float(median(hs_all))


def _quantile(values: Sequence[float], q: float) -> float:
    if not values:
        return 0.0
    if q <= 0:
        return float(min(values))
    if q >= 1:
        return float(max(values))
    xs = sorted(float(x) for x in values)
    if len(xs) == 1:
        return float(xs[0])
    pos = q * (len(xs) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    frac = pos - lo
    return float(xs[lo] * (1.0 - frac) + xs[hi] * frac)


@dataclass(frozen=True)
class _BodyBand:
    ok: bool
    y0: float
    y1: float
    med_fs: float
    med_h: float
    med_w: float


def _compute_body_band(
    lines: Sequence[_Line],
    *,
    page_w: float,
    page_h: float,
    config: ExtractionConfig,
) -> _BodyBand:
    """
    Estimate the "body text band" (vertical region where main text lives) using robust,
    within-page statistics. This is used to classify header/footer/page-number/footnote lines
    without relying on fixed page-height ratios.
    """
    if not lines or page_h <= 0:
        return _BodyBand(ok=False, y0=0.0, y1=0.0, med_fs=0.0, med_h=0.0, med_w=0.0)

    # Body-like candidates: longer, contains letters, not obvious captions, not pure numbers.
    # Exclude obvious footnote starts near the bottom so they don't inflate the body band.
    cap_re = re.compile(config.caption_re, flags=re.IGNORECASE)
    foot_re = re.compile(config.footnote_start_re)
    candidates: List[_Line] = []
    for l in lines:
        s = (l.text or "").strip()
        if len(s) < 10:
            continue
        if re.match(config.page_number_re, s):
            continue
        if cap_re.match(s):
            continue
        if l.y0 >= (page_h * 0.72) and foot_re.match(s):
            continue
        if not re.search(r"[A-Za-z]", s):
            continue
        candidates.append(l)

    if len(candidates) < 8:
        return _BodyBand(ok=False, y0=0.0, y1=0.0, med_fs=0.0, med_h=0.0, med_w=0.0)

    fs = [l.font_size for l in candidates if l.font_size > 0]
    hs = [l.height for l in candidates if l.height > 0]
    ws = [l.width for l in candidates if l.width > 0]
    if not fs or not hs:
        return _BodyBand(ok=False, y0=0.0, y1=0.0, med_fs=0.0, med_h=0.0, med_w=0.0)

    med_fs = float(median(fs))
    # Second-pass cleanup: remove likely bottom footnote lines by size+position.
    candidates2 = [
        l
        for l in candidates
        if not (
            l.y0 >= (page_h * 0.80)
            and l.font_size > 0
            and l.font_size <= (med_fs * float(config.footnote_font_size_mult))
        )
    ]
    if len(candidates2) >= 8:
        candidates = candidates2
        fs = [l.font_size for l in candidates if l.font_size > 0]
        hs = [l.height for l in candidates if l.height > 0]
        ws = [l.width for l in candidates if l.width > 0]
        med_fs = float(median(fs)) if fs else med_fs
    # Keep only lines reasonably close to the median font size (avoid headings/captions).
    near_fs = [l for l in candidates if l.font_size > 0 and abs(l.font_size - med_fs) / max(med_fs, 1e-6) <= 0.25]
    if len(near_fs) >= 6:
        hs2 = [l.height for l in near_fs if l.height > 0]
        ws2 = [l.width for l in near_fs if l.width > 0]
        med_h = float(median(hs2)) if hs2 else float(median(hs))
        med_w = float(median(ws2)) if ws2 else float(median(ws)) if ws else 0.0
        ys0 = [l.y0 for l in near_fs]
        ys1 = [l.y1 for l in near_fs]
    else:
        med_h = float(median(hs))
        med_w = float(median(ws)) if ws else 0.0
        ys0 = [l.y0 for l in candidates]
        ys1 = [l.y1 for l in candidates]

    q_low = float(config.body_band_q_low)
    q_high = float(config.body_band_q_high)
    band_y0 = _quantile(ys0, q_low)
    band_y1 = _quantile(ys1, q_high)

    pad = float(config.body_band_pad_lines) * max(med_h, 1.0)
    band_y0 = max(0.0, float(band_y0 - pad))
    band_y1 = min(float(page_h), float(band_y1 + pad))
    if band_y1 <= band_y0:
        return _BodyBand(ok=False, y0=0.0, y1=0.0, med_fs=med_fs, med_h=med_h, med_w=med_w)

    return _BodyBand(ok=True, y0=band_y0, y1=band_y1, med_fs=med_fs, med_h=med_h, med_w=med_w)


def _is_outside_body_band(line: _Line, *, band: _BodyBand, config: ExtractionConfig, page_h: float) -> bool:
    if not band.ok:
        return False
    pad = float(config.outside_body_band_pad_lines) * max(band.med_h, 1.0)
    return float(line.y1) < (band.y0 - pad) or float(line.y0) > (band.y1 + pad)


def _page_median_line_width(lines: Sequence[_Line]) -> float:
    ws = [l.width for l in lines if l.width > 0 and len(l.text) >= 10]
    if not ws:
        return 0.0
    return float(median(ws))


def _is_caption_line(
    line: _Line,
    *,
    page_w: float,
    median_width: float,
    config: ExtractionConfig,
) -> bool:
    s = (line.text or "").strip()
    if not s:
        return False
    if re.search(config.caption_re, s, flags=re.IGNORECASE):
        return True
    # Heuristic: centered + shorter than typical width
    if median_width > 0 and line.width <= (median_width * float(config.caption_width_ratio)):
        if config.caption_centered_requires_number:
            if not re.search(config.caption_centered_number_re, s):
                return False
            if not re.search(config.caption_centered_keyword_re, s, flags=re.IGNORECASE):
                return False
        center = (line.x0 + line.x1) / 2.0
        if abs(center - (page_w / 2.0)) <= (page_w * float(config.caption_center_tol_ratio)):
            return True
    return False


def _join_line_texts(lines: Sequence[_Line]) -> str:
    parts: List[str] = []
    for line in lines:
        s = (line.text or "").strip()
        if not s:
            continue
        if not parts:
            parts.append(s)
            continue
        prev = parts[-1]
        if prev.endswith("-") and len(prev) >= 2 and prev[-2].isalpha():
            parts[-1] = prev[:-1] + s
        else:
            parts.append(s)
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def _is_sentence_like(text: str) -> bool:
    s = (text or "").strip()
    if not s:
        return False
    if not re.search(r"[a-z]", s):
        return False
    words = s.split()
    if len(words) < 6:
        return False
    return bool(re.search(r"[.!?][\"'\)\]]*\s*$", s))


def _is_prose_like(text: str) -> bool:
    s = re.sub(r"\s+", " ", (text or "").strip())
    if not s:
        return False
    words = s.split()
    if len(words) < 6:
        return False
    alpha = sum(1 for ch in s if ch.isalpha())
    if alpha < 15:
        return False
    mathish = sum(1 for ch in s if ch in "=∈→←{}\\_^")
    if mathish >= 4 and mathish > (alpha * 0.15):
        return False
    return True


def _is_mathish_text(text: str) -> bool:
    s = re.sub(r"\s+", " ", (text or "").strip())
    if not s:
        return False
    if _is_prose_like(s):
        return False
    if re.search(r"[=∈→←{}\\_^∇γθρ≈∼∞·]", s):
        return True
    if re.search(r"\b(?:max|min|argmax|argmin|Es?)\b", s):
        return True
    if re.search(r"\b(?:Q|Li)\b", s):
        return True
    alpha = sum(1 for ch in s if ch.isalpha())
    non_alnum = sum(1 for ch in s if (not ch.isalnum() and not ch.isspace()))
    if non_alnum >= 3 and alpha <= 10:
        return True
    return False


def _is_heading_only_paragraph(para: _Paragraph, *, config: ExtractionConfig) -> bool:
    if para.is_caption:
        return False
    s = re.sub(r"\s+", " ", (para.text or "").strip())
    if not s:
        return False
    if len(s) > max(int(config.heading_numbered_max_chars), int(config.heading_max_chars) + 40):
        return False
    if len(para.lines) > 2:
        return False
    if re.search(r"[.!?;:]\s*$", s):
        return False

    if re.match(config.heading_numbered_re, s):
        words = s.split()
        if 1 <= len(words) <= int(config.heading_numbered_max_words):
            return True

    # All-caps section titles like "ATARI EXPERIMENTS", optional leading index ("4 ...", "B.2 ...").
    s2 = re.sub(r"^(?:[A-Z]?\d+(?:\.\d+)*)\s+", "", s)
    tokens = s2.split()
    if tokens and len(tokens) <= 10:
        caps_tokens = [
            t for t in tokens if re.search(r"[A-Za-z]", t)
        ]
        if caps_tokens and all(t == t.upper() for t in caps_tokens):
            return True

    # Canonical one-line section names.
    if re.match(r"^(?:Abstract|Introduction|Conclusion|Conclusions|References|Appendix)\b", s, flags=re.IGNORECASE):
        return True
    return False


def _is_tiny_noise_paragraph(para: _Paragraph, *, config: ExtractionConfig) -> bool:
    if para.is_caption:
        return False
    s = re.sub(r"\s+", " ", (para.text or "").strip())
    if not s:
        return False
    if s.startswith(str(config.display_math_placeholder)):
        return False
    if len(s) > int(config.tiny_noise_max_chars):
        return False
    if _is_sentence_like(s) or _is_prose_like(s):
        return False
    tokens = s.split()
    if len(tokens) > 2:
        return False
    # Keep explicit section numbers from being dropped here (handled by heading filter).
    if re.match(config.heading_numbered_re, s):
        return False
    return True


def _looks_like_reference_entry(text: str) -> bool:
    s = re.sub(r"\s+", " ", (text or "").strip())
    if len(s) < 12:
        return False
    score = 0
    if re.match(r"^\[\d{1,4}\]", s):
        score += 2
    if re.match(r"^\d{1,4}[\.\)]\s+", s):
        score += 2
    if re.search(r"\b(19|20)\d{2}\b", s):
        score += 1
    if re.search(r"\b(?:et al\.|arXiv|doi|vol\.|pp\.|Proc\.|Proceedings)\b", s, flags=re.IGNORECASE):
        score += 1
    if re.search(r"^[A-Z][A-Za-z'`-]+,\s+[A-Z]", s):
        score += 1
    return score >= 2


def _trim_after_references_heading(paras: List[_Paragraph], *, config: ExtractionConfig) -> List[_Paragraph]:
    if not config.skip_after_references or not paras:
        return paras

    n = len(paras)
    min_pos = max(0.0, min(1.0, float(config.references_min_position_ratio)))
    confirm_window = max(0, int(config.references_confirmation_window))
    confirm_needed = max(0, int(config.references_confirmation_needed))
    max_page = max((max(p.pages) for p in paras if p.pages), default=1)

    for i, p in enumerate(paras):
        if p.is_caption:
            continue
        s = re.sub(r"\s+", " ", (p.text or "").strip())
        if not s:
            continue
        if not re.match(config.references_heading_re, s, flags=re.IGNORECASE):
            continue
        first_page = min(p.pages) if p.pages else 1
        pos_ratio = (float(first_page) / float(max_page)) if max_page > 0 else (i / max(1, n - 1))
        if pos_ratio < min_pos:
            continue

        # Some PDFs merge the heading and many reference entries into one paragraph.
        # In that case, cut immediately.
        if (
            len(s) >= 120
            or len(re.findall(r"\b(19|20)\d{2}\b", s)) >= 3
            or s.upper().startswith("REFERENCES ")
        ):
            return paras[:i]

        lookahead = paras[i + 1 : i + 1 + confirm_window]
        evidence = sum(1 for q in lookahead if _looks_like_reference_entry(q.text))
        if evidence >= confirm_needed:
            return paras[:i]

        # If heading appears near the end, trust it even without enough lookahead.
        if pos_ratio >= 0.85:
            return paras[:i]

    return paras


def _table_like_score(text: str) -> float:
    """
    Score how much a paragraph looks like a table row / table body text.
    (0.0 -> not table-like, 1.0 -> very table-like)
    """
    s = re.sub(r"\s+", " ", (text or "").strip())
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
        if re.fullmatch(r"[\+\-−]?\d+(?:\.\d+)?", t):
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
    # Penalize long prose.
    sentencey = 1.0 if _is_sentence_like(s) else 0.0
    score = (
        0.55 * numeric_ratio
        + 0.22 * short_ratio
        + 0.18 * cap_ratio
        + 0.15 * (1.0 if len(tokens) >= 12 else 0.0)
        - 0.7 * sentencey
    )
    return max(0.0, min(1.0, score))


def _para_bbox_on_page(para: _Paragraph, page_index: int) -> Optional[Tuple[float, float, float, float]]:
    ls = [l for l in para.lines if l.page_index == page_index]
    if not ls:
        return None
    x0 = min(l.x0 for l in ls)
    y0 = min(l.y0 for l in ls)
    x1 = max(l.x1 for l in ls)
    y1 = max(l.y1 for l in ls)
    return float(x0), float(y0), float(x1), float(y1)


def _merge_caption_continuations_in_page(
    paras: List[_Paragraph],
    *,
    page_index: int,
    avg_h: float,
    config: ExtractionConfig,
) -> List[_Paragraph]:
    """
    Merge caption label line and its following prose line.
    Example: "Table 1:" + "The upper table compares ..." -> one caption paragraph.
    """
    if not paras:
        return paras

    out: List[_Paragraph] = []
    i = 0
    while i < len(paras):
        cur = paras[i]
        if (
            cur.is_caption
            and i + 1 < len(paras)
            and not paras[i + 1].is_caption
            and any(l.page_index == page_index for l in cur.lines)
            and any(l.page_index == page_index for l in paras[i + 1].lines)
        ):
            nxt = paras[i + 1]
            cur_text = (cur.text or "").strip()
            # Only do this for typical caption labels (endswith ":" or very short).
            if cur_text.endswith((":",".")) or len(cur_text) <= 24:
                last = max([l for l in cur.lines if l.page_index == page_index], key=lambda l: (l.y1, l.x1))
                first = min([l for l in nxt.lines if l.page_index == page_index], key=lambda l: (l.y0, l.x0))
                gap = _line_gap(last, first)
                gap_mult = 1.2
                # Captions often have extra vertical whitespace after the label line.
                if cur_text.endswith(":") and len(cur_text) <= 20:
                    gap_mult = 3.0
                if gap <= (avg_h * gap_mult) and _x_overlap_ratio(last, first) >= float(config.overlap_min_ratio):
                    merged = _Paragraph(paragraph_id=-1, lines=cur.lines + nxt.lines, is_caption=True)
                    out.append(merged)
                    i += 2
                    continue
            # Also merge when a long caption paragraph got split, and the next paragraph clearly
            # looks like a continuation (starts with lowercase, aligned, and close vertically).
            # Keep this strict to avoid swallowing normal body prose below a caption.
            if re.search(config.caption_re, cur_text, flags=re.IGNORECASE):
                last = max([l for l in cur.lines if l.page_index == page_index], key=lambda l: (l.y1, l.x1))
                first = min([l for l in nxt.lines if l.page_index == page_index], key=lambda l: (l.y0, l.x0))
                gap = _line_gap(last, first)
                nxt_text = (nxt.text or "").lstrip()
                nxt_page_lines = [l for l in nxt.lines if l.page_index == page_index]
                if (
                    nxt_text[:1].islower()
                    and gap <= (avg_h * float(config.caption_multiline_gap_line_height_mult) * 1.2)
                    and (_x_overlap_ratio(last, first) >= float(config.overlap_min_ratio) or abs(last.x0 - first.x0) <= 8.0)
                    and len(nxt_page_lines) <= 2
                    and not _is_sentence_like(nxt_text)
                    and not ((last.text or "").rstrip().endswith(".") and len(nxt_text) >= 40)
                ):
                    merged = _Paragraph(paragraph_id=-1, lines=cur.lines + nxt.lines, is_caption=True)
                    out.append(merged)
                    i += 2
                    continue

        out.append(cur)
        i += 1
    return out


def _split_caption_body_tails_in_page(
    paras: List[_Paragraph],
    *,
    page_index: int,
    avg_h: float,
) -> List[_Paragraph]:
    """
    Split cases where body prose was mistakenly absorbed into the tail of a caption.

    Typical pattern:
      ... caption sentence.
      in/of/over ...   <- actually body continuation text
    """
    if not paras:
        return paras
    out: List[_Paragraph] = []
    for p in paras:
        if not p.is_caption:
            out.append(p)
            continue
        page_lines = [l for l in p.lines if l.page_index == page_index]
        if len(page_lines) < 2:
            out.append(p)
            continue

        cut: Optional[int] = None
        for i in range(1, len(page_lines)):
            prev = page_lines[i - 1]
            cur = page_lines[i]
            prev_text = (prev.text or "").rstrip()
            cur_text = (cur.text or "").lstrip()
            if not prev_text.endswith("."):
                continue
            if not cur_text[:1].islower():
                continue
            if len(cur_text) < 30:
                continue
            if not (_is_sentence_like(cur_text) or _is_prose_like(cur_text)):
                continue
            if re.match(r"^(?:left|right|top|bottom)\s*:", cur_text, flags=re.IGNORECASE):
                continue
            if _line_gap(prev, cur) > (avg_h * 2.6):
                continue
            cut = i
            break

        if cut is None:
            out.append(p)
            continue

        head = page_lines[:cut]
        tail = page_lines[cut:]
        if not head or not tail:
            out.append(p)
            continue
        out.append(_Paragraph(paragraph_id=-1, lines=head, is_caption=True))
        out.append(_Paragraph(paragraph_id=-1, lines=tail, is_caption=False))
    return out


def _drop_table_body_near_captions(
    paras: List[_Paragraph],
    *,
    page_index: int,
    page_w: float,
    page_h: float,
    config: ExtractionConfig,
) -> List[_Paragraph]:
    """
    Drop table body fragments while keeping the caption.

    We look for a "Table N:" caption paragraph and then drop a dense cluster of
    table-like paragraphs in a nearby vertical window.
    """
    if not config.table_handling or not paras or page_h <= 0 or page_w <= 0:
        return paras

    mid = page_w * float(config.column_split_ratio)

    def col_of_para(p: _Paragraph) -> Optional[int]:
        bb = _para_bbox_on_page(p, page_index)
        if not bb:
            return None
        x0, _y0, x1, _y1 = bb
        # Full-width captions/tables can span both columns; don't constrain by column then.
        tol = page_w * 0.02
        if (x0 < (mid - tol)) and (x1 > (mid + tol)):
            return None
        return 0 if x0 < mid else 1

    table_caption_idxs: List[int] = []
    for i, p in enumerate(paras):
        if not p.is_caption:
            continue
        if not _para_bbox_on_page(p, page_index):
            continue
        if re.search(config.table_caption_re, (p.text or "").strip(), flags=re.IGNORECASE):
            table_caption_idxs.append(i)

    if not table_caption_idxs:
        return paras

    drop: set[int] = set()
    win = page_h * float(config.table_caption_window_ratio)

    for cap_i in table_caption_idxs:
        cap = paras[cap_i]
        cap_bb = _para_bbox_on_page(cap, page_index)
        if not cap_bb:
            continue
        _cx0, cap_y0, _cx1, cap_y1 = cap_bb
        cap_col = col_of_para(cap)

        # Consider both: body above caption (common) and body below caption.
        bands = [
            (max(0.0, cap_y0 - win), cap_y0, "above"),
            (cap_y1, min(page_h, cap_y1 + win), "below"),
        ]
        for band_y0, band_y1, where in bands:
            candidates_all: List[int] = []
            candidates_strong: List[int] = []
            for j, p in enumerate(paras):
                if j == cap_i:
                    continue
                bb = _para_bbox_on_page(p, page_index)
                if not bb:
                    continue
                _x0, y0, _x1, y1 = bb
                if y1 <= band_y0 or y0 >= band_y1:
                    continue
                if cap_col is not None and col_of_para(p) != cap_col:
                    continue
                # Do not drop captions or normal prose.
                if p.is_caption:
                    continue
                t = (p.text or "").strip()
                if not t:
                    continue
                if _is_sentence_like(t):
                    # Keep prose paragraphs; we will not drop them.
                    continue

                candidates_all.append(j)
                score = _table_like_score(t)
                if where == "above":
                    if score >= float(config.table_like_min_score):
                        candidates_strong.append(j)
                else:
                    # Below-caption band is conservative to avoid losing short prose fragments.
                    # Require stronger table-like evidence.
                    if score >= max(float(config.table_like_min_score) + 0.10, 0.34):
                        candidates_strong.append(j)

            if where == "above":
                # Detect whether this band is actually a table cluster (strong evidence).
                if len(candidates_strong) < int(config.table_min_body_paragraphs):
                    continue
                # Once we are confident, drop all non-sentence fragments in the band (including header rows).
                for j in candidates_all:
                    drop.add(j)
            else:
                # For below-caption content, only drop strongly table-like fragments and only
                # when a local cluster exists.
                below_min_cluster = max(3, int(config.table_min_body_paragraphs // 2))
                if len(candidates_strong) < below_min_cluster:
                    continue
                for j in candidates_strong:
                    drop.add(j)

    if not drop:
        return paras
    return [p for i, p in enumerate(paras) if i not in drop]


def _is_eq_number_line(line: _Line, *, page_w: float, config: ExtractionConfig) -> bool:
    s = (line.text or "").strip()
    if not s:
        return False
    if not re.match(config.display_math_eqno_re, s):
        return False
    if page_w <= 0:
        return False
    if line.x0 < (page_w * float(config.display_math_eqno_right_x0_ratio)):
        return False
    if line.width > (page_w * float(config.display_math_eqno_max_width_ratio)):
        return False
    return True


def _merge_equation_number_paragraphs(
    paras: List[_Paragraph],
    *,
    page_index: int,
    page_w: float,
    avg_h: float,
    config: ExtractionConfig,
) -> List[_Paragraph]:
    """
    PyMuPDF may emit equation numbers like "(1)" as separate tiny paragraphs on the right margin.
    Merge them into the nearest preceding paragraph on the same baseline so that later
    math-placeholder logic can treat the whole display equation as one unit.
    """
    if not paras or page_w <= 0 or avg_h <= 0:
        return paras

    y_tol = avg_h * float(config.display_math_merge_eqno_y_tol_mult)
    out: List[_Paragraph] = []

    for p in paras:
        bb = _para_bbox_on_page(p, page_index)
        if not bb:
            out.append(p)
            continue
        if p.is_caption:
            out.append(p)
            continue
        if len(p.lines) != 1:
            out.append(p)
            continue
        ln = p.lines[0]
        if ln.page_index != page_index:
            out.append(p)
            continue
        if not _is_eq_number_line(ln, page_w=page_w, config=config):
            out.append(p)
            continue

        # Find best previous candidate in out: same page, last line baseline close, and ends to the left.
        best_i = None
        best_dx = 1e9
        for i in range(len(out) - 1, -1, -1):
            prev = out[i]
            if prev.is_caption:
                continue
            prev_lines = [l for l in prev.lines if l.page_index == page_index]
            prev_last = max(prev_lines, key=lambda l: (l.y1, l.x1)) if prev_lines else None
            if prev_last is None:
                continue
            baseline_close = abs(prev_last.y0 - ln.y0) <= y_tol and abs(prev_last.y1 - ln.y1) <= y_tol
            if not baseline_close:
                # Because we scan backwards in reading order, once we are far above the baseline we can stop.
                if prev_last.y1 < (ln.y0 - (avg_h * 2.5)):
                    break
                continue
            if prev_last.x1 > ln.x0:
                continue
            dx = ln.x0 - prev_last.x1
            if dx < best_dx:
                best_dx = dx
                best_i = i

        if best_i is None:
            out.append(p)
            continue

        merged = _Paragraph(paragraph_id=-1, lines=out[best_i].lines + [ln], is_caption=False)
        out[best_i] = merged
        # Drop this eq-number paragraph.
        continue

    return out


def _replace_display_math_paragraphs(
    paras: List[_Paragraph],
    *,
    page_index: int,
    page_w: float,
    config: ExtractionConfig,
) -> List[_Paragraph]:
    """
    Replace display equations (numbered) with a placeholder token.
    We only target equations that have an explicit equation number like "(1)".
    """
    if not config.replace_display_math_with_placeholder:
        return paras

    out: List[_Paragraph] = []
    for p in paras:
        if p.is_caption:
            out.append(p)
            continue
        if not any(l.page_index == page_index for l in p.lines):
            out.append(p)
            continue

        eqno_text = None
        for l in p.lines:
            if l.page_index != page_index:
                continue
            if _is_eq_number_line(l, page_w=page_w, config=config):
                eqno_text = (l.text or "").strip()
                break
        has_eqno = bool(eqno_text)
        if not has_eqno:
            out.append(p)
            continue

        bb = _para_bbox_on_page(p, page_index)
        if not bb:
            out.append(p)
            continue
        x0, y0, x1, y1 = bb
        fs = float(median([l.font_size for l in p.lines if l.font_size > 0]) or [0.0])
        label = str(config.display_math_placeholder)
        if eqno_text:
            m = re.search(r"\(\s*\d{1,3}(?:\.\d{1,2}|[a-z])?\s*\)", eqno_text)
            eqno = re.sub(r"\s+", "", m.group(0) if m else eqno_text)
            label = f"{label}{eqno}" if eqno.startswith("(") else f"{label} {eqno}"
        placeholder_line = _Line(
            page_index=page_index,
            x0=x0,
            y0=y0,
            x1=x1,
            y1=y1,
            text=label,
            font_size=fs,
            block_no=p.lines[0].block_no if p.lines else 0,
        )
        out.append(_Paragraph(paragraph_id=-1, lines=[placeholder_line], is_caption=False))

    return out


def _replace_display_math_lines(
    lines: List[_Line],
    *,
    page_index: int,
    page_w: float,
    avg_h: float,
    config: ExtractionConfig,
) -> List[_Line]:
    """
    Replace a numbered display-math *block* with a single placeholder line.

    Doing this at the line stage avoids column-major ordering problems where the
    equation number on the right margin appears much later than the equation body.
    """
    if not config.replace_display_math_with_placeholder or not lines or page_w <= 0 or avg_h <= 0:
        return lines

    eqno_idx = [i for i, l in enumerate(lines) if _is_eq_number_line(l, page_w=page_w, config=config)]
    if not eqno_idx:
        return lines

    # A tight band captures same-baseline fragments; a looser band can capture multi-line math,
    # but only for clearly math-like lines (to avoid swallowing prose).
    tight = avg_h * 1.5
    loose = avg_h * 2.4

    remove: set[int] = set()
    placeholders: List[_Line] = []

    for i in sorted(eqno_idx, key=lambda k: (lines[k].y0, lines[k].x0)):
        if i in remove:
            continue
        eq = lines[i]
        cy = (eq.y0 + eq.y1) / 2.0

        core: List[Tuple[int, _Line]] = []
        for j, l in enumerate(lines):
            if j in remove:
                continue
            c2 = (l.y0 + l.y1) / 2.0
            dy = abs(c2 - cy)
            if dy <= tight:
                core.append((j, l))
                continue
            if dy <= loose and _is_mathish_text(l.text):
                core.append((j, l))

        # Require more than just the eq number.
        if len(core) < 2:
            continue

        # Include nearby tiny crumbs like "k" that belong to the equation but are not
        # obviously math-ish by themselves.
        cluster = list(core)
        for j, l in enumerate(lines):
            if j in remove:
                continue
            if any(j == jj for jj, _ in cluster):
                continue
            c2 = (l.y0 + l.y1) / 2.0
            dy = abs(c2 - cy)
            if dy > loose:
                continue
            s = (l.text or "").strip()
            if not s:
                continue
            if _is_prose_like(s) or _is_sentence_like(s):
                continue
            if len(s) <= 2:
                cluster.append((j, l))

        xs0 = min(l.x0 for _j, l in cluster)
        ys0 = min(l.y0 for _j, l in cluster)
        xs1 = max(l.x1 for _j, l in cluster)
        ys1 = max(l.y1 for _j, l in cluster)
        fs = float(median([l.font_size for _j, l in cluster if l.font_size > 0]) or [0.0])

        eqno_raw = (eq.text or "").strip()
        m = re.search(r"\(\s*\d{1,3}(?:\.\d{1,2}|[a-z])?\s*\)", eqno_raw)
        eqno = re.sub(r"\s+", "", m.group(0) if m else eqno_raw)
        label = str(config.display_math_placeholder)
        if eqno:
            label = f"{label}{eqno}" if eqno.startswith("(") else f"{label} {eqno}"

        placeholders.append(
            _Line(
                page_index=page_index,
                x0=float(xs0),
                y0=float(ys0),
                x1=float(xs1),
                y1=float(ys1),
                text=label,
                font_size=fs,
                block_no=eq.block_no,
            )
        )
        remove.update(j for j, _l in cluster)

    if not remove:
        return lines

    kept = [l for idx, l in enumerate(lines) if idx not in remove]
    kept.extend(placeholders)
    return kept


def _replace_unnumbered_display_math_blocks(
    lines: List[_Line],
    *,
    page_index: int,
    page_w: float,
    page_h: float,
    avg_h: float,
    config: ExtractionConfig,
) -> List[_Line]:
    if (
        not config.replace_unnumbered_display_math_with_placeholder
        or not config.replace_display_math_with_placeholder
        or not lines
        or page_w <= 0
        or page_h <= 0
        or avg_h <= 0
    ):
        return lines

    gap_max = avg_h * float(config.unnumbered_display_math_gap_line_height_mult)
    min_lines = int(config.unnumbered_display_math_min_lines)
    score_threshold = int(config.math_context_score_threshold)

    def is_candidate_math_line(l: _Line) -> bool:
        s = (l.text or "").strip()
        if not s:
            return False
        if s.startswith(str(config.display_math_placeholder)):
            return False
        if _is_caption_line(l, page_w=page_w, median_width=0.0, config=config):
            return False
        if _is_sentence_like(s) or _is_prose_like(s):
            return False
        if _is_mathish_text(s):
            return True
        # Control chars sometimes appear in math spans.
        if any(ord(ch) < 0x20 and ch not in ("\t", "\n", "\r") for ch in s):
            return True
        # Very short greek / symbol tokens can be part of math blocks.
        if len(s) <= 2 and re.search(r"[αβγθρησμλ∇·]", s):
            return True
        if "·" in s or "=" in s:
            return True
        return False

    out_lines = list(lines)
    remove_idx: set[int] = set()
    updated: Dict[int, _Line] = {}
    placeholders: List[_Line] = []

    def current_line(idx: int, fallback: _Line) -> _Line:
        return updated.get(idx, fallback)

    def with_text(base: _Line, text: str) -> _Line:
        return _Line(
            page_index=base.page_index,
            x0=base.x0,
            y0=base.y0,
            x1=base.x1,
            y1=base.y1,
            text=text,
            font_size=base.font_size,
            block_no=base.block_no,
        )

    for col in (0, 1):
        col_lines: List[Tuple[int, _Line]] = [
            (idx, l)
            for idx, l in enumerate(out_lines)
            if l.page_index == page_index and _column_of(l, page_w=page_w, config=config) == col
        ]
        col_lines.sort(key=lambda t: (t[1].y0, t[1].x0))
        i = 0
        while i < len(col_lines):
            idx0, raw0 = col_lines[i]
            l0 = current_line(idx0, raw0)
            if idx0 in remove_idx or not is_candidate_math_line(l0):
                i += 1
                continue
            block: List[Tuple[int, _Line]] = [(idx0, l0)]
            block_index_set: set[int] = {idx0}
            has_mathish = True
            prev = l0
            i2 = i + 1
            while i2 < len(col_lines):
                idx_l, raw_l = col_lines[i2]
                if idx_l in remove_idx:
                    i2 += 1
                    continue
                l = current_line(idx_l, raw_l)
                gap = _line_gap(prev, l)
                if gap > gap_max:
                    break
                s = (l.text or "").strip()
                if not s:
                    i2 += 1
                    continue
                if _is_caption_line(l, page_w=page_w, median_width=0.0, config=config):
                    break
                if _is_prose_like(s) or _is_sentence_like(s):
                    break

                # Inside a math block, include short non-prose lines even if they are not
                # obviously mathish (e.g., "P(i)", "1 N ·").
                if is_candidate_math_line(l):
                    has_mathish = True
                    block.append((idx_l, l))
                    block_index_set.add(idx_l)
                    prev = l
                    i2 += 1
                    continue
                if len(s) <= 40:
                    block.append((idx_l, l))
                    block_index_set.add(idx_l)
                    prev = l
                    i2 += 1
                    continue
                break

            if len(block) >= min_lines and has_mathish:
                first_line = block[0][1]
                last_line = block[-1][1]
                prev_idx: Optional[int] = None
                prev_line: Optional[_Line] = None
                next_idx: Optional[int] = None
                next_line: Optional[_Line] = None

                k = i - 1
                while k >= 0:
                    idx_p, raw_p = col_lines[k]
                    if idx_p in remove_idx or idx_p in block_index_set:
                        k -= 1
                        continue
                    cand = current_line(idx_p, raw_p)
                    if (cand.text or "").strip():
                        prev_idx = idx_p
                        prev_line = cand
                        break
                    k -= 1

                k = i2
                while k < len(col_lines):
                    idx_n, raw_n = col_lines[k]
                    if idx_n in remove_idx or idx_n in block_index_set:
                        k += 1
                        continue
                    cand = current_line(idx_n, raw_n)
                    if (cand.text or "").strip():
                        next_idx = idx_n
                        next_line = cand
                        break
                    k += 1

                prev_score = -10**6
                next_score = -10**6
                if prev_line is not None and (_is_prose_like(prev_line.text) or _is_sentence_like(prev_line.text)):
                    prev_score = _line_pair_continuity_score(
                        prev_line,
                        first_line,
                        page_w=page_w,
                        avg_h=avg_h,
                        config=config,
                    )
                if next_line is not None and (_is_prose_like(next_line.text) or _is_sentence_like(next_line.text)):
                    next_score = _line_pair_continuity_score(
                        last_line,
                        next_line,
                        page_w=page_w,
                        avg_h=avg_h,
                        config=config,
                    )

                direction = "skip"
                if prev_score >= score_threshold and next_score >= score_threshold:
                    prev_text = (prev_line.text or "").rstrip() if prev_line is not None else ""
                    next_text = (next_line.text or "").lstrip() if next_line is not None else ""
                    if prev_text and not prev_text.endswith((".", ":", ";")):
                        direction = "merge_prev"
                    elif _looks_like_continuation_start(next_text):
                        direction = "merge_next"
                    elif not config.math_context_skip_ambiguous:
                        direction = "merge_prev"
                elif prev_score >= score_threshold:
                    direction = "merge_prev"
                elif next_score >= score_threshold:
                    direction = "merge_next"

                placeholder = str(config.display_math_placeholder)
                if direction == "merge_prev" and prev_idx is not None and prev_line is not None:
                    merged = f"{(prev_line.text or '').rstrip()} {placeholder}".strip()
                    updated[prev_idx] = with_text(prev_line, merged)
                elif direction == "merge_next" and next_idx is not None and next_line is not None:
                    merged = f"{placeholder} {(next_line.text or '').lstrip()}".strip()
                    updated[next_idx] = with_text(next_line, merged)
                elif direction == "skip":
                    xs0 = min(l.x0 for _idx, l in block)
                    ys0 = min(l.y0 for _idx, l in block)
                    xs1 = max(l.x1 for _idx, l in block)
                    ys1 = max(l.y1 for _idx, l in block)
                    fs_vals = [l.font_size for _idx, l in block if l.font_size > 0]
                    placeholders.append(
                        _Line(
                            page_index=page_index,
                            x0=float(xs0),
                            y0=float(ys0),
                            x1=float(xs1),
                            y1=float(ys1),
                            text=placeholder,
                            font_size=float(median(fs_vals) if fs_vals else 0.0),
                            block_no=block[0][1].block_no,
                        )
                    )

                remove_idx.update(idx for idx, _ in block)
                i = i2
            else:
                i += 1

    if not remove_idx and not updated and not placeholders:
        return lines

    out: List[_Line] = []
    for idx, l in enumerate(out_lines):
        if idx in remove_idx:
            continue
        out.append(updated.get(idx, l))
    out.extend(placeholders)
    return out


def _merge_right_floating_math_into_left_lines(
    lines: List[_Line],
    *,
    page_w: float,
    avg_h: float,
    config: ExtractionConfig,
) -> List[_Line]:
    if not lines or page_w <= 0 or avg_h <= 0:
        return lines

    mid = page_w * float(config.column_split_ratio)
    y_tol = avg_h * float(config.inline_math_y_tol_mult)

    def is_right_floating_math(l: _Line) -> bool:
        s = (l.text or "").strip()
        if not s:
            return False
        if len(s) > int(config.inline_math_max_chars):
            return False
        if l.x0 < (page_w * float(config.inline_math_right_x0_ratio)):
            return False
        if l.width > (page_w * float(config.inline_math_max_width_ratio)):
            return False
        if _column_of(l, page_w=page_w, config=config) != 1:
            return False
        if l.x0 < (mid + page_w * 0.02):
            return False
        if _is_eq_number_line(l, page_w=page_w, config=config):
            return False
        if not _is_mathish_text(s):
            return False
        return True

    idxs = [i for i, l in enumerate(lines) if is_right_floating_math(l)]
    if not idxs:
        return lines

    remove: set[int] = set()
    updated: dict[int, _Line] = {}

    for i in idxs:
        if i in remove:
            continue
        r = lines[i]
        best_j = None
        best_dx = 1e9
        for j, l in enumerate(lines):
            if j == i or j in remove:
                continue
            if _column_of(l, page_w=page_w, config=config) != 0:
                continue
            # baseline proximity
            if abs(l.y0 - r.y0) > y_tol or abs(l.y1 - r.y1) > y_tol:
                continue
            if l.x1 > r.x0:
                continue
            if not _is_prose_like(l.text):
                continue
            dx = r.x0 - l.x1
            if dx < best_dx:
                best_dx = dx
                best_j = j

        if best_j is None:
            continue

        l = updated.get(best_j, lines[best_j])
        merged_text = f"{(l.text or '').rstrip()} {(r.text or '').lstrip()}".strip()
        updated[best_j] = _Line(
            page_index=l.page_index,
            x0=min(l.x0, r.x0),
            y0=min(l.y0, r.y0),
            x1=max(l.x1, r.x1),
            y1=max(l.y1, r.y1),
            text=merged_text,
            font_size=float(median([fs for fs in (l.font_size, r.font_size) if fs > 0]) or (l.font_size or r.font_size or 0.0)),
            block_no=l.block_no,
        )
        remove.add(i)

    if not remove and not updated:
        return lines

    out: List[_Line] = []
    for k, l in enumerate(lines):
        if k in remove:
            continue
        out.append(updated.get(k, l))
    return out


def _drop_algorithm_blocks_in_lines(
    lines: List[_Line],
    *,
    page_w: float,
    page_h: float,
    avg_h: float,
    config: ExtractionConfig,
) -> List[_Line]:
    if not config.drop_algorithms or not lines or page_w <= 0 or page_h <= 0 or avg_h <= 0:
        return lines

    cap_re = re.compile(config.algorithm_caption_re, flags=re.IGNORECASE)
    by_y = sorted(lines, key=lambda l: (l.y0, l.x0))
    cap_idxs = [i for i, l in enumerate(by_y) if cap_re.match((l.text or "").strip())]
    if not cap_idxs:
        return lines

    max_gap = avg_h * float(config.algorithm_block_max_gap_line_height_mult)
    max_h = page_h * float(config.algorithm_block_max_height_ratio)
    max_lines = int(config.algorithm_block_max_lines)

    drop: set[_Line] = set()
    mid = page_w * float(config.column_split_ratio)

    for i0 in cap_idxs:
        cap = by_y[i0]
        if cap in drop:
            continue
        cap_col = _column_of(cap, page_w=page_w, config=config)
        cap_y0 = float(cap.y0)
        cap_full_width = cap.x1 > (mid + page_w * 0.02)

        drop.add(cap)
        prev = cap
        kept = 0

        for l in by_y[i0 + 1 :]:
            if l in drop:
                continue
            if l.y0 < cap_y0:
                continue
            if float(l.y1 - cap_y0) > max_h:
                break
            if kept >= max_lines:
                break

            # Stay within the same column region as the caption.
            if not cap_full_width and _column_of(l, page_w=page_w, config=config) != cap_col:
                break

            gap = _line_gap(prev, l)
            if gap > max_gap:
                break
            drop.add(l)
            prev = l
            kept += 1

    if not drop:
        return lines
    return [l for l in lines if l not in drop]


def _drop_figure_body_near_captions(
    lines: List[_Line],
    *,
    page_index: int,
    page_w: float,
    page_h: float,
    avg_h: float,
    config: ExtractionConfig,
) -> List[_Line]:
    """
    Drop non-prose figure/plot labels in a band above a "Figure N:" caption.

    This suppresses stray diagram labels like "n", "k", "β", "0%" that PyMuPDF may
    emit as standalone text, while keeping captions and body prose.
    """
    if (
        not config.figure_handling
        or not lines
        or page_w <= 0
        or page_h <= 0
        or avg_h <= 0
    ):
        return lines

    cap_re = re.compile(config.figure_caption_re, flags=re.IGNORECASE)
    caps = [l for l in lines if l.page_index == page_index and cap_re.match((l.text or "").strip())]
    if not caps:
        return lines

    win = page_h * float(config.figure_caption_window_ratio)
    drop: set[_Line] = set()

    for cap in caps:
        band_y0 = max(0.0, float(cap.y0) - win)
        band_y1 = float(cap.y0)
        cap_col = _column_of(cap, page_w=page_w, config=config)
        strong_candidates: List[_Line] = []

        for l in lines:
            if l.page_index != page_index or l is cap or l in drop:
                continue
            if l.y1 <= band_y0 or l.y0 >= band_y1:
                continue
            if _column_of(l, page_w=page_w, config=config) != cap_col:
                continue

            s = (l.text or "").strip()
            if not s:
                continue
            # Keep captions and real prose.
            if _is_caption_line(l, page_w=page_w, median_width=0.0, config=config):
                continue
            if _is_sentence_like(s) or _is_prose_like(s):
                continue

            short = len(s) <= int(config.figure_body_drop_max_chars)
            mathish = _is_mathish_text(s)
            narrow = l.width <= (page_w * 0.32)
            labelish = bool(
                re.fullmatch(r"[A-Za-zα-ωΑ-Ω0-9%+\-−=·_./:]+", s)
                or len(s) <= 12
            )
            if narrow and ((short and labelish) or (mathish and len(s) <= 16)):
                strong_candidates.append(l)

        # Only drop when we see a local cluster; avoids deleting isolated math/prose fragments.
        if len(strong_candidates) >= 3:
            drop.update(strong_candidates)

    if not drop:
        return lines
    return [l for l in lines if l not in drop]


def _drop_table_body_lines_near_captions(
    lines: List[_Line],
    *,
    page_index: int,
    page_w: float,
    page_h: float,
    avg_h: float,
    config: ExtractionConfig,
) -> List[_Line]:
    """
    Drop table body cell text near a "Table N:" caption (line-level).

    This complements paragraph-level table dropping, and helps with small tables
    that do not generate many separate paragraphs.
    """
    if not config.table_handling or not lines or page_w <= 0 or page_h <= 0 or avg_h <= 0:
        return lines

    cap_re = re.compile(config.table_caption_re, flags=re.IGNORECASE)
    caps = [l for l in lines if l.page_index == page_index and cap_re.match((l.text or "").strip())]
    if not caps:
        return lines

    win = page_h * float(config.table_caption_window_ratio)
    drop: set[_Line] = set()

    for cap in caps:
        cap_col = _column_of(cap, page_w=page_w, config=config)
        # Asymmetric cleanup:
        # - above caption: aggressive cleanup (table headers / plot labels often live here)
        # - below caption: conservative cleanup to avoid dropping real prose lines
        bands = [
            (max(0.0, float(cap.y0) - win), float(cap.y0), "above"),
            (float(cap.y1), min(page_h, float(cap.y1) + win), "below"),
        ]
        for band_y0, band_y1, where in bands:
            below_strong: List[_Line] = []
            for l in lines:
                if l.page_index != page_index or l is cap or l in drop:
                    continue
                if l.y1 <= band_y0 or l.y0 >= band_y1:
                    continue
                if _column_of(l, page_w=page_w, config=config) != cap_col:
                    continue

                s = (l.text or "").strip()
                if not s:
                    continue
                if _is_caption_line(l, page_w=page_w, median_width=0.0, config=config):
                    continue
                if _is_sentence_like(s) or _is_prose_like(s):
                    continue
                score = _table_like_score(s)
                mathish = _is_mathish_text(s)

                # Above-caption band keeps the old aggressive behavior.
                if where == "above":
                    if len(s) <= 40 or score >= float(config.table_like_min_score) or mathish:
                        drop.add(l)
                    continue

                # Below-caption band is conservative:
                # never drop by short-length alone; require stronger table-like evidence.
                strong_score = score >= max(float(config.table_like_min_score) + 0.10, 0.34)
                strong_math = mathish and len(s) <= 24
                if strong_score or strong_math:
                    below_strong.append(l)

            # Apply below-caption drop only when we have a local cluster of strong evidence.
            if where == "below" and len(below_strong) >= 3:
                drop.update(below_strong)

    if not drop:
        return lines
    return [l for l in lines if l not in drop]


def _merge_math_placeholders_into_previous(paras: List[_Paragraph], *, config: ExtractionConfig) -> List[_Paragraph]:
    """
    Merge a standalone display-math placeholder paragraph into the previous prose paragraph.

    This addresses cases where a numbered display equation splits a sentence:
      "... , h"  +  "[MATH] (1)"  -> merged into one paragraph.
    """
    if not paras:
        return paras

    out: List[_Paragraph] = []
    score_threshold = int(config.math_context_score_threshold)

    def is_math_placeholder(p: _Paragraph) -> bool:
        if p.is_caption:
            return False
        t = (p.text or "").strip()
        return bool(t) and t.startswith(str(config.display_math_placeholder))

    def is_numbered_math_placeholder(p: _Paragraph) -> bool:
        t = (p.text or "").strip()
        if not (t and t.startswith(str(config.display_math_placeholder))):
            return False
        # Accept both "[MATH] (1)" and "[MATH](1)" styles.
        return bool(re.search(r"\(\s*\d{1,3}(?:\.\d{1,2}|[a-z])?\s*\)", t))

    def _find_prev_out_index() -> Optional[int]:
        j = len(out) - 1
        while j >= 0:
            cand = out[j]
            if cand.is_caption or is_math_placeholder(cand):
                j -= 1
                continue
            if _is_prose_like((cand.text or "").strip()) or _is_sentence_like((cand.text or "").strip()):
                return j
            j -= 1
        return None

    def _find_next_index(start: int) -> Optional[int]:
        k = start
        while k < len(paras):
            cand = paras[k]
            if cand.is_caption or is_math_placeholder(cand):
                k += 1
                continue
            if _is_prose_like((cand.text or "").strip()) or _is_sentence_like((cand.text or "").strip()):
                return k
            k += 1
        return None

    i = 0
    while i < len(paras):
        p = paras[i]
        if not is_math_placeholder(p):
            out.append(p)
            i += 1
            continue

        numbered = is_numbered_math_placeholder(p)
        if (not config.merge_unnumbered_math_placeholders_into_previous) and (not numbered):
            # Keep as standalone placeholder; do not force-merge into prose.
            out.append(p)
            i += 1
            continue

        placeholder_text = (p.text or "").strip()
        prev_out_idx = _find_prev_out_index()
        next_idx = _find_next_index(i + 1)
        prev_score = -10**6
        next_score = -10**6

        if prev_out_idx is not None and out[prev_out_idx].lines and p.lines:
            prev_last = out[prev_out_idx].lines[-1]
            cur_first = p.lines[0]
            approx_w = max(prev_last.x1, cur_first.x1, 1.0)
            avg_h = float(median([h for h in (prev_last.height, cur_first.height) if h > 0]) or [10.0])
            prev_score = _line_pair_continuity_score(
                prev_last,
                cur_first,
                page_w=approx_w,
                avg_h=avg_h,
                config=config,
            )

        if next_idx is not None and paras[next_idx].lines and p.lines:
            next_first = paras[next_idx].lines[0]
            cur_last = p.lines[-1]
            approx_w = max(next_first.x1, cur_last.x1, 1.0)
            avg_h = float(median([h for h in (next_first.height, cur_last.height) if h > 0]) or [10.0])
            next_score = _line_pair_continuity_score(
                cur_last,
                next_first,
                page_w=approx_w,
                avg_h=avg_h,
                config=config,
            )

        direction = "skip"
        if prev_score >= score_threshold and next_score >= score_threshold:
            prev_text = (out[prev_out_idx].text or "").rstrip() if prev_out_idx is not None else ""
            next_text = (paras[next_idx].text or "").lstrip() if next_idx is not None else ""
            if prev_text and not prev_text.endswith((".", ":", ";")):
                direction = "merge_prev"
            elif _looks_like_continuation_start(next_text):
                direction = "merge_next"
            elif numbered:
                direction = "keep"
            elif not config.math_context_skip_ambiguous:
                direction = "merge_prev"
        elif prev_score >= score_threshold:
            direction = "merge_prev"
        elif next_score >= score_threshold:
            direction = "merge_next"
        else:
            direction = "keep" if numbered else "skip"

        if direction == "merge_prev" and prev_out_idx is not None:
            prev = out[prev_out_idx]
            prev_last_text = (prev.lines[-1].text or "").rstrip() if prev.lines else ""
            merged_text = f"{prev_last_text} {placeholder_text}".strip()
            out[prev_out_idx] = _replace_last_line_text(prev, merged_text)
        elif direction == "merge_next" and next_idx is not None:
            nxt = paras[next_idx]
            next_first_text = (nxt.lines[0].text or "").lstrip() if nxt.lines else ""
            merged_text = f"{placeholder_text} {next_first_text}".strip()
            paras[next_idx] = _replace_first_line_text(nxt, merged_text)
        elif direction == "keep":
            out.append(p)
        # else: skip placeholder paragraph entirely

        i += 1

    return out


@dataclass(frozen=True)
class _PageMetrics:
    avg_h: float
    median_w: float
    page_med_fs: float
    band: _BodyBand
    body_med_fs: float


def _compute_page_metrics(
    lines: List[_Line],
    *,
    page_w: float,
    page_h: float,
    config: ExtractionConfig,
) -> _PageMetrics:
    avg_h = _page_avg_line_height(lines)
    median_w = _page_median_line_width(lines)
    fs_samples = [l.font_size for l in lines if l.font_size > 0]
    page_med_fs = float(median(fs_samples)) if fs_samples else 0.0
    band = (
        _compute_body_band(lines, page_w=page_w, page_h=page_h, config=config)
        if config.prefer_statistical_body_band
        else _BodyBand(ok=False, y0=0.0, y1=0.0, med_fs=0.0, med_h=0.0, med_w=0.0)
    )
    body_med_fs = float(band.med_fs) if band.ok else 0.0
    return _PageMetrics(
        avg_h=avg_h,
        median_w=median_w,
        page_med_fs=page_med_fs,
        band=band,
        body_med_fs=body_med_fs,
    )


def _is_page_number_line(
    line: _Line,
    *,
    page_w: float,
    page_h: float,
    metrics: _PageMetrics,
    config: ExtractionConfig,
) -> bool:
    if not config.drop_page_numbers:
        return False
    s = (line.text or "").strip()
    if not s:
        return False
    if not re.match(config.page_number_re, s):
        return False
    if page_h <= 0:
        return False
    if config.prefer_statistical_body_band and metrics.band.ok:
        if not _is_outside_body_band(line, band=metrics.band, config=config, page_h=page_h):
            return False
    else:
        margin = page_h * float(config.page_number_margin_ratio)
        near_edge = (line.y0 <= margin) or (line.y1 >= (page_h - margin))
        if not near_edge:
            return False
    xc = (line.x0 + line.x1) / 2.0
    centered = abs(xc - (page_w / 2.0)) <= (page_w * float(config.page_number_center_tol_ratio))
    cornerish = (line.x0 <= (page_w * 0.2)) or (line.x1 >= (page_w * 0.8))
    if not (centered or cornerish):
        return False
    if metrics.body_med_fs > 0 and line.font_size > (metrics.body_med_fs * 1.3):
        return False
    return True


def _filter_page_numbers(
    lines: List[_Line],
    *,
    page_w: float,
    page_h: float,
    metrics: _PageMetrics,
    config: ExtractionConfig,
) -> List[_Line]:
    return [
        l for l in lines
        if not _is_page_number_line(l, page_w=page_w, page_h=page_h, metrics=metrics, config=config)
    ]


def _filter_narrow_tall_lines(
    lines: List[_Line],
    *,
    page_w: float,
    page_h: float,
    metrics: _PageMetrics,
    config: ExtractionConfig,
) -> List[_Line]:
    if not config.drop_narrow_tall_lines or page_w <= 0 or page_h <= 0:
        return lines
    band = metrics.band
    return [
        l for l in lines
        if not (
            (
                band.ok
                and band.med_w > 0
                and l.width < (band.med_w * 0.25)
                and band.med_h > 0
                and l.height > (band.med_h * 3.0)
            )
            or (
                (not band.ok)
                and l.width < (page_w * float(config.narrow_line_width_ratio))
                and l.height > (page_h * float(config.tall_line_height_ratio))
            )
        )
    ]


def _merge_same_baseline_lines(
    lines: List[_Line],
    *,
    page_w: float,
    metrics: _PageMetrics,
    config: ExtractionConfig,
) -> List[_Line]:
    avg_h = metrics.avg_h
    page_med_fs = metrics.page_med_fs
    if not config.same_baseline_merge or avg_h <= 0 or page_w <= 0:
        return lines
    y_tol = avg_h * float(config.same_baseline_y_tol_mult)
    by_yx = sorted(lines, key=lambda l: (l.y0, l.x0))
    merged: List[_Line] = []
    i = 0
    while i < len(by_yx):
        cur = by_yx[i]
        if i + 1 < len(by_yx):
            nxt = by_yx[i + 1]
            same_row = abs(cur.y0 - nxt.y0) <= y_tol and abs(cur.y1 - nxt.y1) <= y_tol
            same_col = _column_of(cur, page_w=page_w, config=config) == _column_of(nxt, page_w=page_w, config=config)
            if same_row and same_col and _font_size_consistent(cur, nxt, config=config):
                left, right = (cur, nxt) if cur.x0 <= nxt.x0 else (nxt, cur)
                x_gap = float(right.x0 - left.x1)
                gap_thresh = max(1.5, float(cur.font_size or page_med_fs or 10.0) * float(config.same_baseline_x_gap_font_mult))
                if -1.0 <= x_gap <= gap_thresh:
                    text = f"{left.text.rstrip()} {right.text.lstrip()}".strip()
                    merged.append(
                        _Line(
                            page_index=cur.page_index,
                            x0=min(cur.x0, nxt.x0),
                            y0=min(cur.y0, nxt.y0),
                            x1=max(cur.x1, nxt.x1),
                            y1=max(cur.y1, nxt.y1),
                            text=text,
                            font_size=float(median([fs for fs in (cur.font_size, nxt.font_size) if fs > 0]) or (cur.font_size or nxt.font_size or 0.0)),
                            block_no=cur.block_no,
                        )
                    )
                    i += 2
                    continue
        merged.append(cur)
        i += 1
    return merged


def _is_footnote_start(
    line: _Line,
    *,
    band_y0: float,
    metrics: _PageMetrics,
    config: ExtractionConfig,
) -> bool:
    if line.y0 < band_y0:
        return False
    s = (line.text or "").strip()
    if not s:
        return False
    if not re.match(config.footnote_start_re, s):
        return False
    if metrics.body_med_fs > 0 and line.font_size > (metrics.body_med_fs * float(config.footnote_font_size_mult)):
        return False
    if re.match(config.page_number_re, s):
        return False
    return True


def _drop_footnotes(
    lines: List[_Line],
    *,
    page_w: float,
    page_h: float,
    metrics: _PageMetrics,
    config: ExtractionConfig,
) -> List[_Line]:
    if not config.drop_footnotes or page_h <= 0 or page_w <= 0:
        return lines
    avg_h = metrics.avg_h
    band = metrics.band
    if config.prefer_statistical_body_band and band.ok:
        band_y0 = float(max(page_h * 0.68, band.y1 - max(band.med_h, avg_h, 1.0) * 2.0))
    else:
        band_y0 = page_h * (1.0 - float(config.footnote_margin_ratio))
    by_y = sorted(lines, key=lambda l: (l.y0, l.x0))
    drop: set[_Line] = set()
    for i, ln in enumerate(by_y):
        if ln in drop:
            continue
        if not _is_footnote_start(ln, band_y0=band_y0, metrics=metrics, config=config):
            continue
        drop.add(ln)
        col0 = _column_of(ln, page_w=page_w, config=config)
        prev = ln
        kept = 0
        for ln2 in by_y[i + 1:]:
            if ln2.y0 < band_y0:
                continue
            if _column_of(ln2, page_w=page_w, config=config) != col0:
                continue
            gap = _line_gap(prev, ln2)
            if gap > (avg_h * float(config.footnote_continuation_gap_line_height_mult)):
                break
            if metrics.body_med_fs > 0 and ln2.font_size > (metrics.body_med_fs * float(config.footnote_font_size_mult) * 1.05):
                break
            if _x_overlap_ratio(prev, ln2) < float(config.overlap_min_ratio):
                break
            s2 = (ln2.text or "").strip()
            if re.match(config.page_number_re, s2):
                continue
            drop.add(ln2)
            prev = ln2
            kept += 1
            if kept >= int(config.footnote_continuation_max_lines):
                break
    if drop:
        return [l for l in lines if l not in drop]
    return lines


def _apply_drop_front_matter(lines: List[_Line], *, config: ExtractionConfig) -> List[_Line]:
    stop_re = re.compile(config.front_matter_stop_re, flags=re.IGNORECASE)
    stop_y = None
    for l in sorted(lines, key=lambda ln: (ln.y0, ln.x0)):
        s = (l.text or "").strip()
        if not s:
            continue
        if stop_re.match(s):
            stop_y = float(l.y0)
            break
    if stop_y is not None:
        return [l for l in lines if float(l.y1) >= stop_y]
    return lines


def _assemble_paragraphs(
    lines: List[_Line],
    *,
    page_w: float,
    page_h: float,
    metrics: _PageMetrics,
    config: ExtractionConfig,
) -> List[_Paragraph]:
    avg_h = metrics.avg_h
    median_w = metrics.median_w
    page_med_fs = metrics.page_med_fs
    with_col = [(l, _column_of(l, page_w=page_w, config=config)) for l in lines]
    with_col.sort(key=lambda t: (t[1], t[0].y0, t[0].x0))
    paras: List[_Paragraph] = []
    cur: List[_Line] = []
    cur_is_caption = False
    cur_is_labelled_caption = False
    cur_caption_lines = 0
    cur_col: Optional[int] = None

    def flush() -> None:
        nonlocal cur, cur_is_caption, cur_is_labelled_caption, cur_caption_lines
        if not cur:
            return
        if not cur_is_caption and len(cur) == 1 and _is_page_number_line(cur[0], page_w=page_w, page_h=page_h, metrics=metrics, config=config):
            cur = []
            cur_is_caption = False
            return
        paras.append(_Paragraph(paragraph_id=-1, lines=list(cur), is_caption=cur_is_caption))
        cur = []
        cur_is_caption = False
        cur_is_labelled_caption = False
        cur_caption_lines = 0

    i = 0
    while i < len(with_col):
        line, col = with_col[i]
        if (line.text or "").strip().startswith(str(config.display_math_placeholder)):
            flush()
            paras.append(_Paragraph(paragraph_id=-1, lines=[line], is_caption=False))
            cur_col = None
            i += 1
            continue
        line_is_caption = _is_caption_line(line, page_w=page_w, median_width=median_w, config=config)
        if i + 1 < len(with_col):
            next_line, next_col = with_col[i + 1]
            if (
                col == next_col
                and (line.text or "").strip().isdigit()
                and page_med_fs > 0
                and next_line.font_size > (page_med_fs * float(config.heading_font_size_mult))
            ):
                s2 = (next_line.text or "").strip()
                if (
                    s2
                    and len(s2) <= int(config.heading_max_chars)
                    and not s2.endswith((".", ":", ";"))
                    and not _is_caption_line(next_line, page_w=page_w, median_width=median_w, config=config)
                ):
                    baseline_close = (abs(line.y0 - next_line.y0) <= (avg_h * 0.3)) and (
                        abs(line.y1 - next_line.y1) <= (avg_h * 0.3)
                    )
                    left_to_right = next_line.x0 >= (line.x1 - 1.0)
                    if baseline_close and left_to_right:
                        flush()
                        paras.append(_Paragraph(paragraph_id=-1, lines=[line, next_line], is_caption=False))
                        cur_col = None
                        i += 2
                        continue
        s = (line.text or "").strip()
        line_is_heading = False
        if config.split_headings and s and not line_is_caption and not s.isdigit():
            if (
                page_med_fs > 0
                and line.font_size > (page_med_fs * float(config.heading_font_size_mult))
                and len(s) <= int(config.heading_max_chars)
                and not s.endswith((".", ":", ";"))
            ):
                line_is_heading = True
            if not line_is_heading:
                if (
                    len(s) <= int(config.heading_numbered_max_chars)
                    and re.match(config.heading_numbered_re, s)
                    and not s.endswith((".", ":", ";", ","))
                    and re.search(r"[A-Za-z]", s)
                ):
                    if not re.search(r"[.!?][\"'\)\]]*\s*$", s):
                        words = s.split()
                        if 2 <= len(words) <= int(config.heading_numbered_max_words):
                            line_is_heading = True
        if line_is_heading:
            flush()
            paras.append(_Paragraph(paragraph_id=-1, lines=[line], is_caption=False))
            cur_col = None
            i += 1
            continue
        if not cur:
            cur = [line]
            cur_is_caption = line_is_caption
            cur_is_labelled_caption = bool(re.search(config.caption_re, (line.text or "").strip(), flags=re.IGNORECASE))
            cur_caption_lines = 1 if cur_is_caption else 0
            cur_col = col
            i += 1
            continue
        assert cur_col is not None
        prev = cur[-1]
        same_col = col == cur_col
        gap = _line_gap(prev, line)
        gap_threshold = avg_h * float(config.paragraph_gap_line_height_mult)
        should_break = (not same_col) or (gap > gap_threshold)
        if (
            should_break
            and config.allow_cross_column_continuations
            and (not same_col)
            and cur_col == 0
            and col == 1
            and page_h > 0
            and not cur_is_caption
        ):
            prev_text = (prev.text or "").rstrip()
            cur_text = (line.text or "").lstrip()
            prev_ends_sentence = bool(re.search(r"[.!?][\"'\)\]]*\s*$", prev_text))
            cur_looks_like_cont = bool(re.match(r"^([a-z]|[,\)\]])", cur_text))
            prev_near_bottom = float(prev.y1) >= (page_h * (1.0 - float(config.cross_column_prev_bottom_ratio)))
            cur_near_top = float(line.y0) <= (page_h * float(config.cross_column_next_top_ratio))
            if (not prev_ends_sentence) and cur_looks_like_cont and prev_near_bottom and cur_near_top:
                if not line_is_caption and _font_size_consistent(prev, line, config=config):
                    should_break = False
        if (
            cur_is_caption
            and cur_is_labelled_caption
            and not line_is_caption
            and not should_break
            and cur_caption_lines < int(config.caption_multiline_max_lines)
        ):
            if gap <= (avg_h * float(config.caption_multiline_gap_line_height_mult)):
                if _x_overlap_ratio(prev, line) >= float(config.overlap_min_ratio) and _font_size_consistent(prev, line, config=config):
                    prev_text = (prev.text or "").rstrip()
                    cur_text = (line.text or "").lstrip()
                    if not (
                        (prev_text.endswith(".") and cur_text[:1].islower())
                        or (
                            prev_text.endswith(".")
                            and cur_text[:1].isupper()
                            and len(cur_text) >= 60
                            and (_is_sentence_like(cur_text) or _is_prose_like(cur_text))
                        )
                    ):
                        line_is_caption = True
        if cur_is_caption and not line_is_caption and not should_break and median_w > 0:
            if line.width <= (median_w * float(config.caption_width_ratio)):
                center = (line.x0 + line.x1) / 2.0
                centered = abs(center - (page_w / 2.0)) <= (page_w * float(config.caption_center_tol_ratio))
                overlap_ok = _x_overlap_ratio(prev, line) >= float(config.overlap_min_ratio)
                if centered or overlap_ok:
                    prev_text = (prev.text or "").rstrip()
                    cur_text = (line.text or "").lstrip()
                    if not (
                        prev_text.endswith(".")
                        and cur_text[:1].islower()
                        and len(cur_text) >= 40
                        and _is_sentence_like(cur_text)
                    ):
                        line_is_caption = True
        if not should_break and (cur_is_caption != line_is_caption):
            should_break = True
        if not should_break and gap > (avg_h * float(config.sentence_gap_line_height_mult)):
            prev_text = (prev.text or "").rstrip()
            cur_text = (line.text or "").lstrip()
            if prev_text.endswith((".", "?", "!")) and cur_text[:1].isupper():
                should_break = True
        if not should_break:
            if _x_overlap_ratio(prev, line) < float(config.overlap_min_ratio):
                should_break = True
            elif not _font_size_consistent(prev, line, config=config):
                should_break = True
        if should_break:
            flush()
            cur = [line]
            cur_is_caption = line_is_caption
            cur_is_labelled_caption = bool(re.search(config.caption_re, (line.text or "").strip(), flags=re.IGNORECASE))
            cur_caption_lines = 1 if cur_is_caption else 0
            cur_col = col
        else:
            cur.append(line)
            if col != cur_col:
                cur_col = col
            if cur_is_caption:
                cur_caption_lines += 1
        i += 1
    flush()
    return paras


def _build_paragraphs_for_page(
    *,
    page_index: int,
    page_w: float,
    page_h: float,
    lines: List[_Line],
    config: ExtractionConfig,
    drop_texts: Optional[set[str]] = None,
) -> List[_Paragraph]:
    if not lines:
        return []
    metrics = _compute_page_metrics(lines, page_w=page_w, page_h=page_h, config=config)
    lines = _filter_page_numbers(lines, page_w=page_w, page_h=page_h, metrics=metrics, config=config)
    if not lines:
        return []
    lines = _filter_narrow_tall_lines(lines, page_w=page_w, page_h=page_h, metrics=metrics, config=config)
    if not lines:
        return []
    if drop_texts:
        lines = [l for l in lines if (l.text or "").strip() not in drop_texts]
        if not lines:
            return []
    lines = _merge_same_baseline_lines(lines, page_w=page_w, metrics=metrics, config=config)
    if page_w > 0 and metrics.avg_h > 0:
        lines = _merge_right_floating_math_into_left_lines(lines, page_w=page_w, avg_h=metrics.avg_h, config=config)
    if page_w > 0 and page_h > 0 and metrics.avg_h > 0:
        lines = _drop_algorithm_blocks_in_lines(lines, page_w=page_w, page_h=page_h, avg_h=metrics.avg_h, config=config)
    if config.drop_front_matter and page_index == 0 and page_h > 0:
        lines = _apply_drop_front_matter(lines, config=config)
    if page_w > 0 and page_h > 0 and metrics.avg_h > 0:
        lines = _drop_table_body_lines_near_captions(
            lines, page_index=page_index, page_w=page_w, page_h=page_h, avg_h=metrics.avg_h, config=config
        )
    lines = _drop_footnotes(lines, page_w=page_w, page_h=page_h, metrics=metrics, config=config)
    if page_w > 0 and metrics.avg_h > 0:
        lines = _replace_display_math_lines(lines, page_index=page_index, page_w=page_w, avg_h=metrics.avg_h, config=config)
        lines = _replace_unnumbered_display_math_blocks(
            lines, page_index=page_index, page_w=page_w, page_h=page_h, avg_h=metrics.avg_h, config=config
        )
    paras = _assemble_paragraphs(lines, page_w=page_w, page_h=page_h, metrics=metrics, config=config)
    paras = _merge_caption_continuations_in_page(paras, page_index=page_index, avg_h=metrics.avg_h, config=config)
    paras = _split_caption_body_tails_in_page(paras, page_index=page_index, avg_h=metrics.avg_h)
    paras = _merge_equation_number_paragraphs(paras, page_index=page_index, page_w=page_w, avg_h=metrics.avg_h, config=config)
    paras = _replace_display_math_paragraphs(paras, page_index=page_index, page_w=page_w, config=config)
    paras = _drop_table_body_near_captions(paras, page_index=page_index, page_w=page_w, page_h=page_h, config=config)
    return paras


def _cross_page_merge(
    paragraphs: List[_Paragraph],
    *,
    page_sizes: Dict[int, Tuple[float, float]],
    page_avg_line_height: Dict[int, float],
    config: ExtractionConfig,
) -> List[_Paragraph]:
    if not paragraphs:
        return paragraphs

    def _first_line_on_page(para: _Paragraph, page_index: int) -> Optional[_Line]:
        candidates = [l for l in para.lines if l.page_index == page_index]
        if not candidates:
            return None
        return min(candidates, key=lambda l: (l.y0, l.x0))

    def _last_line_on_page(para: _Paragraph, page_index: int) -> Optional[_Line]:
        candidates = [l for l in para.lines if l.page_index == page_index]
        if not candidates:
            return None
        return max(candidates, key=lambda l: (l.y1, l.x1))

    def _has_same_page_prose_predecessor(out: List[_Paragraph], cur_para: _Paragraph, cur_first_page: int) -> bool:
        """
        If we already have a prose paragraph on the current page before `cur_para`,
        prefer staying within-page rather than forcing a cross-page merge.
        """
        cur_first = _first_line_on_page(cur_para, cur_first_page)
        if cur_first is None:
            return False
        for q in reversed(out):
            q_first_page = min(l.page_index for l in q.lines)
            if q_first_page < cur_first_page:
                break
            if q.is_caption:
                continue
            q_last = _last_line_on_page(q, cur_first_page)
            if q_last is None:
                continue
            if q_last.y1 > cur_first.y0:
                continue
            q_text = (q.text or "").strip()
            if not q_text:
                continue
            # Ignore tiny noise/labels/headings.
            if len(q_text) < 40:
                continue
            if re.match(r"^(?:\d{1,2}(?:\.\d{1,2})*)\s+\S", q_text):
                continue
            if _is_sentence_like(q_text) or _is_prose_like(q_text):
                return True
        return False

    def _best_prev_candidate_index(
        *,
        out: List[_Paragraph],
        cur_para: _Paragraph,
        cur_first_page: int,
        page_sizes: Dict[int, Tuple[float, float]],
        config: ExtractionConfig,
    ) -> Optional[int]:
        """
        Pick the best previous paragraph to merge with a cross-page continuation.

        We cannot rely on `out[-1]` because reading-order sorting can interleave
        other blocks/columns near the page bottom (headers/footers, side notes, etc.).
        """
        if cur_first_page <= 0:
            return None
        prev_page_no = cur_first_page  # 1-based page number
        cur_page_no = cur_first_page + 1
        prev_page_h = page_sizes.get(prev_page_no, (0.0, 0.0))[1]
        cur_w = page_sizes.get(cur_page_no, (0.0, 0.0))[0]
        if prev_page_h <= 0 or cur_w <= 0:
            return None

        cur_first_line = _first_line_on_page(cur_para, cur_first_page)
        if cur_first_line is None:
            return None

        best_i: Optional[int] = None
        best_score = -1e9
        scan = int(config.cross_page_search_back)
        start = max(0, len(out) - scan)
        for i in range(len(out) - 1, start - 1, -1):
            prev = out[i]
            if prev.is_caption:
                continue
            prev_last_page = max(l.page_index for l in prev.lines)
            if prev_last_page != cur_first_page - 1:
                continue
            prev_text = prev.text.rstrip()
            if prev_text.endswith((".", ":", ";")):
                continue
            prev_last_line = _last_line_on_page(prev, prev_last_page)
            if prev_last_line is None:
                continue

            # Require column alignment (x0 close or overlap) to avoid merging across columns.
            x0_diff = abs(prev_last_line.x0 - cur_first_line.x0)
            x0_close = x0_diff <= (cur_w * float(config.cross_page_x0_tol_ratio))
            overlap_ok = _x_overlap_ratio(prev_last_line, cur_first_line) >= float(config.overlap_min_ratio)
            if not (x0_close or overlap_ok):
                continue

            # Prefer paragraphs that end close to the bottom of the previous page.
            bottomness = float(prev_last_line.y1) / float(prev_page_h)
            score = bottomness - (x0_diff / cur_w)
            if score > best_score:
                best_score = score
                best_i = i

        return best_i

    out: List[_Paragraph] = []
    for p in paragraphs:
        if not out:
            out.append(p)
            continue

        cur_first_page = min(l.page_index for l in p.lines)

        # Always keep captions as standalone paragraphs in output order.
        if p.is_caption:
            out.append(p)
            continue

        # Only consider cross-page merge when current starts on page N+1.
        # We'll select the best previous paragraph ending on page N.
        cand_index = _best_prev_candidate_index(
            out=out,
            cur_para=p,
            cur_first_page=cur_first_page,
            page_sizes=page_sizes,
            config=config,
        )
        if cand_index is None:
            out.append(p)
            continue

        cur_text_full = (p.text or "").strip()
        if len(cur_text_full) < 30 and not (_is_sentence_like(cur_text_full) or _is_prose_like(cur_text_full)):
            out.append(p)
            continue

        if _has_same_page_prose_predecessor(out, p, cur_first_page):
            out.append(p)
            continue

        prev = out[cand_index]
        prev_last_page = max(l.page_index for l in prev.lines)
        if cur_first_page != prev_last_page + 1:
            out.append(p)
            continue

        prev_text = prev.text.rstrip()
        if prev_text.endswith((".", ":", ";")):
            out.append(p)
            continue

        # Optional guard: continuation line usually starts with lowercase.
        if config.cross_page_require_lowercase_start:
            cur_text = (p.text or "").lstrip()
            if cur_text[:1] and not cur_text[:1].islower():
                out.append(p)
                continue

        prev_page = prev_last_page + 1
        cur_page = cur_first_page + 1
        prev_w, prev_page_h = page_sizes.get(prev_page, (0.0, 0.0))
        cur_w, cur_page_h = page_sizes.get(cur_page, (0.0, 0.0))
        if prev_page_h <= 0 or cur_page_h <= 0:
            out.append(p)
            continue

        prev_h = page_avg_line_height.get(prev_page, 10.0)
        cur_h = page_avg_line_height.get(cur_page, 10.0)
        h = float(mean([prev_h, cur_h])) if (prev_h and cur_h) else float(prev_h or cur_h or 10.0)

        prev_last = _last_line_on_page(prev, prev_last_page)
        cur_first = _first_line_on_page(p, cur_first_page)
        if prev_last is None or cur_first is None:
            out.append(p)
            continue

        prev_bottom = float(prev_last.y1)
        cur_top = float(cur_first.y0)
        boundary_gap = (prev_page_h - prev_bottom) + cur_top

        # Strict rule: small boundary whitespace.
        should_merge = boundary_gap < (h * float(config.cross_page_gap_line_height_mult))

        # Relaxed rule: captions (or other floats) can push the continuation down.
        # In that case, require strong horizontal alignment and proximity to page edges.
        if not should_merge and config.cross_page_skip_captions:
            remaining = prev_page_h - prev_bottom
            prev_near_bottom = remaining < (h * float(config.cross_page_prev_bottom_max_lines))
            cur_near_top = cur_top < (cur_page_h * float(config.cross_page_next_top_max_ratio))
            x0_close = abs(prev_last.x0 - cur_first.x0) <= (float(cur_w or prev_w) * float(config.cross_page_x0_tol_ratio))
            overlap_ok = _x_overlap_ratio(prev_last, cur_first) >= float(config.overlap_min_ratio)
            # If the previous paragraph ends with a connector, allow a larger remaining space.
            prev_connector = bool(re.search(r"(?:,|\b(?:and|or|where|which|that|because)\b)\s*$", prev_text, flags=re.IGNORECASE))
            if (not prev_near_bottom) and prev_connector:
                prev_near_bottom = remaining < (h * float(config.cross_page_prev_bottom_max_lines_relaxed))

            if prev_near_bottom and (x0_close or overlap_ok):
                # If the current page starts with a figure/table caption, the continuation
                # paragraph can be pushed down significantly.
                has_caption_before = False
                for q in reversed(out):
                    q_first = min(l.page_index for l in q.lines) if q.lines else -1
                    if q_first < cur_first_page:
                        break
                    if q.is_caption:
                        has_caption_before = True
                        break
                if cur_near_top:
                    should_merge = True
                elif has_caption_before and cur_top < (cur_page_h * float(config.cross_page_next_top_max_ratio_with_captions)):
                    should_merge = True

        if should_merge:
            out[cand_index] = _Paragraph(paragraph_id=-1, lines=prev.lines + p.lines, is_caption=False)
        else:
            out.append(p)

    return out


def extract_paragraphs_pymupdf(
    pdf_path: str | Path,
    *,
    config: Optional[ExtractionConfig] = None,
) -> List[Dict[str, Any]]:
    _require_pymupdf()
    cfg = config or ExtractionConfig()
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(str(path))
    doc = fitz.open(str(path))
    try:
        return _extract_from_doc(doc, cfg)
    finally:
        doc.close()


def extract_paragraphs_pymupdf_bytes(
    pdf_bytes: bytes,
    *,
    config: Optional[ExtractionConfig] = None,
) -> List[Dict[str, Any]]:
    _require_pymupdf()
    cfg = config or ExtractionConfig()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        return _extract_from_doc(doc, cfg)
    finally:
        doc.close()


def _extract_from_doc(doc: Any, cfg: ExtractionConfig) -> List[Dict[str, Any]]:
    # Extract lines per page first (dict output)
    page_sizes: Dict[int, Tuple[float, float]] = {}
    page_avg_h: Dict[int, float] = {}
    page_paras: List[_Paragraph] = []
    page_lines: Dict[int, List[_Line]] = {}

    for page_index in range(doc.page_count):
        page = doc.load_page(page_index)
        page_w = float(page.rect.width)
        page_h = float(page.rect.height)
        page_sizes[page_index + 1] = (page_w, page_h)

        d = page.get_text("dict")
        lines = _iter_lines_from_page_dict(d, page_index=page_index, config=cfg)
        page_lines[page_index + 1] = lines
        page_avg_h[page_index + 1] = _page_avg_line_height(lines) if lines else 10.0

    drop_texts: set[str] = set()
    if cfg.drop_running_headers_footers and page_sizes and page_lines:
        margin_ratio = float(cfg.running_header_footer_margin_ratio)
        min_pages = int(cfg.running_header_footer_min_pages)
        min_len = int(cfg.running_header_footer_min_len)
        page_bands: Dict[int, _BodyBand] = {}
        if cfg.prefer_statistical_body_band:
            for page_no, lines in page_lines.items():
                w, h = page_sizes.get(page_no, (0.0, 0.0))
                if w <= 0 or h <= 0 or not lines:
                    continue
                page_bands[page_no] = _compute_body_band(lines, page_w=w, page_h=h, config=cfg)

        counts: Dict[str, set[int]] = {}
        for page_no, lines in page_lines.items():
            _w, h = page_sizes.get(page_no, (0.0, 0.0))
            if h <= 0:
                continue
            band = page_bands.get(page_no)
            margin = h * margin_ratio
            for l in lines:
                s = (l.text or "").strip()
                if len(s) < min_len:
                    continue
                if cfg.prefer_statistical_body_band and band and band.ok:
                    if not _is_outside_body_band(l, band=band, config=cfg, page_h=h):
                        continue
                else:
                    if not (l.y0 <= margin or l.y1 >= (h - margin)):
                        continue
                if re.match(cfg.page_number_re, s):
                    continue
                counts.setdefault(s, set()).add(page_no)
        for s, pageset in counts.items():
            if len(pageset) >= min_pages:
                drop_texts.add(s)

    for page_index in range(doc.page_count):
        page_no = page_index + 1
        page = doc.load_page(page_index)
        page_w = float(page.rect.width)
        page_h = float(page.rect.height)
        lines = page_lines.get(page_no, [])
        page_paras.extend(
            _build_paragraphs_for_page(
                page_index=page_index,
                page_w=page_w,
                page_h=page_h,
                lines=lines,
                config=cfg,
                drop_texts=drop_texts,
            )
        )

    page_paras = _cross_page_merge(page_paras, page_sizes=page_sizes, page_avg_line_height=page_avg_h, config=cfg)
    page_paras = _merge_math_placeholders_into_previous(page_paras, config=cfg)
    page_paras = _trim_after_references_heading(page_paras, config=cfg)
    if cfg.drop_heading_paragraphs:
        page_paras = [p for p in page_paras if not _is_heading_only_paragraph(p, config=cfg)]
    if cfg.drop_tiny_noise_paragraphs:
        page_paras = [p for p in page_paras if not _is_tiny_noise_paragraph(p, config=cfg)]

    # Assign global paragraph IDs deterministically and emit JSON-serializable dicts
    out: List[Dict[str, Any]] = []
    for i, p in enumerate(page_paras):
        out.append(
            {
                "paragraph_id": i,
                "text": p.text,
                "pages": p.pages,
                "bboxes": p.bboxes_by_page(),
                "_anchor": p.anchor_bbox(),
                "is_caption": bool(p.is_caption),
                "_median_font_size": float(median([l.font_size for l in p.lines if l.font_size > 0]) or [0.0]),
            }
        )
    return out


def extract_paragraphs_from_pymupdf_dict(
    pymupdf_dict: Dict[str, Any],
    *,
    config: Optional[ExtractionConfig] = None,
) -> List[Dict[str, Any]]:
    """
    Extract paragraphs from an already-dumped PyMuPDF dict JSON.

    Expected structure (as dumped by `zotero-annotator dev dump-pymupdf-dict`):
      {
        "pages": [
          {"page": 1, "width": <float>, "height": <float>, "dict": <page.get_text('dict') output>},
          ...
        ]
      }
    """
    cfg = config or ExtractionConfig()
    pages = pymupdf_dict.get("pages") if isinstance(pymupdf_dict, dict) else None
    if not isinstance(pages, list):
        raise ValueError("invalid pymupdf_dict: missing 'pages' list")

    page_sizes: Dict[int, Tuple[float, float]] = {}
    page_avg_h: Dict[int, float] = {}
    page_paras: List[_Paragraph] = []
    page_lines: Dict[int, List[_Line]] = {}

    for p in pages:
        if not isinstance(p, dict):
            continue
        page_no = int(p.get("page") or 0)
        if page_no <= 0:
            continue
        page_w = float(p.get("width") or 0.0)
        page_h = float(p.get("height") or 0.0)
        d = p.get("dict") or {}
        if not isinstance(d, dict):
            continue

        page_sizes[page_no] = (page_w, page_h)
        lines = _iter_lines_from_page_dict(d, page_index=page_no - 1, config=cfg)
        page_lines[page_no] = lines
        page_avg_h[page_no] = _page_avg_line_height(lines) if lines else 10.0

    drop_texts: set[str] = set()
    if cfg.drop_running_headers_footers and page_sizes and page_lines:
        margin_ratio = float(cfg.running_header_footer_margin_ratio)
        min_pages = int(cfg.running_header_footer_min_pages)
        min_len = int(cfg.running_header_footer_min_len)
        page_bands: Dict[int, _BodyBand] = {}
        if cfg.prefer_statistical_body_band:
            for page_no, lines in page_lines.items():
                w, h = page_sizes.get(page_no, (0.0, 0.0))
                if w <= 0 or h <= 0 or not lines:
                    continue
                page_bands[page_no] = _compute_body_band(lines, page_w=w, page_h=h, config=cfg)

        counts: Dict[str, set[int]] = {}
        for page_no, lines in page_lines.items():
            _w, h = page_sizes.get(page_no, (0.0, 0.0))
            if h <= 0:
                continue
            band = page_bands.get(page_no)
            margin = h * margin_ratio
            for l in lines:
                s = (l.text or "").strip()
                if len(s) < min_len:
                    continue
                if cfg.prefer_statistical_body_band and band and band.ok:
                    if not _is_outside_body_band(l, band=band, config=cfg, page_h=h):
                        continue
                else:
                    if not (l.y0 <= margin or l.y1 >= (h - margin)):
                        continue
                if re.match(cfg.page_number_re, s):
                    continue
                counts.setdefault(s, set()).add(page_no)
        for s, pageset in counts.items():
            if len(pageset) >= min_pages:
                drop_texts.add(s)

    for page_no, (page_w, page_h) in sorted(page_sizes.items(), key=lambda t: t[0]):
        lines = page_lines.get(page_no, [])
        page_paras.extend(
            _build_paragraphs_for_page(
                page_index=page_no - 1,
                page_w=page_w,
                page_h=page_h,
                lines=lines,
                config=cfg,
                drop_texts=drop_texts,
            )
        )

    page_paras = _cross_page_merge(page_paras, page_sizes=page_sizes, page_avg_line_height=page_avg_h, config=cfg)
    page_paras = _merge_math_placeholders_into_previous(page_paras, config=cfg)
    page_paras = _trim_after_references_heading(page_paras, config=cfg)
    if cfg.drop_heading_paragraphs:
        page_paras = [p for p in page_paras if not _is_heading_only_paragraph(p, config=cfg)]
    if cfg.drop_tiny_noise_paragraphs:
        page_paras = [p for p in page_paras if not _is_tiny_noise_paragraph(p, config=cfg)]

    out: List[Dict[str, Any]] = []
    for i, para in enumerate(page_paras):
        out.append(
            {
                "paragraph_id": i,
                "text": para.text,
                "pages": para.pages,
                "bboxes": para.bboxes_by_page(),
                "_anchor": para.anchor_bbox(),
                "is_caption": bool(para.is_caption),
                "_median_font_size": float(median([l.font_size for l in para.lines if l.font_size > 0]) or [0.0]),
            }
        )
    return out


def paragraphs_to_xml(paragraphs: Sequence[Dict[str, Any]]) -> str:
    """
    Convert paragraph output into a simple deterministic XML (NOT TEI).
    """

    def _xml_safe_text(s: str) -> str:
        out = []
        for ch in s:
            o = ord(ch)
            if o in (0x09, 0x0A, 0x0D) or o >= 0x20:
                out.append(ch)
            else:
                out.append(" ")
        return "".join(out)

    root = ET.Element("pymupdfParagraphs", {"version": "1"})
    for p in paragraphs:
        el_p = ET.SubElement(
            root,
            "paragraph",
            {"id": str(p.get("paragraph_id", "")), "is_caption": "1" if p.get("is_caption") else "0"},
        )
        el_text = ET.SubElement(el_p, "text")
        el_text.text = _xml_safe_text(str(p.get("text") or ""))
        el_pages = ET.SubElement(el_p, "pages")
        el_pages.text = ",".join(str(x) for x in (p.get("pages") or []))
        el_bboxes = ET.SubElement(el_p, "bboxes")
        for bb in (p.get("bboxes") or []):
            if not isinstance(bb, dict):
                continue
            ET.SubElement(
                el_bboxes,
                "bbox",
                {
                    "page": str(bb.get("page", "")),
                    "x0": str(bb.get("x0", "")),
                    "y0": str(bb.get("y0", "")),
                    "x1": str(bb.get("x1", "")),
                    "y1": str(bb.get("y1", "")),
                },
            )
    return ET.tostring(root, encoding="unicode")
