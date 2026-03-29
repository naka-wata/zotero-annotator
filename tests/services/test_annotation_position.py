from __future__ import annotations

from zotero_annotator.services.annotation_position import (
    NotePosition,
    _first_page_coords,
    build_note_position,
)
from zotero_annotator.services.paragraphs import Paragraph, ParagraphCoord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def coord(page: int, x: float, y: float, w: float = 100.0, h: float = 10.0) -> ParagraphCoord:
    return ParagraphCoord(page=page, x=x, y=y, w=w, h=h)


def make_para(
    text: str = "sample",
    hash: str = "h",
    page: int | None = None,
    coords: list[ParagraphCoord] | None = None,
) -> Paragraph:
    return Paragraph(
        text=text,
        hash=hash,
        dedup_hashes=[hash],
        coords=coords or [],
        page=page,
    )


# ---------------------------------------------------------------------------
# _first_page_coords
# ---------------------------------------------------------------------------

class TestFirstPageCoords:
    def test_single_page_returns_all(self) -> None:
        coords = [coord(1, 0, 0), coord(1, 50, 20)]
        assert _first_page_coords(coords) == coords

    def test_multi_page_returns_first_page_only(self) -> None:
        c1 = coord(1, 0, 0)
        c2 = coord(1, 50, 20)
        c3 = coord(2, 0, 0)
        result = _first_page_coords([c1, c2, c3])
        assert result == [c1, c2]

    def test_all_different_pages_returns_first(self) -> None:
        c1 = coord(3, 10, 10)
        c2 = coord(4, 20, 20)
        result = _first_page_coords([c1, c2])
        assert result == [c1]


# ---------------------------------------------------------------------------
# build_note_position — coords あり
# ---------------------------------------------------------------------------

class TestBuildNotePositionWithCoords:
    def test_page_index_derived_from_coords(self) -> None:
        # page=2 in coord → page_index should be 1 (0-based)
        p = make_para(coords=[coord(2, 100.0, 50.0, h=10.0)])
        result = build_note_position(p)
        assert result.page_index == 1

    def test_x1_uses_leftmost_coord_plus_offset(self) -> None:
        c1 = coord(1, 80.0, 50.0)
        c2 = coord(1, 120.0, 50.0)
        p = make_para(coords=[c1, c2])
        result = build_note_position(p, x_offset=0.0, y_offset=0.0)
        assert result.x1 == pytest.approx(80.0)

    def test_x_offset_applied(self) -> None:
        p = make_para(coords=[coord(1, 100.0, 50.0)])
        result = build_note_position(p, x_offset=-30.0, y_offset=0.0)
        assert result.x1 == pytest.approx(70.0)

    def test_y1_converted_from_top_origin_to_bottom_origin(self) -> None:
        # page_h=842, coord y=100, h=10 → y1 = 842 - (100+10) = 732
        page_sizes = {0: (595.0, 842.0)}
        p = make_para(coords=[coord(1, 0.0, 100.0, h=10.0)])
        result = build_note_position(p, page_sizes=page_sizes, y_offset=0.0, x_offset=0.0)
        assert result.y1 == pytest.approx(732.0)

    def test_y_offset_applied(self) -> None:
        page_sizes = {0: (595.0, 842.0)}
        p = make_para(coords=[coord(1, 0.0, 100.0, h=10.0)])
        result = build_note_position(p, page_sizes=page_sizes, y_offset=5.0, x_offset=0.0)
        # 842 - (100+10) + 5 = 737
        assert result.y1 == pytest.approx(737.0)

    def test_x2_y2_icon_size(self) -> None:
        p = make_para(coords=[coord(1, 100.0, 50.0)])
        result = build_note_position(p, x_offset=0.0, y_offset=0.0, icon_w=12.0, icon_h=12.0)
        assert result.x2 == pytest.approx(result.x1 + 12.0)
        assert result.y2 == pytest.approx(result.y1 + 12.0)

    def test_annotation_position_structure(self) -> None:
        p = make_para(coords=[coord(1, 50.0, 40.0)])
        result = build_note_position(p)
        pos = result.annotation_position
        assert pos["pageIndex"] == result.page_index
        assert pos["rotation"] == 0
        rects = pos["rects"]
        assert len(rects) == 1
        assert rects[0] == [result.x1, result.y1, result.x2, result.y2]

    def test_sort_index_format(self) -> None:
        page_sizes = {0: (595.0, 842.0)}
        # page_index=0, raw_y1 = 842 - (50+10) = 782
        p = make_para(coords=[coord(1, 0.0, 50.0, h=10.0)])
        result = build_note_position(p, page_sizes=page_sizes, y_offset=0.0, x_offset=0.0)
        assert result.annotation_sort_index == "00000|000000|00782"

    def test_page_size_from_page_sizes_dict(self) -> None:
        page_sizes = {0: (400.0, 600.0)}
        p = make_para(coords=[coord(1, 0.0, 100.0, h=10.0)])
        result = build_note_position(p, page_sizes=page_sizes, y_offset=0.0, x_offset=0.0)
        # y1 = 600 - (100+10) = 490
        assert result.y1 == pytest.approx(490.0)

    def test_fallback_page_size_used_when_no_page_sizes(self) -> None:
        p = make_para(coords=[coord(1, 0.0, 100.0, h=10.0)])
        result = build_note_position(
            p, page_sizes=None, y_offset=0.0, x_offset=0.0,
            fallback_page_h=500.0,
        )
        # y1 = 500 - (100+10) = 390
        assert result.y1 == pytest.approx(390.0)

    def test_multi_page_coords_uses_first_page_only(self) -> None:
        c_p1 = coord(1, 50.0, 30.0, h=10.0)
        c_p2 = coord(2, 10.0, 50.0, h=10.0)
        p = make_para(coords=[c_p1, c_p2])
        result = build_note_position(p, x_offset=0.0, y_offset=0.0)
        # x1 should come from page 1 coord (50.0), not page 2 (10.0)
        assert result.x1 == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# build_note_position — coords なし（フォールバック）
# ---------------------------------------------------------------------------

class TestBuildNotePositionWithoutCoords:
    def test_fallback_x1_is_10_percent_of_page_width(self) -> None:
        p = make_para(page=1)
        result = build_note_position(p, x_offset=0.0, y_offset=0.0, fallback_page_w=500.0)
        assert result.x1 == pytest.approx(50.0)  # 500 * 0.1

    def test_fallback_y1_is_90_percent_of_page_height(self) -> None:
        p = make_para(page=1)
        result = build_note_position(p, x_offset=0.0, y_offset=0.0, fallback_page_h=1000.0)
        assert result.y1 == pytest.approx(900.0)  # 1000 * 0.9

    def test_page_sizes_used_for_fallback(self) -> None:
        page_sizes = {0: (400.0, 800.0)}
        p = make_para(page=1)
        result = build_note_position(p, page_sizes=page_sizes, x_offset=0.0, y_offset=0.0)
        assert result.x1 == pytest.approx(40.0)   # 400 * 0.1
        assert result.y1 == pytest.approx(720.0)  # 800 * 0.9

    def test_page_index_from_paragraph_page(self) -> None:
        p = make_para(page=3)
        result = build_note_position(p)
        assert result.page_index == 2  # page 3 → index 2

    def test_page_none_defaults_to_index_0(self) -> None:
        p = make_para(page=None)
        result = build_note_position(p)
        assert result.page_index == 0

    def test_sort_index_format_without_coords(self) -> None:
        p = make_para(page=1)
        result = build_note_position(p, x_offset=0.0, y_offset=0.0, fallback_page_h=1000.0)
        # raw_y1 = 1000 * 0.9 = 900, page_index=0
        assert result.annotation_sort_index == "00000|000000|00900"


# ---------------------------------------------------------------------------
# boundary / edge cases
# ---------------------------------------------------------------------------

class TestBuildNotePositionEdgeCases:
    def test_page_1_coord_gives_page_index_0(self) -> None:
        p = make_para(coords=[coord(1, 0.0, 0.0)])
        result = build_note_position(p)
        assert result.page_index == 0

    def test_coord_y_zero_h_zero(self) -> None:
        # Should not raise; y1 = page_h - 0
        p = make_para(coords=[coord(1, 0.0, 0.0, h=0.0)])
        result = build_note_position(p, fallback_page_h=842.0, y_offset=0.0, x_offset=0.0)
        assert result.y1 == pytest.approx(842.0)

    def test_icon_size_zero(self) -> None:
        p = make_para(coords=[coord(1, 50.0, 50.0)])
        result = build_note_position(p, icon_w=0.0, icon_h=0.0)
        assert result.x2 == pytest.approx(result.x1)
        assert result.y2 == pytest.approx(result.y1)

    def test_large_page_index_in_sort_index(self) -> None:
        p = make_para(coords=[coord(100, 0.0, 0.0, h=0.0)])
        result = build_note_position(p, fallback_page_h=842.0, y_offset=0.0, x_offset=0.0)
        # page_index = 99
        assert result.annotation_sort_index.startswith("00099|")


import pytest  # noqa: E402  (placed here to keep helpers above readable)
