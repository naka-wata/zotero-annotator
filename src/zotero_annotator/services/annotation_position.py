from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from zotero_annotator.services.paragraphs import Paragraph, ParagraphCoord


@dataclass
class NotePosition:
    page_index: int
    x1: float
    y1: float
    x2: float
    y2: float
    annotation_position: Dict[str, object]
    annotation_sort_index: str


def _first_page_coords(coords: List[ParagraphCoord]) -> List[ParagraphCoord]:
    page = coords[0].page
    return [c for c in coords if c.page == page]


def build_note_position(
    paragraph: Paragraph,
    *,
    # Horizontal offset for left/right tuning (右へ + / 左へ - の左右補正)
    x_offset: float = -30.0,
    # Vertical offset for up/down tuning (上へ + / 下へ - の上下補正)
    y_offset: float = -45.0,
    icon_w: float = 12.0,
    icon_h: float = 12.0,
    fallback_page_w: float = 595.0,
    fallback_page_h: float = 842.0,
) -> NotePosition:
    # Use paragraph coords on its first page; otherwise fall back to a fixed point.
    # Convert Y from top-origin (GROBID) to bottom-origin (PDF/Zotero).
    page_index = max((paragraph.page or 1) - 1, 0)
    if paragraph.coords:
        same_page = _first_page_coords(paragraph.coords)
        x1 = min(c.x for c in same_page)
        topmost = min(same_page, key=lambda c: c.y)
        y1 = fallback_page_h - (topmost.y + topmost.h)
        page_index = max(same_page[0].page - 1, 0)
    else:
        x1 = fallback_page_w * 0.1
        y1 = fallback_page_h * 0.9

    # Keep original coordinates for sort index generation.
    raw_y1 = y1

    x1 += x_offset
    y1 += y_offset

    x2 = x1 + icon_w
    y2 = y1 + icon_h

    annotation_position: Dict[str, object] = {
        "pageIndex": page_index,
        "rects": [[x1, y1, x2, y2]],
        "rotation": 0,
    }
    annotation_sort_index = f"{page_index:05d}|000000|{int(round(raw_y1)):05d}"

    return NotePosition(
        page_index=page_index,
        x1=x1,
        y1=y1,
        x2=x2,
        y2=y2,
        annotation_position=annotation_position,
        annotation_sort_index=annotation_sort_index,
    )
