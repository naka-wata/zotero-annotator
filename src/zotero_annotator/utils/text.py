from __future__ import annotations

import dataclasses
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from zotero_annotator.services.paragraphs import Paragraph

_LEADING_CONTINUATION_RE = re.compile(r"^([a-z]|[,\)\]])")
_SENTENCE_END_RE = re.compile(r'[.!?][\"\'\)\]]*\s*$')


def normalize_text(text: str) -> str:
    return " ".join((text or "").split()).strip()


def merge_leading_continuations(
    paragraphs: list[Paragraph],
) -> list[Paragraph]:
    """
    Merge paragraphs that look like a continuation of the previous paragraph.

    Trigger:
      - current paragraph starts with a lowercase letter, or one of: , ) ]
    Guard:
      - do NOT merge if previous paragraph ends with a clear sentence terminator: . ? !
      - do NOT merge across known different pages
    """
    if not paragraphs:
        return paragraphs

    out: list[Paragraph] = []
    for p in paragraphs:
        if not out:
            out.append(p)
            continue

        prev = out[-1]
        cur_text = (p.text or "").lstrip()
        prev_text = (prev.text or "").rstrip()

        # Allow merge within the same page, and also across a page break if the
        # previous paragraph ends on the page right before the current starts.
        can_merge_across_pages = True
        if prev.coords and p.coords:
            prev_end_page = max(c.page for c in prev.coords)
            cur_start_page = min(c.page for c in p.coords)
            if not (
                cur_start_page == prev_end_page
                or cur_start_page == prev_end_page + 1
            ):
                can_merge_across_pages = False
        else:
            # Fallback to coarse page attribute when coords are missing.
            if prev.page is not None and p.page is not None and prev.page != p.page:
                can_merge_across_pages = False

        should_try_merge = bool(_LEADING_CONTINUATION_RE.match(cur_text))
        prev_ends_sentence = bool(_SENTENCE_END_RE.search(prev_text))

        if can_merge_across_pages and should_try_merge and not prev_ends_sentence:
            merged_text = normalize_text(f"{prev_text} {cur_text}")
            merged_coords = [*prev.coords, *p.coords]
            merged_dedup_hashes = [
                *(prev.dedup_hashes or [prev.hash]),
                *(p.dedup_hashes or [p.hash]),
            ]
            merged_hash = merged_dedup_hashes[0] if merged_dedup_hashes else prev.hash
            out[-1] = dataclasses.replace(
                prev,
                text=merged_text,
                hash=merged_hash,
                dedup_hashes=merged_dedup_hashes,
                coords=merged_coords,
                page=prev.page if prev.page is not None else p.page,
            )
            continue

        out.append(p)

    return out
