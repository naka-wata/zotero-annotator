from __future__ import annotations

import pytest

from zotero_annotator.services.pdf_pages import (
    estimate_dominant_pdf_page_size,
    get_page_size,
)


# ---------------------------------------------------------------------------
# get_page_size
# ---------------------------------------------------------------------------

class TestGetPageSize:
    # --- exact match ---

    def test_returns_exact_page(self) -> None:
        sizes = {0: (595.0, 842.0), 1: (400.0, 600.0)}
        assert get_page_size(sizes, 1) == (400.0, 600.0)

    def test_returns_page_0_when_exact(self) -> None:
        sizes = {0: (595.0, 842.0)}
        assert get_page_size(sizes, 0) == (595.0, 842.0)

    # --- fallback to page 0 ---

    def test_falls_back_to_page_0_when_index_missing(self) -> None:
        sizes = {0: (595.0, 842.0)}
        assert get_page_size(sizes, 5) == (595.0, 842.0)

    def test_falls_back_to_page_0_not_another_page(self) -> None:
        # page 1 exists but page 0 does not → should NOT fall back to page 1
        sizes = {1: (400.0, 600.0)}
        assert get_page_size(sizes, 3) is None

    def test_fallback_does_not_prefer_nearest_page(self) -> None:
        # page 2 is closer to page 3, but fallback must be page 0 only
        sizes = {0: (595.0, 842.0), 2: (400.0, 600.0)}
        assert get_page_size(sizes, 3) == (595.0, 842.0)

    def test_exact_match_takes_priority_over_fallback(self) -> None:
        sizes = {0: (595.0, 842.0), 3: (200.0, 300.0)}
        assert get_page_size(sizes, 3) == (200.0, 300.0)

    # --- failure cases ---

    def test_returns_none_when_empty_dict(self) -> None:
        assert get_page_size({}, 0) is None

    def test_returns_none_when_no_page_0_and_index_missing(self) -> None:
        sizes = {2: (595.0, 842.0), 3: (595.0, 842.0)}
        assert get_page_size(sizes, 5) is None

    def test_returns_none_for_negative_index_with_no_page_0(self) -> None:
        sizes = {1: (595.0, 842.0)}
        assert get_page_size(sizes, -1) is None

    def test_negative_index_falls_back_to_page_0_if_present(self) -> None:
        sizes = {0: (595.0, 842.0)}
        assert get_page_size(sizes, -1) == (595.0, 842.0)


# ---------------------------------------------------------------------------
# estimate_dominant_pdf_page_size
# ---------------------------------------------------------------------------

def _make_pdf_bytes(*box_lines: str) -> bytes:
    """Build minimal fake PDF raw bytes containing the given box definitions."""
    content = "\n".join(box_lines)
    return content.encode("latin-1")


class TestEstimateDominantPdfPageSize:
    def test_empty_bytes_returns_none(self) -> None:
        assert estimate_dominant_pdf_page_size(b"") is None

    def test_no_box_in_bytes_returns_none(self) -> None:
        assert estimate_dominant_pdf_page_size(b"no boxes here") is None

    def test_single_mediabox(self) -> None:
        raw = _make_pdf_bytes("/MediaBox [0 0 595 842]")
        result = estimate_dominant_pdf_page_size(raw)
        assert result == pytest.approx((595.0, 842.0))

    def test_single_cropbox(self) -> None:
        raw = _make_pdf_bytes("/CropBox [0 0 612 792]")
        result = estimate_dominant_pdf_page_size(raw)
        assert result == pytest.approx((612.0, 792.0))

    def test_cropbox_preferred_over_mediabox(self) -> None:
        # CropBox score=2, MediaBox score=1 — same count → CropBox wins on score
        raw = _make_pdf_bytes(
            "/MediaBox [0 0 595 842]",
            "/CropBox [0 0 400 600]",
        )
        result = estimate_dominant_pdf_page_size(raw)
        assert result == pytest.approx((400.0, 600.0))

    def test_dominant_size_by_frequency(self) -> None:
        # 595×842 appears 3 times, 400×600 appears once → 595×842 wins
        raw = _make_pdf_bytes(
            "/MediaBox [0 0 595 842]",
            "/MediaBox [0 0 595 842]",
            "/MediaBox [0 0 595 842]",
            "/MediaBox [0 0 400 600]",
        )
        result = estimate_dominant_pdf_page_size(raw)
        assert result == pytest.approx((595.0, 842.0))

    def test_non_zero_origin_box(self) -> None:
        # x0=10, y0=20, x1=610, y1=820 → w=600, h=800
        raw = _make_pdf_bytes("/MediaBox [10 20 610 820]")
        result = estimate_dominant_pdf_page_size(raw)
        assert result == pytest.approx((600.0, 800.0))

    def test_zero_or_negative_dimension_ignored(self) -> None:
        # w = 0 - 0 = 0 → ignored; valid box follows
        raw = _make_pdf_bytes(
            "/MediaBox [0 0 0 0]",
            "/MediaBox [0 0 595 842]",
        )
        result = estimate_dominant_pdf_page_size(raw)
        assert result == pytest.approx((595.0, 842.0))

    def test_all_invalid_boxes_returns_none(self) -> None:
        raw = _make_pdf_bytes("/MediaBox [0 0 0 0]", "/CropBox [100 100 50 50]")
        assert estimate_dominant_pdf_page_size(raw) is None

    def test_float_values_in_box(self) -> None:
        raw = _make_pdf_bytes("/MediaBox [0 0 595.28 841.89]")
        result = estimate_dominant_pdf_page_size(raw)
        assert result == pytest.approx((595.28, 841.89), rel=1e-3)

    def test_cropbox_tie_broken_by_score_over_mediabox(self) -> None:
        # Both appear once but CropBox has score 2 vs MediaBox score 1
        raw = _make_pdf_bytes(
            "/MediaBox [0 0 100 200]",
            "/CropBox [0 0 300 400]",
        )
        result = estimate_dominant_pdf_page_size(raw)
        assert result == pytest.approx((300.0, 400.0))
