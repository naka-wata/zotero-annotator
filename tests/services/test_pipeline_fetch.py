from __future__ import annotations

from typing import Any, Dict
from unittest.mock import MagicMock

import httpx
import pytest

from zotero_annotator.clients.zotero import ZoteroClient
from zotero_annotator.models.results import ItemResult
from zotero_annotator.services.pipeline import _fetch_item_and_pdf


def _make_item(key: str = "ITEM0001", title: str = "Test Title") -> Dict[str, Any]:
    return {
        "key": key,
        "version": 1,
        "data": {
            "key": key,
            "itemType": "journalArticle",
            "title": title,
            "tags": [],
        },
        "links": {},
    }


def _make_pdf_child(key: str = "PDF00001") -> Dict[str, Any]:
    return {
        "key": key,
        "version": 1,
        "data": {
            "key": key,
            "itemType": "attachment",
            "contentType": "application/pdf",
        },
        "links": {},
    }


@pytest.fixture
def mock_zotero() -> MagicMock:
    return MagicMock(spec=ZoteroClient)


class TestFetchItemAndPdf:
    def test_success_returns_title_and_pdf_key(self, mock_zotero: MagicMock) -> None:
        """正常系: PDF アタッチメントあり → (title, pdf_key) のタプルが返る"""
        item = _make_item(key="ITEM0001", title="Test Title")
        pdf_child = _make_pdf_child(key="PDF00001")

        mock_zotero.list_children.return_value = [pdf_child]
        mock_zotero.pick_pdf_attachment.return_value = pdf_child

        result = _fetch_item_and_pdf("ITEM0001", item, mock_zotero)

        assert isinstance(result, tuple)
        title, pdf_key = result
        assert title == "Test Title"
        assert pdf_key == "PDF00001"

    def test_empty_children_returns_skipped_item_result(
        self, mock_zotero: MagicMock
    ) -> None:
        """children が空 → ItemResult が返り skipped_reason に内容がある"""
        item = _make_item(key="ITEM0002", title="No Children Paper")

        mock_zotero.list_children.return_value = []
        mock_zotero.pick_pdf_attachment.return_value = None

        result = _fetch_item_and_pdf("ITEM0002", item, mock_zotero)

        assert isinstance(result, ItemResult)
        assert result.skipped_reason is not None
        assert len(result.skipped_reason) > 0

    def test_no_pdf_attachment_returns_skipped_item_result(
        self, mock_zotero: MagicMock
    ) -> None:
        """PDF アタッチメントが存在しない (pick_pdf_attachment が None を返す) → ItemResult が返る"""
        item = _make_item(key="ITEM0003", title="No PDF Paper")
        non_pdf_child: Dict[str, Any] = {
            "key": "CHILD001",
            "version": 1,
            "data": {"key": "CHILD001", "itemType": "attachment", "contentType": "text/html"},
            "links": {},
        }

        mock_zotero.list_children.return_value = [non_pdf_child]
        mock_zotero.pick_pdf_attachment.return_value = None

        result = _fetch_item_and_pdf("ITEM0003", item, mock_zotero)

        assert isinstance(result, ItemResult)
        assert result.skipped_reason is not None
        assert result.item_key == "ITEM0003"

    def test_list_children_http_error_returns_skipped_item_result(
        self, mock_zotero: MagicMock
    ) -> None:
        """list_children() が httpx.HTTPError を投げる → ItemResult が返る"""
        item = _make_item(key="ITEM0004", title="Network Error Paper")

        mock_zotero.list_children.side_effect = httpx.HTTPError("connection failed")

        result = _fetch_item_and_pdf("ITEM0004", item, mock_zotero)

        assert isinstance(result, ItemResult)
        assert result.skipped_reason is not None
        assert result.item_key == "ITEM0004"
        assert result.pdf_key is None
