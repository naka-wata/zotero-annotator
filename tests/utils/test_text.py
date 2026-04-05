from __future__ import annotations

import pytest

from zotero_annotator.services.paragraphs import Paragraph, ParagraphCoord
from zotero_annotator.utils.text import merge_leading_continuations, normalize_text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_para(
    text: str,
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


def coord(page: int) -> ParagraphCoord:
    return ParagraphCoord(page=page, x=0.0, y=0.0, w=100.0, h=10.0)


# ---------------------------------------------------------------------------
# normalize_text
# ---------------------------------------------------------------------------

class TestNormalizeText:
    def test_collapses_multiple_spaces(self) -> None:
        assert normalize_text("hello   world") == "hello world"

    def test_collapses_tabs(self) -> None:
        assert normalize_text("hello\tworld") == "hello world"

    def test_replaces_newlines_with_space(self) -> None:
        assert normalize_text("hello\nworld") == "hello world"

    def test_replaces_mixed_whitespace(self) -> None:
        assert normalize_text("  hello \n  world  ") == "hello world"

    def test_empty_string(self) -> None:
        assert normalize_text("") == ""

    def test_none_like_empty_string(self) -> None:
        # normalize_text treats falsy value as empty string via `(text or "")`
        # noinspection PyTypeChecker
        assert normalize_text(None) == ""  # type: ignore[arg-type]

    def test_already_normalized(self) -> None:
        assert normalize_text("already normalized") == "already normalized"

    def test_leading_and_trailing_whitespace_stripped(self) -> None:
        assert normalize_text("  hello  ") == "hello"


# ---------------------------------------------------------------------------
# merge_leading_continuations
# ---------------------------------------------------------------------------

class TestMergeLeadingContinuations:
    # --- empty / single ---

    def test_empty_list(self) -> None:
        assert merge_leading_continuations([]) == []

    def test_single_paragraph_unchanged(self) -> None:
        p = make_para("Hello world.", hash="a")
        result = merge_leading_continuations([p])
        assert result == [p]

    # --- no merge cases ---

    def test_no_merge_when_prev_ends_with_period(self) -> None:
        p1 = make_para("This is a sentence.", hash="a")
        p2 = make_para("continuation here", hash="b")
        result = merge_leading_continuations([p1, p2])
        assert len(result) == 2

    def test_no_merge_when_prev_ends_with_question_mark(self) -> None:
        p1 = make_para("Is this a sentence?", hash="a")
        p2 = make_para("yes it is", hash="b")
        result = merge_leading_continuations([p1, p2])
        assert len(result) == 2

    def test_no_merge_when_prev_ends_with_exclamation(self) -> None:
        p1 = make_para("Watch out!", hash="a")
        p2 = make_para("careful here", hash="b")
        result = merge_leading_continuations([p1, p2])
        assert len(result) == 2

    def test_no_merge_when_current_starts_uppercase(self) -> None:
        p1 = make_para("First part", hash="a")
        p2 = make_para("New sentence", hash="b")
        result = merge_leading_continuations([p1, p2])
        assert len(result) == 2

    # --- merge cases ---

    def test_merge_when_current_starts_lowercase(self) -> None:
        p1 = make_para("The result was", hash="a")
        p2 = make_para("very significant", hash="b")
        result = merge_leading_continuations([p1, p2])
        assert len(result) == 1
        assert result[0].text == "The result was very significant"

    def test_merge_when_current_starts_with_comma(self) -> None:
        p1 = make_para("The result", hash="a")
        p2 = make_para(", as expected", hash="b")
        result = merge_leading_continuations([p1, p2])
        assert len(result) == 1

    def test_merge_when_current_starts_with_closing_paren(self) -> None:
        p1 = make_para("The value (see below", hash="a")
        p2 = make_para(") was large", hash="b")
        result = merge_leading_continuations([p1, p2])
        assert len(result) == 1

    def test_merge_when_current_starts_with_closing_bracket(self) -> None:
        p1 = make_para("The array [1, 2", hash="a")
        p2 = make_para("] is complete", hash="b")
        result = merge_leading_continuations([p1, p2])
        assert len(result) == 1

    def test_merge_dedup_hashes_combined(self) -> None:
        p1 = make_para("Part one", hash="h1")
        p2 = make_para("continues here", hash="h2")
        result = merge_leading_continuations([p1, p2])
        assert result[0].dedup_hashes == ["h1", "h2"]

    def test_merge_coords_combined(self) -> None:
        c1 = coord(0)
        c2 = coord(0)
        p1 = make_para("Part one", hash="h1", coords=[c1])
        p2 = make_para("continues here", hash="h2", coords=[c2])
        result = merge_leading_continuations([p1, p2])
        assert result[0].coords == [c1, c2]

    # --- page boundary ---

    def test_no_merge_across_non_adjacent_pages_with_coords(self) -> None:
        p1 = make_para("The result", hash="a", coords=[coord(0)])
        p2 = make_para("continues here", hash="b", coords=[coord(2)])
        result = merge_leading_continuations([p1, p2])
        assert len(result) == 2

    def test_merge_across_adjacent_pages_with_coords(self) -> None:
        p1 = make_para("The result", hash="a", coords=[coord(0)])
        p2 = make_para("continues here", hash="b", coords=[coord(1)])
        result = merge_leading_continuations([p1, p2])
        assert len(result) == 1

    def test_no_merge_across_non_adjacent_pages_with_page_attr(self) -> None:
        p1 = make_para("The result", hash="a", page=0)
        p2 = make_para("continues here", hash="b", page=2)
        result = merge_leading_continuations([p1, p2])
        assert len(result) == 2

    def test_merge_same_page_with_page_attr(self) -> None:
        p1 = make_para("The result", hash="a", page=1)
        p2 = make_para("continues here", hash="b", page=1)
        result = merge_leading_continuations([p1, p2])
        assert len(result) == 1

    # --- chained merges ---

    def test_three_paragraphs_chain_merge(self) -> None:
        p1 = make_para("First part", hash="h1")
        p2 = make_para("second part", hash="h2")
        p3 = make_para("third part", hash="h3")
        result = merge_leading_continuations([p1, p2, p3])
        assert len(result) == 1
        assert "First part" in result[0].text
        assert "second part" in result[0].text
        assert "third part" in result[0].text
