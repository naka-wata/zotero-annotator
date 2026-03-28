from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha1
from statistics import median
from typing import List, Literal, Optional, Union

from defusedxml import ElementTree as ET

from zotero_annotator.utils.text import merge_leading_continuations, normalize_text


# Data class for paragraph coordinates (段落の座標を表すデータクラス)
@dataclass
class ParagraphCoord:
    page: int
    x: float
    y: float
    w: float
    h: float


# Data class for paragraph content (段落の本文を表すデータクラス)
@dataclass
class Paragraph:
    text: str
    hash: str
    dedup_hashes: List[str]
    coords: List[ParagraphCoord]
    page: Optional[int]


@dataclass
class CoordHThreshold:
    threshold: float
    method: Literal["disabled", "fixed", "auto_q75_ratio"]
    samples: int
    q75: Optional[float]
    ratio: Optional[float]


@dataclass
class _ParagraphEntry:
    legacy_text: str
    display_text: str
    coords: List[ParagraphCoord]
    page: Optional[int]

_CAPTION_START_RE = re.compile(r"^[^A-Za-z0-9]*(Figure|Fig\.|Table|Tab\.)\s*\d+\s*:", re.IGNORECASE)
_CAPTION_BODY_SPLIT_RE = re.compile(r"\.\s+([a-z])")


def _strip_or_drop_caption(text: str) -> Optional[str]:
    """
    Skip figure/table captions as notes.

    - If the paragraph is a pure caption (starts with 'Figure N:' / 'Table N:'), drop it.
    - If it is a mixed paragraph where a caption is followed by prose (rare, but happens with PDF layout),
      keep the prose tail by splitting at the first '. <lowercase...>' boundary.
    """
    s = (text or "").strip()
    if not s:
        return None
    if not _CAPTION_START_RE.match(s):
        return s

    m = _CAPTION_BODY_SPLIT_RE.search(s)
    if not m:
        return None

    tail = s[m.start(1) :].strip()
    return tail or None



# SHA1 hash computation function (SHA1ハッシュ計算関数(重複判定タグ))
def _sha1(text: str) -> str:
    return sha1(text.encode("utf-8")).hexdigest()

# Extract local name from XML tag (XMLタグからローカル名を抽出)
def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag

# Find coords attribute in an element (要素からcoords属性を探す)
def _find_coords_attr(elem: ET.Element) -> Optional[str]:
    for key, value in elem.attrib.items():
        if _local_name(key) == "coords":
            return value
    return None

# Parse coords string "page,x,y,w,h;..." into ParagraphCoord list (座標文字列 "page,x,y,w,h;..." を ParagraphCoord のリストに変換する)
def _parse_coords(coords_str: str) -> List[ParagraphCoord]:
    coords: List[ParagraphCoord] = []
    if not coords_str:
        return coords
    for part in coords_str.split(";"):
        bits = [b.strip() for b in part.split(",") if b.strip() != ""]
        if len(bits) != 5:
            continue
        try:
            page = int(float(bits[0]))
            x = float(bits[1])
            y = float(bits[2])
            w = float(bits[3])
            h = float(bits[4])
        except ValueError:
            continue
        coords.append(ParagraphCoord(page=page, x=x, y=y, w=w, h=h))
    return coords


def _render_p_text(p_elem: ET.Element, *, formula_placeholder: str) -> str:
    # Render paragraph text with placeholders for disruptive elements.
    # (数式などをプレースホルダ化して段落テキストを安定化)

    def render(elem: ET.Element) -> str:
        out_parts: List[str] = []
        if elem.text:
            out_parts.append(elem.text)

        for child in list(elem):
            name = _local_name(child.tag)
            if name == "formula":
                out_parts.append(
                    _render_formula_text_or_token(
                        child,
                        formula_placeholder=formula_placeholder,
                        max_formula_chars=200,
                    )
                )
            elif name == "lb":
                out_parts.append(" ")
            else:
                out_parts.append(render(child))

            if child.tail:
                out_parts.append(child.tail)

        return "".join(out_parts)

    return render(p_elem)


def _render_formula_token(formula_elem: ET.Element, *, formula_placeholder: str) -> str:
    # Render a standalone <formula> element into a token (or short text when unlabelled).
    # (単独<formula>を段落ストリームに埋め込むためのトークンに変換)
    return _render_formula_text_or_token(
        formula_elem,
        formula_placeholder=formula_placeholder,
        max_formula_chars=200,
    )


def _render_formula_text_or_token(
    formula_elem: ET.Element,
    *,
    formula_placeholder: str,
    max_formula_chars: int,
) -> str:
    # If the formula has an explicit <label>, keep it as a compact token.
    # If there is no label, try to embed the formula text directly (short only).
    label_text = ""
    for g in formula_elem.iter():
        if _local_name(g.tag) == "label":
            label_text = normalize_text("".join(g.itertext()))
            break

    if label_text:
        return f"{formula_placeholder} {label_text}"

    raw = normalize_text("".join(formula_elem.itertext()))
    if not raw:
        return formula_placeholder
    if max_formula_chars > 0 and len(raw) > max_formula_chars:
        return formula_placeholder
    return raw


def _iter_p_with_prefix_tokens(
    root: ET.Element, *, formula_placeholder: str
) -> List[tuple[ET.Element, List[str]]]:
    """
    Iterate <p> elements in reading order, attaching standalone <formula> tokens
    that appear immediately before each <p> within the same <div>.

    This preserves the stable hashing of <p> while allowing merge heuristics to
    keep math-split paragraphs together.
    """
    rows: List[tuple[ET.Element, List[str]]] = []
    found_div = False

    for div in root.iter():
        if _local_name(div.tag) != "div":
            continue
        found_div = True
        pending: List[str] = []
        for child in list(div):
            name = _local_name(child.tag)
            if name == "formula":
                pending.append(_render_formula_token(child, formula_placeholder=formula_placeholder))
                continue
            if name == "p":
                rows.append((child, pending))
                pending = []
                continue
            # Other elements: keep pending tokens until we hit the next <p>.
        # If a <div> ends with formulas and no following <p>, attach to the last <p>.
        if pending and rows:
            p_elem, tokens = rows[-1]
            rows[-1] = (p_elem, tokens + pending)

    if found_div:
        return rows

    # Fallback: plain <p> iteration without context.
    for p in root.iter():
        if _local_name(p.tag) == "p":
            rows.append((p, []))
    return rows


def _strip_trailing_punct(text: str) -> str:
    t = text.strip()
    while t and t[-1] in (",", ";", ":", "."):
        t = t[:-1].rstrip()
    return t


def _strip_leading_formula_tokens(text: str, *, formula_placeholder: str) -> str:
    """
    Strip leading formula placeholder tokens like:
    - "[MATH]"
    - "[MATH] (2)"
    possibly repeated.
    """
    t = text.strip()
    while t.startswith(formula_placeholder):
        t = t[len(formula_placeholder) :].lstrip()
        if t.startswith("("):
            end = t.find(")")
            if 0 < end <= 8:
                t = t[end + 1 :].lstrip()
    return t


def _format_math_newlines(text: str, *, formula_placeholder: str) -> str:
    """
    Put [MATH] (n) tokens on their own line.
    This runs at the end of extraction so merge heuristics stay stable.
    """
    if not text or not formula_placeholder:
        return text

    token_re = re.compile(rf"{re.escape(formula_placeholder)}(?:\\s*\\(\\d+\\))?")

    def repl(m: re.Match[str]) -> str:
        tok = m.group(0).strip()
        return f"\n{tok}\n"

    t = token_re.sub(repl, text)
    # Trim spaces around newlines and collapse multiple newlines to a single newline.
    t = re.sub(r"[ \t]*\n[ \t]*", "\n", t)
    t = re.sub(r"\n{2,}", "\n", t)
    return t.strip()


def _is_connector_paragraph_v2(
    text: str,
    *,
    connector_max_chars: int,
    formula_placeholder: str,
) -> Optional[str]:
    t0 = _strip_trailing_punct(normalize_text(text))
    t = _strip_leading_formula_tokens(t0, formula_placeholder=formula_placeholder)
    t = _strip_trailing_punct(t)
    if not t:
        return None
    if len(t) > connector_max_chars:
        return None
    if t in ("where", "Where"):
        return t
    return None


def _should_prefix_where_capitalized(prev_text: str, next_text: str, *, formula_placeholder: str) -> bool:
    prev_t = prev_text.strip()
    next_t = next_text.strip()
    if not prev_t or not next_t:
        return False

    prev_sentence_end = prev_t.endswith((".", "!", "?"))
    prev_continuation_end = prev_t.endswith((",", ":", ";", "="))
    if prev_sentence_end and not prev_continuation_end:
        return False

    if next_t.startswith(formula_placeholder):
        return True

    ch0 = next_t[:1]
    if not ch0:
        return False
    if ch0.islower():
        return True
    if ch0 in ("y", "x", "Q", "V", "L", "R", "θ", "γ", "("):
        return True
    if ch0.isdigit():
        return True
    return False


def _merge_connector_entries(
    entries: List[_ParagraphEntry],
    *,
    connector_max_chars: int,
    formula_placeholder: str,
) -> List[_ParagraphEntry]:
    if not entries:
        return entries

    out: List[_ParagraphEntry] = []
    i = 0
    while i < len(entries):
        cur = entries[i]
        token = _is_connector_paragraph_v2(
            cur.display_text,
            connector_max_chars=connector_max_chars,
            formula_placeholder=formula_placeholder,
        )
        if token is None:
            out.append(cur)
            i += 1
            continue

        if i + 1 < len(entries):
            nxt = entries[i + 1]
            if token == "where":
                nxt.display_text = normalize_text(f"{cur.display_text} {nxt.display_text}")
                i += 1
                continue
            if token == "Where":
                prev_text = out[-1].display_text if out else ""
                if _should_prefix_where_capitalized(
                    prev_text,
                    nxt.display_text,
                    formula_placeholder=formula_placeholder,
                ):
                    nxt.display_text = normalize_text(f"{cur.display_text} {nxt.display_text}")
                    i += 1
                    continue

        out.append(cur)
        i += 1

    return out


def _filter_algorithm_entries(
    entries: List[_ParagraphEntry],
    *,
    formula_placeholder: str,
    enabled: bool,
) -> List[_ParagraphEntry]:
    if not enabled or not entries:
        return entries

    # Be tolerant to leading invisible chars and punctuation inserted by upstream tools.
    algo_start_re = re.compile(r"^[^A-Za-z0-9]*Algorithm\s*\d+\b", re.IGNORECASE)
    algo_keywords = (
        "initialize",
        "initialise",
        "for ",
        " do",
        "end",
        "set ",
        "store",
        "sample",
        "perform",
        "execute",
        "observe",
        "with probability",
        "otherwise",
        "replay memory",
        "minibatch",
    )
    resume_markers = (
        "First,",
        "Second,",
        "Third,",
        "In practice",
        "Note that",
        "However",
        "We note that",
    )

    def is_pseudocode_like(text: str) -> bool:
        t = normalize_text(text)
        if not t:
            return False
        lower = t.lower()
        kw = sum(1 for k in algo_keywords if k in lower)
        periods = lower.count(".")
        if algo_start_re.match(t):
            return True
        if kw >= 2 and periods == 0:
            return True
        if kw >= 3 and periods <= 1:
            return True
        return False

    def split_after_resume(text: str) -> Optional[str]:
        for m in resume_markers:
            idx = text.find(m)
            if idx >= 0:
                return text[idx:]
        return None

    out: List[_ParagraphEntry] = []
    in_algo = False

    for e in entries:
        t = e.display_text
        t_for_detect = _strip_leading_formula_tokens(t, formula_placeholder=formula_placeholder)
        t_for_detect = t_for_detect.lstrip("\ufeff\u200b\u200e\u200f")

        if not in_algo:
            if algo_start_re.match(t_for_detect):
                in_algo = True
                continue
            out.append(e)
            continue

        tail = split_after_resume(t_for_detect)
        if tail:
            out.append(
                _ParagraphEntry(
                    legacy_text=e.legacy_text,
                    display_text=normalize_text(tail),
                    coords=e.coords,
                    page=e.page,
                )
            )
            in_algo = False
            continue

        if is_pseudocode_like(t_for_detect):
            continue

        if t_for_detect.count(".") >= 1:
            in_algo = False
            out.append(e)
            continue

        continue

    return out


def _strip_plot_axis_prefix(text: str) -> str:
    """
    Strip numeric-heavy plot/axis label noise that appears before "Figure N:".
    Conservative: only strips when a Figure caption marker is present.
    """
    t = text.strip()
    if not t:
        return t

    m = re.search(r"\bFigure\s+\d+\s*:", t)
    if not m:
        return t

    prefix = t[: m.start()].strip()
    rest = t[m.start() :].strip()
    if not prefix:
        return t

    tokens = prefix.split()
    if len(tokens) < 20:
        return t

    digit_chars = sum(ch.isdigit() for ch in prefix)
    alpha_chars = sum(ch.isalpha() for ch in prefix)
    total_chars = max(1, len(prefix))
    digit_frac = digit_chars / total_chars
    alpha_frac = alpha_chars / total_chars

    numeric_tokens = 0
    for tok in tokens:
        s = tok.strip("()[]{}.,;:%")
        if not s:
            continue
        if all(c.isdigit() for c in s):
            numeric_tokens += 1
            continue
        if re.fullmatch(r"\d+(e\d+)?", s, flags=re.IGNORECASE):
            numeric_tokens += 1

    lower = prefix.lower()
    kw_hits = sum(
        1
        for k in (
            "training",
            "epoch",
            "step",
            "reward",
            "score",
            "normalized",
            "mean",
            "max",
            "min",
        )
        if k in lower
    )
    periods = prefix.count(".")

    looks_like_axis = (
        numeric_tokens >= 10
        and periods <= 1
        and (digit_frac >= 0.15 or alpha_frac <= 0.45 or kw_hits >= 2)
    )
    if not looks_like_axis:
        return t

    return normalize_text(rest)


def _should_merge(
    prev_text: str,
    next_text: str,
    *,
    formula_placeholder: str,
    short_threshold: int = 30,
) -> bool:
    prev_text = prev_text.strip()
    next_text = next_text.strip()
    if not prev_text or not next_text:
        return True

    # Strong signal: paragraph ended mid-clause / mid-equation.
    # (段落が句読点ではなく「続き」を示す記号で終わっている場合は結合)
    if prev_text[-1] in (",", "=", "(", "[", "{"):
        return True

    # If either side is just a formula placeholder, merge.
    if prev_text == formula_placeholder or next_text == formula_placeholder:
        return True

    # If one side is extremely short, it's likely a split.
    if len(prev_text) <= short_threshold or len(next_text) <= short_threshold:
        return True

    # If the previous paragraph doesn't look like it ends a sentence, it may be a split.
    # Merge when the next looks like a continuation (math/punctuation/closing/opening tokens).
    if prev_text[-1] not in (".", "!", "?", ";"):
        if next_text.startswith(formula_placeholder):
            return True
        if next_text[:1] in (")", "]", "}", ",", ".", ";", ":", "=", "+", "-", "×", "·"):
            return True
        if next_text[:1].islower():
            return True

    # Common continuation markers for math-split paragraphs.
    if next_text[:1] in (")", "]", ","):
        return True

    return False


def _merge_paragraphs(paragraphs: List[Paragraph], *, formula_placeholder: str) -> List[Paragraph]:
    # Merge adjacent paragraph fragments conservatively (保守的に隣接段落を結合する)
    if not paragraphs:
        return paragraphs

    def can_merge_pages(a: Paragraph, b: Paragraph) -> bool:
        # Prefer not to merge across pages when both pages are known.
        if a.page is not None and b.page is not None:
            return a.page == b.page
        # If either page is unknown (e.g., missing coords), allow merge.
        return True

    merged: List[Paragraph] = []
    current = paragraphs[0]

    for nxt in paragraphs[1:]:
        if can_merge_pages(current, nxt):
            if _should_merge(current.text, nxt.text, formula_placeholder=formula_placeholder):
                combined_text = normalize_text(f"{current.text} {nxt.text}")
                combined_coords = list(current.coords) + list(nxt.coords)
                combined_hashes = list(current.dedup_hashes) + [
                    h for h in nxt.dedup_hashes if h not in current.dedup_hashes
                ]
                combined_page = combined_coords[0].page if combined_coords else (current.page or nxt.page)
                # Keep legacy-hash stability: hash is based on concatenated legacy hashes.
                # (hashは互換性よりも内部一意性用。dedupはdedup_hashesで行う)
                current = Paragraph(
                    text=combined_text,
                    hash=_sha1("|".join(combined_hashes)),
                    dedup_hashes=combined_hashes,
                    coords=combined_coords,
                    page=combined_page,
                )
                continue

        merged.append(current)
        current = nxt

    merged.append(current)
    return merged


def _median_coord_h(coords: List[ParagraphCoord]) -> Optional[float]:
    if not coords:
        return None
    try:
        return float(median([c.h for c in coords]))
    except Exception:
        return None


def _percentile(values: List[float], q: float) -> Optional[float]:
    if not values:
        return None
    if q <= 0:
        return min(values)
    if q >= 1:
        return max(values)
    xs = sorted(values)
    idx = int(round((len(xs) - 1) * q))
    return xs[max(0, min(idx, len(xs) - 1))]


def estimate_coord_h_threshold(
    tei_xml: str,
    *,
    min_chars: int,
    formula_placeholder: str,
    min_median_coord_h: Union[float, Literal["auto"]],
    min_median_coord_h_auto_ratio: float,
) -> CoordHThreshold:
    """
    Estimate coordinate-height threshold for filtering non-body text.

    - fixed: user-provided numeric threshold
    - auto: q75(median(h) per paragraph) × ratio
    - disabled: 0 or missing samples
    """
    if min_median_coord_h == "auto":
        try:
            root = ET.fromstring(tei_xml)
        except ET.ParseError as exc:
            raise ValueError("Invalid TEI XML") from exc
        return _estimate_coord_h_threshold_from_root(
            root,
            min_chars=min_chars,
            formula_placeholder=formula_placeholder,
            min_median_coord_h=min_median_coord_h,
            min_median_coord_h_auto_ratio=min_median_coord_h_auto_ratio,
        )

    fixed = float(min_median_coord_h)
    if fixed <= 0:
        return CoordHThreshold(threshold=0.0, method="disabled", samples=0, q75=None, ratio=None)
    return CoordHThreshold(threshold=fixed, method="fixed", samples=0, q75=None, ratio=None)


def _estimate_coord_h_threshold_from_root(
    root: ET.Element,
    *,
    min_chars: int,
    formula_placeholder: str,
    min_median_coord_h: Union[float, Literal["auto"]],
    min_median_coord_h_auto_ratio: float,
) -> CoordHThreshold:
    if min_median_coord_h != "auto":
        fixed = float(min_median_coord_h)
        if fixed <= 0:
            return CoordHThreshold(threshold=0.0, method="disabled", samples=0, q75=None, ratio=None)
        return CoordHThreshold(threshold=fixed, method="fixed", samples=0, q75=None, ratio=None)

    mhs: List[float] = []
    for e in root.iter():
        if _local_name(e.tag) != "p":
            continue
        coords_str = _find_coords_attr(e)
        if not coords_str:
            continue
        coords = _parse_coords(coords_str)
        mh = _median_coord_h(coords)
        if mh is None:
            continue

        display_text = normalize_text(_render_p_text(e, formula_placeholder=formula_placeholder))
        if len(display_text) < min_chars:
            continue

        mhs.append(mh)

    q75 = _percentile(mhs, 0.75)
    if q75 is None or q75 <= 0:
        return CoordHThreshold(
            threshold=0.0,
            method="disabled",
            samples=len(mhs),
            q75=q75,
            ratio=float(min_median_coord_h_auto_ratio),
        )

    return CoordHThreshold(
        threshold=q75 * float(min_median_coord_h_auto_ratio),
        method="auto_q75_ratio",
        samples=len(mhs),
        q75=q75,
        ratio=float(min_median_coord_h_auto_ratio),
    )


# Extract paragraphs and optional coordinates from TEI XML (TEIから段落と座標を抽出)
def extract_paragraphs(
    tei_xml: str,
    min_chars: int,
    max_chars: int,
    *,
    merge_splits: bool = False,
    formula_placeholder: str = "[MATH]",
    min_median_coord_h: Union[float, Literal["auto"]] = 0.0,
    min_median_coord_h_auto_ratio: float = 0.7,
    connector_max_chars: int = 20,
    math_newlines: bool = False,
    skip_algorithms: bool = False,
    strip_plot_axis_prefix: bool = False,
    skip_captions: bool = False,
) -> List[Paragraph]:
    try:
        root = ET.fromstring(tei_xml)
    except ET.ParseError as exc:
        raise ValueError("Invalid TEI XML") from exc
    coord_h = _estimate_coord_h_threshold_from_root(
        root,
        min_chars=min_chars,
        formula_placeholder=formula_placeholder,
        min_median_coord_h=min_median_coord_h,
        min_median_coord_h_auto_ratio=min_median_coord_h_auto_ratio,
    )
    coord_h_threshold = coord_h.threshold

    entries: List[_ParagraphEntry] = []
    for elem, prefix_tokens in _iter_p_with_prefix_tokens(root, formula_placeholder=formula_placeholder):
        legacy_text = normalize_text("".join(elem.itertext()))
        display_text = normalize_text(_render_p_text(elem, formula_placeholder=formula_placeholder))
        if prefix_tokens:
            display_text = normalize_text(" ".join([*prefix_tokens, display_text]))
        coords_str = _find_coords_attr(elem)
        coords = _parse_coords(coords_str) if coords_str else []
        page = coords[0].page if coords else None

        if not display_text:
            continue

        if coord_h_threshold > 0 and coords:
            mh = _median_coord_h(coords)
            if mh is not None and mh < coord_h_threshold:
                continue

        entries.append(
            _ParagraphEntry(
                legacy_text=legacy_text,
                display_text=display_text,
                coords=coords,
                page=page,
            )
        )

    entries = _merge_connector_entries(
        entries,
        connector_max_chars=connector_max_chars,
        formula_placeholder=formula_placeholder,
    )
    entries = _filter_algorithm_entries(
        entries,
        formula_placeholder=formula_placeholder,
        enabled=skip_algorithms,
    )
    if strip_plot_axis_prefix:
        entries = [
            _ParagraphEntry(
                legacy_text=e.legacy_text,
                display_text=_strip_plot_axis_prefix(e.display_text),
                coords=e.coords,
                page=e.page,
            )
            for e in entries
            if e.display_text
        ]

    if skip_captions:
        kept: List[_ParagraphEntry] = []
        for e in entries:
            cleaned = _strip_or_drop_caption(e.display_text)
            if not cleaned:
                continue
            kept.append(
                _ParagraphEntry(
                    legacy_text=e.legacy_text,
                    display_text=cleaned,
                    coords=e.coords,
                    page=e.page,
                )
            )
        entries = kept

    paragraphs_raw: List[Paragraph] = []
    for e in entries:
        text = e.display_text
        if not text:
            continue
        dedup_hash = _sha1(e.legacy_text if e.legacy_text else text)
        paragraphs_raw.append(
            Paragraph(
                text=text,
                hash=dedup_hash,
                dedup_hashes=[dedup_hash],
                coords=e.coords,
                page=e.page,
            )
        )

    paragraphs_raw = merge_leading_continuations(paragraphs_raw)

    paragraphs: List[Paragraph] = []
    for p in paragraphs_raw:
        if len(p.text) < min_chars:
            continue
        if len(p.text) > max_chars:
            # For now keep the full text; downstream can split if needed.
            pass
        paragraphs.append(p)

    out = _merge_paragraphs(paragraphs, formula_placeholder=formula_placeholder) if merge_splits else paragraphs
    if math_newlines:
        out = [
            Paragraph(
                text=_format_math_newlines(p.text, formula_placeholder=formula_placeholder),
                hash=p.hash,
                dedup_hashes=p.dedup_hashes,
                coords=p.coords,
                page=p.page,
            )
            for p in out
        ]
    return out
