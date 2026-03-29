"""
tests/services/test_paragraphs.py

services/paragraphs.py は Paragraph / ParagraphCoord の dataclass 定義のみ。
段落の構築・フィルタリングに関わる純粋関数は services/pymupdf_adapter.py にある。
ここでは両モジュールから純粋関数を対象にテストする。

NOTE: min_chars フィルタは extract_paragraphs_from_pdf_bytes() 内で適用されており、
      PyMuPDF 依存のため直接テストしない。代わりにフィルタ判定に使われる述語関数を
      テストすることで、フィルタリング挙動を間接的にカバーする。
"""
from __future__ import annotations

from zotero_annotator.services.paragraphs import Paragraph, ParagraphCoord
from zotero_annotator.services.pymupdf_adapter import (
    _hash_text,
    _is_caption_continuation,
    _is_caption_start,
    _is_section_heading,
    _is_sentence_like,
    _merge_leading_continuations,
    _table_like_score,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_para(
    text: str,
    hash: str | None = None,
    page: int | None = None,
    coords: list[ParagraphCoord] | None = None,
) -> Paragraph:
    h = hash or _hash_text(text)
    return Paragraph(text=text, hash=h, dedup_hashes=[h], coords=coords or [], page=page)


def coord(page: int) -> ParagraphCoord:
    return ParagraphCoord(page=page, x=0.0, y=0.0, w=100.0, h=10.0)


# ---------------------------------------------------------------------------
# Paragraph / ParagraphCoord dataclass
# ---------------------------------------------------------------------------

class TestParagraphDataclass:
    def test_construction(self) -> None:
        p = Paragraph(text="hello", hash="abc", dedup_hashes=["abc"], coords=[], page=1)
        assert p.text == "hello"
        assert p.hash == "abc"
        assert p.page == 1

    def test_equality(self) -> None:
        p1 = Paragraph(text="x", hash="h", dedup_hashes=["h"], coords=[], page=None)
        p2 = Paragraph(text="x", hash="h", dedup_hashes=["h"], coords=[], page=None)
        assert p1 == p2

    def test_paragraph_coord_construction(self) -> None:
        c = ParagraphCoord(page=2, x=10.0, y=20.0, w=100.0, h=15.0)
        assert c.page == 2
        assert c.w == 100.0


# ---------------------------------------------------------------------------
# _hash_text
# ---------------------------------------------------------------------------

class TestHashText:
    def test_same_text_same_hash(self) -> None:
        assert _hash_text("hello world") == _hash_text("hello world")

    def test_different_text_different_hash(self) -> None:
        assert _hash_text("foo") != _hash_text("bar")

    def test_normalizes_before_hashing(self) -> None:
        # extra whitespace should not change the hash
        assert _hash_text("hello  world") == _hash_text("hello world")

    def test_empty_string(self) -> None:
        result = _hash_text("")
        assert isinstance(result, str) and len(result) == 40  # sha1 hex


# ---------------------------------------------------------------------------
# _is_sentence_like
# ---------------------------------------------------------------------------

class TestIsSentenceLike:
    def test_typical_sentence(self) -> None:
        assert _is_sentence_like("The model achieves state-of-the-art results on several benchmarks.")

    def test_too_short_returns_false(self) -> None:
        # fewer than 6 words
        assert not _is_sentence_like("Short text.")

    def test_no_lowercase_returns_false(self) -> None:
        assert not _is_sentence_like("ABC DEF GHI JKL MNO PQR.")

    def test_no_sentence_terminator_returns_false(self) -> None:
        assert not _is_sentence_like("This is a fragment without terminator")

    def test_empty_string_returns_false(self) -> None:
        assert not _is_sentence_like("")


# ---------------------------------------------------------------------------
# _is_caption_start
# ---------------------------------------------------------------------------

class TestIsCaptionStart:
    def test_figure_caption(self) -> None:
        assert _is_caption_start("Figure 1: Sample results")

    def test_fig_abbreviation(self) -> None:
        assert _is_caption_start("Fig. 2. Architecture overview")

    def test_table_caption(self) -> None:
        assert _is_caption_start("Table 3: Comparison of methods")

    def test_regular_text_is_not_caption(self) -> None:
        assert not _is_caption_start("The results show that our model outperforms")

    def test_empty_string(self) -> None:
        assert not _is_caption_start("")


# ---------------------------------------------------------------------------
# _is_caption_continuation
# ---------------------------------------------------------------------------

class TestIsCaptionContinuation:
    def test_comma_separated_list(self) -> None:
        assert _is_caption_continuation("Seaquest, Beam Rider")

    def test_short_title_case(self) -> None:
        assert _is_caption_continuation("Space Invaders")

    def test_empty_returns_false(self) -> None:
        assert not _is_caption_continuation("")

    def test_lowercase_start_returns_false(self) -> None:
        assert not _is_caption_continuation("and we observe that")

    def test_long_text_returns_false(self) -> None:
        long_text = "A" * 121
        assert not _is_caption_continuation(long_text)

    def test_many_words_without_comma_returns_false(self) -> None:
        assert not _is_caption_continuation("One Two Three Four Five Six Seven")


# ---------------------------------------------------------------------------
# _is_section_heading
# ---------------------------------------------------------------------------

class TestIsSectionHeading:
    def test_numbered_heading(self) -> None:
        assert _is_section_heading("6 Conclusion")

    def test_dotted_subsection(self) -> None:
        assert _is_section_heading("4.1 Experimental Setup")

    def test_bare_heading_abstract(self) -> None:
        assert _is_section_heading("Abstract")

    def test_bare_heading_references(self) -> None:
        assert _is_section_heading("References")

    def test_bare_heading_introduction(self) -> None:
        assert _is_section_heading("Introduction")

    def test_long_text_not_heading(self) -> None:
        assert not _is_section_heading(
            "The proposed method achieves significantly better results than all baselines."
        )

    def test_text_with_comma_not_heading(self) -> None:
        assert not _is_section_heading("Results, Discussion, and Conclusion")

    def test_sentence_ending_not_heading(self) -> None:
        assert not _is_section_heading("6 Conclusion.")

    def test_empty_string(self) -> None:
        assert not _is_section_heading("")

    def test_caption_not_heading(self) -> None:
        assert not _is_section_heading("Figure 1: Overview")


# ---------------------------------------------------------------------------
# _table_like_score
# ---------------------------------------------------------------------------

class TestTableLikeScore:
    def test_numeric_heavy_row_high_score(self) -> None:
        row = "85.3 72.1 91.0 68.4 77.2 83.6 90.1 65.0"
        assert _table_like_score(row) > 0.3

    def test_normal_prose_low_score(self) -> None:
        prose = (
            "The proposed method significantly outperforms all baseline models "
            "across every evaluated benchmark dataset."
        )
        assert _table_like_score(prose) < 0.2

    def test_empty_string_returns_zero(self) -> None:
        assert _table_like_score("") == 0.0

    def test_score_bounded_between_0_and_1(self) -> None:
        for text in ["", "abc", "1 2 3 4 5 6 7 8 9 10", "Normal sentence with words."]:
            s = _table_like_score(text)
            assert 0.0 <= s <= 1.0


# ---------------------------------------------------------------------------
# _merge_leading_continuations (adapter version — includes caption logic)
# ---------------------------------------------------------------------------

class TestMergeLeadingContinuations:
    def test_empty_list(self) -> None:
        assert _merge_leading_continuations([]) == []

    def test_single_paragraph_unchanged(self) -> None:
        p = make_para("Hello world.")
        assert _merge_leading_continuations([p]) == [p]

    def test_no_merge_when_prev_ends_with_period(self) -> None:
        p1 = make_para("This is a complete sentence.")
        p2 = make_para("continuation of something")
        result = _merge_leading_continuations([p1, p2])
        assert len(result) == 2

    def test_no_merge_when_current_starts_uppercase(self) -> None:
        # Prev must have > 6 words to avoid being treated as caption-like by _is_caption_continuation.
        p1 = make_para("The first part has several more words here")
        p2 = make_para("New topic starts here with uppercase")
        result = _merge_leading_continuations([p1, p2])
        assert len(result) == 2

    def test_merge_lowercase_continuation(self) -> None:
        # Prev must have > 6 words to avoid being treated as caption-like.
        p1 = make_para("The results were quite interesting and unexpected here")
        p2 = make_para("very significant indeed")
        result = _merge_leading_continuations([p1, p2])
        assert len(result) == 1
        assert "The results were quite interesting" in result[0].text
        assert "very significant indeed" in result[0].text

    def test_merge_comma_continuation(self) -> None:
        p1 = make_para("The method")
        p2 = make_para(", as expected, converged")
        result = _merge_leading_continuations([p1, p2])
        assert len(result) == 1

    # caption-specific logic (differs from utils/text.py version)

    def test_caption_does_not_absorb_body_text(self) -> None:
        # Figure caption should NOT merge with subsequent body text
        p_caption = make_para("Figure 1: Sample results from our experiment.")
        p_body = make_para("an extended description of results follows here")
        result = _merge_leading_continuations([p_caption, p_body])
        assert len(result) == 2

    def test_caption_merges_with_continuation_fragment(self) -> None:
        # Caption should absorb a short list-like fragment
        p_caption = make_para("Figure 2: Game environments used in evaluation.")
        p_cont = make_para("Seaquest, Beam Rider")
        result = _merge_leading_continuations([p_caption, p_cont])
        assert len(result) == 1
        assert "Seaquest" in result[0].text

    def test_coords_combined_on_merge(self) -> None:
        c1 = coord(0)
        c2 = coord(0)
        # Prev must have > 6 words to avoid being treated as caption-like.
        p1 = make_para("Part one has several more words now", coords=[c1])
        p2 = make_para("continues here", coords=[c2])
        result = _merge_leading_continuations([p1, p2])
        assert result[0].coords == [c1, c2]

    def test_no_merge_across_non_adjacent_pages(self) -> None:
        p1 = make_para("Part one", coords=[coord(0)])
        p2 = make_para("continues here", coords=[coord(2)])
        result = _merge_leading_continuations([p1, p2])
        assert len(result) == 2

    def test_multiple_paragraphs_partial_merge(self) -> None:
        # Use paragraphs with > 6 words to prevent caption-like treatment.
        p1 = make_para("This complete sentence terminates with a period properly.")
        p2 = make_para("The second paragraph has several words without any terminator")
        p3 = make_para("continuation of the second paragraph without end")
        p4 = make_para("More separate content starts a new thought here.")
        result = _merge_leading_continuations([p1, p2, p3, p4])
        # p1 ends with period → p2 not merged into p1
        # p3 starts lowercase → merged into p2
        # p4 starts uppercase → not merged
        assert len(result) == 3
