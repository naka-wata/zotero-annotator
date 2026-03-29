"""Unit tests for helper functions extracted from _build_paragraphs_for_page."""
from __future__ import annotations

import pytest

from zotero_annotator.services.pymupdf_paragraphs import (
    ExtractionConfig,
    _BodyBand,
    _Line,
    _PageMetrics,
    _compute_page_metrics,
    _filter_page_numbers,
    _filter_narrow_tall_lines,
    _merge_same_baseline_lines,
    _drop_footnotes,
    _is_page_number_line,
    _is_footnote_start,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_line(
    text: str = "Hello world",
    x0: float = 50.0,
    y0: float = 100.0,
    x1: float = 300.0,
    y1: float = 114.0,
    font_size: float = 12.0,
    page_index: int = 0,
    block_no: int = 0,
) -> _Line:
    return _Line(
        page_index=page_index,
        x0=x0,
        y0=y0,
        x1=x1,
        y1=y1,
        text=text,
        font_size=font_size,
        block_no=block_no,
    )


def make_metrics(
    avg_h: float = 14.0,
    median_w: float = 250.0,
    page_med_fs: float = 12.0,
    band_ok: bool = False,
    body_med_fs: float = 0.0,
) -> _PageMetrics:
    band = _BodyBand(ok=band_ok, y0=100.0, y1=700.0, med_fs=12.0, med_h=14.0, med_w=250.0)
    return _PageMetrics(
        avg_h=avg_h,
        median_w=median_w,
        page_med_fs=page_med_fs,
        band=band,
        body_med_fs=body_med_fs,
    )


# ---------------------------------------------------------------------------
# _compute_page_metrics
# ---------------------------------------------------------------------------


class TestComputePageMetrics:
    def test_empty_list_returns_valid_metrics(self) -> None:
        config = ExtractionConfig()
        result = _compute_page_metrics([], page_w=600.0, page_h=800.0, config=config)
        # avg_h may have a non-zero default from _page_avg_line_height, but page_med_fs
        # must be 0 and band.ok must be False for an empty line list
        assert result.page_med_fs == 0.0
        assert result.band.ok is False

    def test_normal_list_computes_positive_values(self) -> None:
        lines = [
            make_line(y0=100.0, y1=114.0, font_size=12.0),
            make_line(y0=120.0, y1=134.0, font_size=10.0),
            make_line(y0=140.0, y1=154.0, font_size=12.0),
        ]
        config = ExtractionConfig()
        result = _compute_page_metrics(lines, page_w=600.0, page_h=800.0, config=config)
        assert result.avg_h > 0
        assert result.page_med_fs > 0


# ---------------------------------------------------------------------------
# _is_page_number_line / _filter_page_numbers
# ---------------------------------------------------------------------------


class TestIsPageNumberLine:
    def _make_page_number_line(self) -> _Line:
        # text="42", near bottom center of page
        return make_line(
            text="42",
            x0=280.0,
            y0=750.0,
            x1=320.0,
            y1=762.0,
            font_size=10.0,
        )

    def test_page_number_line_is_detected(self) -> None:
        line = self._make_page_number_line()
        metrics = make_metrics(band_ok=False)
        config = ExtractionConfig(drop_page_numbers=True)
        assert _is_page_number_line(line, page_w=600.0, page_h=800.0, metrics=metrics, config=config) is True

    def test_normal_text_line_not_detected(self) -> None:
        line = make_line(text="This is a normal sentence.", y0=400.0, y1=414.0)
        metrics = make_metrics(band_ok=False)
        config = ExtractionConfig(drop_page_numbers=True)
        assert _is_page_number_line(line, page_w=600.0, page_h=800.0, metrics=metrics, config=config) is False

    def test_drop_page_numbers_false_disables_detection(self) -> None:
        line = self._make_page_number_line()
        metrics = make_metrics(band_ok=False)
        config = ExtractionConfig(drop_page_numbers=False)
        assert _is_page_number_line(line, page_w=600.0, page_h=800.0, metrics=metrics, config=config) is False


class TestFilterPageNumbers:
    def test_page_number_line_is_filtered(self) -> None:
        pg_num = make_line(text="42", x0=280.0, y0=750.0, x1=320.0, y1=762.0, font_size=10.0)
        body = make_line(text="Some body text.", x0=50.0, y0=300.0, x1=400.0, y1=314.0)
        metrics = make_metrics(band_ok=False)
        config = ExtractionConfig(drop_page_numbers=True)
        result = _filter_page_numbers(
            [pg_num, body], page_w=600.0, page_h=800.0, metrics=metrics, config=config
        )
        assert len(result) == 1
        assert result[0].text == "Some body text."

    def test_normal_line_not_filtered(self) -> None:
        body = make_line(text="Normal paragraph text.", x0=50.0, y0=300.0, x1=400.0, y1=314.0)
        metrics = make_metrics(band_ok=False)
        config = ExtractionConfig(drop_page_numbers=True)
        result = _filter_page_numbers(
            [body], page_w=600.0, page_h=800.0, metrics=metrics, config=config
        )
        assert result == [body]

    def test_drop_page_numbers_false_keeps_page_number(self) -> None:
        pg_num = make_line(text="42", x0=280.0, y0=750.0, x1=320.0, y1=762.0, font_size=10.0)
        metrics = make_metrics(band_ok=False)
        config = ExtractionConfig(drop_page_numbers=False)
        result = _filter_page_numbers(
            [pg_num], page_w=600.0, page_h=800.0, metrics=metrics, config=config
        )
        assert result == [pg_num]


# ---------------------------------------------------------------------------
# _filter_narrow_tall_lines
# ---------------------------------------------------------------------------


class TestFilterNarrowTallLines:
    def _make_narrow_tall_line(self) -> _Line:
        # width=25 < 600*0.08=48, height=205 > 800*0.25=200
        return make_line(x0=10.0, y0=100.0, x1=35.0, y1=305.0, text="narrow")

    def test_narrow_tall_line_is_filtered(self) -> None:
        narrow = self._make_narrow_tall_line()
        metrics = make_metrics(band_ok=False)
        config = ExtractionConfig(drop_narrow_tall_lines=True)
        result = _filter_narrow_tall_lines(
            [narrow], page_w=600.0, page_h=800.0, metrics=metrics, config=config
        )
        assert result == []

    def test_normal_line_not_filtered(self) -> None:
        normal = make_line(x0=50.0, y0=100.0, x1=400.0, y1=114.0, text="normal line")
        metrics = make_metrics(band_ok=False)
        config = ExtractionConfig(drop_narrow_tall_lines=True)
        result = _filter_narrow_tall_lines(
            [normal], page_w=600.0, page_h=800.0, metrics=metrics, config=config
        )
        assert result == [normal]

    def test_drop_narrow_tall_lines_false_keeps_narrow_tall(self) -> None:
        narrow = self._make_narrow_tall_line()
        metrics = make_metrics(band_ok=False)
        config = ExtractionConfig(drop_narrow_tall_lines=False)
        result = _filter_narrow_tall_lines(
            [narrow], page_w=600.0, page_h=800.0, metrics=metrics, config=config
        )
        assert result == [narrow]


# ---------------------------------------------------------------------------
# _merge_same_baseline_lines
# ---------------------------------------------------------------------------


class TestMergeSameBaselineLines:
    def test_adjacent_same_baseline_lines_merged(self) -> None:
        line1 = make_line(text="Hello", x0=50.0, y0=100.0, x1=200.0, y1=114.0, font_size=12.0)
        line2 = make_line(text="world", x0=202.0, y0=100.0, x1=350.0, y1=114.0, font_size=12.0)
        metrics = make_metrics(avg_h=14.0, page_med_fs=12.0)
        config = ExtractionConfig(same_baseline_merge=True)
        result = _merge_same_baseline_lines([line1, line2], page_w=600.0, metrics=metrics, config=config)
        assert len(result) == 1
        assert result[0].text == "Hello world"

    def test_lines_on_different_baselines_not_merged(self) -> None:
        line1 = make_line(text="Line one", x0=50.0, y0=100.0, x1=200.0, y1=114.0, font_size=12.0)
        line2 = make_line(text="Line two", x0=50.0, y0=130.0, x1=200.0, y1=144.0, font_size=12.0)
        metrics = make_metrics(avg_h=14.0, page_med_fs=12.0)
        config = ExtractionConfig(same_baseline_merge=True)
        result = _merge_same_baseline_lines([line1, line2], page_w=600.0, metrics=metrics, config=config)
        assert len(result) == 2

    def test_same_baseline_merge_false_disables_merging(self) -> None:
        line1 = make_line(text="Hello", x0=50.0, y0=100.0, x1=200.0, y1=114.0, font_size=12.0)
        line2 = make_line(text="world", x0=202.0, y0=100.0, x1=350.0, y1=114.0, font_size=12.0)
        metrics = make_metrics(avg_h=14.0, page_med_fs=12.0)
        config = ExtractionConfig(same_baseline_merge=False)
        result = _merge_same_baseline_lines([line1, line2], page_w=600.0, metrics=metrics, config=config)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# _is_footnote_start / _drop_footnotes
# ---------------------------------------------------------------------------


class TestIsFootnoteStart:
    def test_footnote_start_detected(self) -> None:
        line = make_line(
            text="1 This is a footnote",
            x0=50.0, y0=720.0, x1=300.0, y1=734.0, font_size=10.0,
        )
        metrics = make_metrics(body_med_fs=12.0, band_ok=False)
        config = ExtractionConfig()
        # band_y0 = 800 * (1 - 0.12) = 704.0; line.y0=720 > 704
        assert _is_footnote_start(line, band_y0=704.0, metrics=metrics, config=config) is True

    def test_line_above_band_y0_not_footnote(self) -> None:
        line = make_line(
            text="1 This is a footnote",
            x0=50.0, y0=400.0, x1=300.0, y1=414.0, font_size=10.0,
        )
        metrics = make_metrics(body_med_fs=12.0, band_ok=False)
        config = ExtractionConfig()
        assert _is_footnote_start(line, band_y0=704.0, metrics=metrics, config=config) is False

    def test_large_font_not_footnote(self) -> None:
        # font_size=16 > body_med_fs*footnote_font_size_mult (12*0.9=10.8)
        line = make_line(
            text="1 Big font line",
            x0=50.0, y0=720.0, x1=300.0, y1=736.0, font_size=16.0,
        )
        metrics = make_metrics(body_med_fs=12.0, band_ok=False)
        config = ExtractionConfig()
        assert _is_footnote_start(line, band_y0=704.0, metrics=metrics, config=config) is False


class TestDropFootnotes:
    def test_footnote_line_is_dropped(self) -> None:
        footnote = make_line(
            text="1 This is a footnote",
            x0=50.0, y0=720.0, x1=300.0, y1=734.0, font_size=10.0,
        )
        body = make_line(
            text="Main body text here.",
            x0=50.0, y0=200.0, x1=500.0, y1=214.0, font_size=12.0,
        )
        metrics = make_metrics(avg_h=14.0, body_med_fs=12.0, band_ok=False)
        config = ExtractionConfig(drop_footnotes=True)
        result = _drop_footnotes(
            [footnote, body], page_w=600.0, page_h=800.0, metrics=metrics, config=config
        )
        texts = [l.text for l in result]
        assert "Main body text here." in texts
        assert "1 This is a footnote" not in texts

    def test_normal_body_line_not_dropped(self) -> None:
        body = make_line(
            text="Normal body paragraph.",
            x0=50.0, y0=200.0, x1=500.0, y1=214.0, font_size=12.0,
        )
        metrics = make_metrics(avg_h=14.0, body_med_fs=12.0, band_ok=False)
        config = ExtractionConfig(drop_footnotes=True)
        result = _drop_footnotes(
            [body], page_w=600.0, page_h=800.0, metrics=metrics, config=config
        )
        assert result == [body]

    def test_drop_footnotes_false_keeps_footnote(self) -> None:
        footnote = make_line(
            text="1 This is a footnote",
            x0=50.0, y0=720.0, x1=300.0, y1=734.0, font_size=10.0,
        )
        metrics = make_metrics(avg_h=14.0, body_med_fs=12.0, band_ok=False)
        config = ExtractionConfig(drop_footnotes=False)
        result = _drop_footnotes(
            [footnote], page_w=600.0, page_h=800.0, metrics=metrics, config=config
        )
        assert result == [footnote]
