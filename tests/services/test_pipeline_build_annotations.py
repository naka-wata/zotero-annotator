from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from zotero_annotator.config import CoreSettings
from zotero_annotator.models.results import ItemResult
from zotero_annotator.services.paragraphs import Paragraph
from zotero_annotator.services.pipeline import _build_annotation_payloads


@pytest.fixture
def mock_settings() -> MagicMock:
    settings = MagicMock(spec=CoreSettings)
    settings.dedup_tag_prefix = "para:"
    settings.ann_pending_translation_tag = "za:translate"
    return settings


def _make_paragraph(text: str = "Sample paragraph.", hash_: str = "abc123") -> Paragraph:
    return Paragraph(
        text=text,
        hash=hash_,
        dedup_hashes=None,
        coords=[],
        page=0,
    )


def _call(
    paragraphs: list,
    existing_tags: set,
    mock_settings: MagicMock,
    *,
    max_paragraphs: int = 100,
):
    return _build_annotation_payloads(
        paragraphs,
        existing_tags,
        pdf_key="PDF00001",
        translator=None,
        settings=mock_settings,
        item_key="ITEM0001",
        title="Test Title",
        source_lang="",
        target_lang="",
        annotation_mode="note",
        page_sizes=None,
        max_paragraphs=max_paragraphs,
    )


class TestBuildAnnotationPayloads:
    def test_multiple_paragraphs_returns_payload_list(self, mock_settings: MagicMock) -> None:
        """複数段落 → 件数分のペイロードリストが返る"""
        paragraphs = [
            _make_paragraph("Para 1", "hash1"),
            _make_paragraph("Para 2", "hash2"),
            _make_paragraph("Para 3", "hash3"),
        ]
        result = _call(paragraphs, set(), mock_settings)

        assert isinstance(result, list)
        assert len(result) == 3

    def test_empty_paragraphs_returns_empty_list(self, mock_settings: MagicMock) -> None:
        """空の段落リスト → 空リストが返る"""
        result = _call([], set(), mock_settings)

        assert result == []

    def test_payload_contains_required_keys(self, mock_settings: MagicMock) -> None:
        """段落内容がペイロードの必須フィールドに正しく反映されるか"""
        paragraphs = [_make_paragraph("Hello world.", "deadbeef")]
        result = _call(paragraphs, set(), mock_settings)

        assert isinstance(result, list)
        payload = result[0]
        assert payload["itemType"] == "annotation"
        assert payload["parentItem"] == "PDF00001"
        assert payload["annotationComment"] == "Hello world."

    def test_duplicate_paragraphs_are_skipped(self, mock_settings: MagicMock) -> None:
        """既存タグと重複する段落はスキップされる"""
        paragraphs = [
            _make_paragraph("Para 1", "hash1"),
            _make_paragraph("Para 2", "hash2"),
        ]
        # hash1 はすでに処理済み
        existing_tags = {"para:hash1"}
        result = _call(paragraphs, existing_tags, mock_settings)

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["annotationComment"] == "Para 2"

    def test_max_paragraphs_limits_output(self, mock_settings: MagicMock) -> None:
        """max_paragraphs で処理件数が制限される"""
        paragraphs = [_make_paragraph(f"Para {i}", f"hash{i}") for i in range(5)]
        result = _call(paragraphs, set(), mock_settings, max_paragraphs=2)

        assert isinstance(result, list)
        assert len(result) == 2

    def test_payload_tags_include_dedup_tag(self, mock_settings: MagicMock) -> None:
        """ペイロードのタグに para:<hash> が含まれる"""
        paragraphs = [_make_paragraph("Para 1", "abc123")]
        result = _call(paragraphs, set(), mock_settings)

        assert isinstance(result, list)
        tag_names = [t["tag"] for t in result[0]["tags"]]
        assert "para:abc123" in tag_names

    def test_no_translator_adds_pending_tag(self, mock_settings: MagicMock) -> None:
        """translator=None のとき za:translate タグが付く"""
        paragraphs = [_make_paragraph("Para 1", "hash1")]
        result = _call(paragraphs, set(), mock_settings)

        assert isinstance(result, list)
        tag_names = [t["tag"] for t in result[0]["tags"]]
        assert "za:translate" in tag_names

    def test_translation_error_returns_item_result(self, mock_settings: MagicMock) -> None:
        """翻訳エラー時は ItemResult が返る（フェイルファスト）"""
        from zotero_annotator.services.translators.base import TranslationError

        paragraphs = [_make_paragraph("Para 1", "hash1")]
        failing_translator = MagicMock()
        failing_translator.translate.side_effect = TranslationError(
            "rate_limit", "translation failed", status_code=429
        )

        result = _build_annotation_payloads(
            paragraphs,
            set(),
            pdf_key="PDF00001",
            translator=failing_translator,
            settings=mock_settings,
            item_key="ITEM0001",
            title="Test Title",
            source_lang="en",
            target_lang="ja",
            annotation_mode="note",
            page_sizes=None,
            max_paragraphs=100,
        )

        assert isinstance(result, ItemResult)
        assert result.skipped_reason is not None
        assert "translation_failed" in result.skipped_reason
