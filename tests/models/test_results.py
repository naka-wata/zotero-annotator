from __future__ import annotations

from zotero_annotator.models.results import (
    ItemResult,
    TranslationItemResult,
    make_skipped_item_result,
    make_skipped_translation_result,
)


# ---------------------------------------------------------------------------
# ItemResult
# ---------------------------------------------------------------------------

class TestItemResult:
    def test_normal_construction(self) -> None:
        r = ItemResult(
            item_key="ABCD1234",
            title="Sample Paper",
            pdf_key="PDF0001",
            paragraphs_total=10,
            paragraphs_skipped_duplicate=2,
            paragraphs_processed=8,
            annotations_planned=8,
            annotations_created=8,
        )
        assert r.item_key == "ABCD1234"
        assert r.title == "Sample Paper"
        assert r.pdf_key == "PDF0001"
        assert r.paragraphs_total == 10
        assert r.paragraphs_skipped_duplicate == 2
        assert r.paragraphs_processed == 8
        assert r.annotations_planned == 8
        assert r.annotations_created == 8
        assert r.skipped_reason is None
        assert r.warnings == []

    def test_skipped_result(self) -> None:
        r = ItemResult(
            item_key="ABCD1234",
            title="Sample Paper",
            pdf_key=None,
            paragraphs_total=0,
            paragraphs_skipped_duplicate=0,
            paragraphs_processed=0,
            annotations_planned=0,
            annotations_created=0,
            skipped_reason="no PDF attachment found",
        )
        assert r.skipped_reason == "no PDF attachment found"
        assert r.pdf_key is None

    def test_with_warnings(self) -> None:
        r = ItemResult(
            item_key="K1",
            title="T",
            pdf_key="P1",
            paragraphs_total=5,
            paragraphs_skipped_duplicate=0,
            paragraphs_processed=4,
            annotations_planned=4,
            annotations_created=3,
            warnings=["annotation 4 failed to write"],
        )
        assert len(r.warnings) == 1
        assert "annotation 4 failed to write" in r.warnings

    def test_warnings_default_is_independent(self) -> None:
        # default_factory=list means each instance gets its own list
        r1 = ItemResult(
            item_key="K1", title="T1", pdf_key=None,
            paragraphs_total=0, paragraphs_skipped_duplicate=0,
            paragraphs_processed=0, annotations_planned=0, annotations_created=0,
        )
        r2 = ItemResult(
            item_key="K2", title="T2", pdf_key=None,
            paragraphs_total=0, paragraphs_skipped_duplicate=0,
            paragraphs_processed=0, annotations_planned=0, annotations_created=0,
        )
        r1.warnings.append("warn")
        assert r2.warnings == []

    def test_pdf_key_none(self) -> None:
        r = ItemResult(
            item_key="K1", title="T", pdf_key=None,
            paragraphs_total=0, paragraphs_skipped_duplicate=0,
            paragraphs_processed=0, annotations_planned=0, annotations_created=0,
        )
        assert r.pdf_key is None


# ---------------------------------------------------------------------------
# TranslationItemResult
# ---------------------------------------------------------------------------

class TestTranslationItemResult:
    def test_normal_construction(self) -> None:
        r = TranslationItemResult(
            item_key="ABCD1234",
            title="Sample Paper",
            pdf_key="PDF0001",
            annotations_total=20,
            annotations_targeted=10,
            annotations_processed=10,
            annotations_updated=10,
        )
        assert r.item_key == "ABCD1234"
        assert r.annotations_total == 20
        assert r.annotations_targeted == 10
        assert r.annotations_processed == 10
        assert r.annotations_updated == 10
        assert r.skipped_reason is None
        assert r.warnings == []

    def test_skipped_result(self) -> None:
        r = TranslationItemResult(
            item_key="K1",
            title="T",
            pdf_key=None,
            annotations_total=0,
            annotations_targeted=0,
            annotations_processed=0,
            annotations_updated=0,
            skipped_reason="no annotations with za:translate tag",
        )
        assert r.skipped_reason == "no annotations with za:translate tag"

    def test_partial_update(self) -> None:
        r = TranslationItemResult(
            item_key="K1", title="T", pdf_key="P",
            annotations_total=5,
            annotations_targeted=5,
            annotations_processed=3,
            annotations_updated=2,
        )
        assert r.annotations_processed == 3
        assert r.annotations_updated == 2

    def test_warnings_default_is_independent(self) -> None:
        r1 = TranslationItemResult(
            item_key="K1", title="T1", pdf_key=None,
            annotations_total=0, annotations_targeted=0,
            annotations_processed=0, annotations_updated=0,
        )
        r2 = TranslationItemResult(
            item_key="K2", title="T2", pdf_key=None,
            annotations_total=0, annotations_targeted=0,
            annotations_processed=0, annotations_updated=0,
        )
        r1.warnings.append("warn")
        assert r2.warnings == []


# ---------------------------------------------------------------------------
# make_skipped_item_result
# ---------------------------------------------------------------------------

class TestMakeSkippedItemResult:
    def test_all_counts_are_zero(self) -> None:
        r = make_skipped_item_result("K1", "Title", "P1", "no PDF")
        assert r.paragraphs_total == 0
        assert r.paragraphs_skipped_duplicate == 0
        assert r.paragraphs_processed == 0
        assert r.annotations_planned == 0
        assert r.annotations_created == 0

    def test_skipped_reason_set(self) -> None:
        r = make_skipped_item_result("K1", "Title", None, "already processed")
        assert r.skipped_reason == "already processed"

    def test_fields_passed_through(self) -> None:
        r = make_skipped_item_result("MYKEY", "My Title", "PDFKEY", "reason")
        assert r.item_key == "MYKEY"
        assert r.title == "My Title"
        assert r.pdf_key == "PDFKEY"

    def test_pdf_key_none_accepted(self) -> None:
        r = make_skipped_item_result("K1", "T", None, "reason")
        assert r.pdf_key is None

    def test_returns_item_result_instance(self) -> None:
        r = make_skipped_item_result("K1", "T", None, "reason")
        assert isinstance(r, ItemResult)

    def test_warnings_empty_by_default(self) -> None:
        r = make_skipped_item_result("K1", "T", None, "reason")
        assert r.warnings == []


# ---------------------------------------------------------------------------
# make_skipped_translation_result
# ---------------------------------------------------------------------------

class TestMakeSkippedTranslationResult:
    def test_all_counts_are_zero(self) -> None:
        r = make_skipped_translation_result("K1", "Title", "P1", "no tags")
        assert r.annotations_total == 0
        assert r.annotations_targeted == 0
        assert r.annotations_processed == 0
        assert r.annotations_updated == 0

    def test_skipped_reason_set(self) -> None:
        r = make_skipped_translation_result("K1", "Title", None, "tag not found")
        assert r.skipped_reason == "tag not found"

    def test_fields_passed_through(self) -> None:
        r = make_skipped_translation_result("MYKEY", "My Title", "PDFKEY", "reason")
        assert r.item_key == "MYKEY"
        assert r.title == "My Title"
        assert r.pdf_key == "PDFKEY"

    def test_pdf_key_none_accepted(self) -> None:
        r = make_skipped_translation_result("K1", "T", None, "reason")
        assert r.pdf_key is None

    def test_returns_translation_item_result_instance(self) -> None:
        r = make_skipped_translation_result("K1", "T", None, "reason")
        assert isinstance(r, TranslationItemResult)

    def test_warnings_empty_by_default(self) -> None:
        r = make_skipped_translation_result("K1", "T", None, "reason")
        assert r.warnings == []
