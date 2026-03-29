from __future__ import annotations

from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

from zotero_annotator.clients.zotero import ZoteroClient
from zotero_annotator.services.translators.base import TranslationResult, Translator


@pytest.fixture
def mock_zotero_client() -> MagicMock:
    return MagicMock(spec=ZoteroClient)


@pytest.fixture
def mock_translator() -> MagicMock:
    mock = MagicMock(spec=Translator)
    mock.translate.return_value = TranslationResult(
        text="翻訳結果テキスト",
        provider="mock",
        model="mock-model",
    )
    return mock


@pytest.fixture
def sample_zotero_item() -> Dict[str, Any]:
    return {
        "key": "ABCD1234",
        "version": 42,
        "data": {
            "key": "ABCD1234",
            "itemType": "journalArticle",
            "title": "Sample Paper Title",
            "tags": [{"tag": "to-translate"}],
        },
        "links": {},
    }


@pytest.fixture
def sample_zotero_annotation() -> Dict[str, Any]:
    return {
        "key": "ANNOT001",
        "version": 10,
        "data": {
            "key": "ANNOT001",
            "itemType": "annotation",
            "parentItem": "ABCD1234",
            "annotationType": "note",
            "annotationComment": "This is a sample annotation comment.",
            "annotationPosition": '{"pageIndex": 0, "rects": [[100, 200, 300, 220]]}',
            "annotationPageLabel": "1",
            "annotationSortIndex": "00000|000000|00000",
            "tags": [{"tag": "za:translate"}],
        },
        "links": {},
    }
