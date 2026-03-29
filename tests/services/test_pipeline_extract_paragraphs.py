from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from zotero_annotator.clients.zotero import ZoteroClient
from zotero_annotator.config import CoreSettings
from zotero_annotator.models.results import ItemResult
from zotero_annotator.services.paragraphs import Paragraph
from zotero_annotator.services.pipeline import _extract_paragraphs_from_pdf


@pytest.fixture
def mock_zotero() -> MagicMock:
    return MagicMock(spec=ZoteroClient)


@pytest.fixture
def mock_settings() -> MagicMock:
    return MagicMock(spec=CoreSettings)


def _make_paragraph(text: str = "Sample paragraph text for testing.") -> Paragraph:
    return Paragraph(
        text=text,
        page=1,
        hash="abc123",
        coords=[],
        dedup_hashes=None,
    )


class TestExtractParagraphsFromPdf:
    def test_success_returns_paragraphs_and_existing_tags(
        self, mock_zotero: MagicMock, mock_settings: MagicMock
    ) -> None:
        """正常系: PDF から段落抽出成功 + タグ収集成功 → (paragraphs, existing_tags) が返る"""
        paragraphs = [_make_paragraph("Para 1"), _make_paragraph("Para 2")]
        existing_tags = {"para:hash1", "para:hash2"}

        with patch(
            "zotero_annotator.services.pipeline.extract_paragraphs_from_pdf_bytes",
            return_value=paragraphs,
        ):
            with patch(
                "zotero_annotator.services.pipeline.collect_existing_tags",
                return_value=existing_tags,
            ):
                result = _extract_paragraphs_from_pdf(
                    pdf_bytes=b"fake_pdf",
                    pdf_key="PDF00001",
                    item_key="ITEM0001",
                    title="Test Paper",
                    zotero=mock_zotero,
                    settings=mock_settings,
                )

        assert isinstance(result, tuple)
        paras, tags = result
        assert paras == paragraphs
        assert tags == existing_tags

    def test_empty_paragraphs_returns_empty_list_and_tags(
        self, mock_zotero: MagicMock, mock_settings: MagicMock
    ) -> None:
        """段落なし PDF → 空リストと既存タグが返る"""
        with patch(
            "zotero_annotator.services.pipeline.extract_paragraphs_from_pdf_bytes",
            return_value=[],
        ):
            with patch(
                "zotero_annotator.services.pipeline.collect_existing_tags",
                return_value=set(),
            ):
                result = _extract_paragraphs_from_pdf(
                    pdf_bytes=b"empty_pdf",
                    pdf_key="PDF00002",
                    item_key="ITEM0002",
                    title="Empty Paper",
                    zotero=mock_zotero,
                    settings=mock_settings,
                )

        assert isinstance(result, tuple)
        paras, tags = result
        assert paras == []
        assert tags == set()

    def test_extract_raises_http_error_returns_item_result(
        self, mock_zotero: MagicMock, mock_settings: MagicMock
    ) -> None:
        """抽出中に httpx.HTTPError → skipped_reason 付き ItemResult が返る"""
        with patch(
            "zotero_annotator.services.pipeline.extract_paragraphs_from_pdf_bytes",
            side_effect=httpx.HTTPError("connection error"),
        ):
            result = _extract_paragraphs_from_pdf(
                pdf_bytes=b"fake_pdf",
                pdf_key="PDF00003",
                item_key="ITEM0003",
                title="Error Paper",
                zotero=mock_zotero,
                settings=mock_settings,
            )

        assert isinstance(result, ItemResult)
        assert result.item_key == "ITEM0003"
        assert result.pdf_key == "PDF00003"
        assert result.skipped_reason is not None
        assert "extract_failed" in result.skipped_reason

    def test_extract_raises_value_error_returns_item_result(
        self, mock_zotero: MagicMock, mock_settings: MagicMock
    ) -> None:
        """抽出中に ValueError → skipped_reason 付き ItemResult が返る"""
        with patch(
            "zotero_annotator.services.pipeline.extract_paragraphs_from_pdf_bytes",
            side_effect=ValueError("invalid pdf"),
        ):
            result = _extract_paragraphs_from_pdf(
                pdf_bytes=b"bad_pdf",
                pdf_key="PDF00004",
                item_key="ITEM0004",
                title="Invalid PDF Paper",
                zotero=mock_zotero,
                settings=mock_settings,
            )

        assert isinstance(result, ItemResult)
        assert result.item_key == "ITEM0004"
        assert result.skipped_reason is not None
        assert "extract_failed" in result.skipped_reason

    def test_extract_raises_runtime_error_returns_item_result(
        self, mock_zotero: MagicMock, mock_settings: MagicMock
    ) -> None:
        """抽出中に RuntimeError → skipped_reason 付き ItemResult が返る"""
        with patch(
            "zotero_annotator.services.pipeline.extract_paragraphs_from_pdf_bytes",
            side_effect=RuntimeError("unexpected error"),
        ):
            result = _extract_paragraphs_from_pdf(
                pdf_bytes=b"bad_pdf",
                pdf_key="PDF00005",
                item_key="ITEM0005",
                title="Runtime Error Paper",
                zotero=mock_zotero,
                settings=mock_settings,
            )

        assert isinstance(result, ItemResult)
        assert result.item_key == "ITEM0005"
        assert result.skipped_reason is not None
        assert "extract_failed" in result.skipped_reason

    def test_collect_tags_http_error_returns_item_result(
        self, mock_zotero: MagicMock, mock_settings: MagicMock
    ) -> None:
        """タグ収集中に httpx.HTTPError → paragraphs_total を持つ ItemResult が返る"""
        paragraphs = [_make_paragraph("Para 1"), _make_paragraph("Para 2")]

        with patch(
            "zotero_annotator.services.pipeline.extract_paragraphs_from_pdf_bytes",
            return_value=paragraphs,
        ):
            with patch(
                "zotero_annotator.services.pipeline.collect_existing_tags",
                side_effect=httpx.HTTPError("zotero api error"),
            ):
                result = _extract_paragraphs_from_pdf(
                    pdf_bytes=b"fake_pdf",
                    pdf_key="PDF00006",
                    item_key="ITEM0006",
                    title="Tag Error Paper",
                    zotero=mock_zotero,
                    settings=mock_settings,
                )

        assert isinstance(result, ItemResult)
        assert result.item_key == "ITEM0006"
        assert result.paragraphs_total == len(paragraphs)
        assert result.skipped_reason is not None
        assert "list_annotations_failed" in result.skipped_reason
