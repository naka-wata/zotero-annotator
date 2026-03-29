from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from zotero_annotator.config import CoreSettings
from zotero_annotator.services.translators.base import TranslationError, TranslationResult
from zotero_annotator.services.pipeline import _translate_pending_annotations


@pytest.fixture
def mock_settings() -> MagicMock:
    settings = MagicMock(spec=CoreSettings)
    settings.ann_translated_tag = "za:translated"
    settings.ann_pending_translation_tag = "za:translate"
    settings.dedup_tag_prefix = "para:"
    return settings


def _make_annotation(
    key: str = "ANN00001",
    tags: list[str] | None = None,
    body: str = "Source text.",
    version: int = 1,
) -> dict:
    if tags is None:
        tags = ["za:translate"]
    return {
        "key": key,
        "version": version,
        "data": {
            "key": key,
            "itemType": "annotation",
            "annotationType": "note",
            "annotationComment": body,
            "tags": [{"tag": t} for t in tags],
        },
    }


def _call(
    annotations: list,
    mock_zotero_client: MagicMock,
    mock_settings: MagicMock,
    mock_translator: MagicMock,
    *,
    write_enabled: bool = False,
) -> tuple[list[str], list[str], dict]:
    mock_zotero_client.extract_tag_names.side_effect = (
        lambda ann: [t["tag"] for t in (ann.get("data") or {}).get("tags", [])]
    )
    return _translate_pending_annotations(
        annotations=annotations,
        translator=mock_translator,
        settings=mock_settings,
        write_enabled=write_enabled,
        zotero=mock_zotero_client,
        item_key="ITEM0001",
        source_lang="en",
        target_lang="ja",
    )


class TestTranslatePendingAnnotations:
    def test_pending_annotation_is_translated(
        self, mock_zotero_client: MagicMock, mock_settings: MagicMock, mock_translator: MagicMock
    ) -> None:
        """`za:translate` タグ付き注釈が翻訳されて stats に反映される"""
        annotations = [_make_annotation(tags=["za:translate"])]
        warnings, errors, stats = _call(annotations, mock_zotero_client, mock_settings, mock_translator)

        assert errors == []
        assert stats["targeted"] == 1
        assert stats["processed"] == 1
        mock_translator.translate.assert_called_once()

    def test_already_translated_annotation_is_skipped(
        self, mock_zotero_client: MagicMock, mock_settings: MagicMock, mock_translator: MagicMock
    ) -> None:
        """`za:translated` タグ付き注釈はスキップされる"""
        annotations = [_make_annotation(tags=["za:translated"])]
        warnings, errors, stats = _call(annotations, mock_zotero_client, mock_settings, mock_translator)

        assert errors == []
        assert stats["targeted"] == 0
        assert stats["skipped_already_translated"] == 1
        mock_translator.translate.assert_not_called()
        assert any("skipped_already_translated" in w for w in warnings)

    def test_annotation_without_pending_tag_is_skipped(
        self, mock_zotero_client: MagicMock, mock_settings: MagicMock, mock_translator: MagicMock
    ) -> None:
        """翻訳タグなし注釈はスキップされる"""
        annotations = [_make_annotation(tags=[])]
        warnings, errors, stats = _call(annotations, mock_zotero_client, mock_settings, mock_translator)

        assert errors == []
        assert stats["targeted"] == 0
        assert stats["skipped_non_pending"] == 1
        mock_translator.translate.assert_not_called()
        assert any("skipped_without_pending_tag" in w for w in warnings)

    def test_translation_error_is_collected_in_errors(
        self, mock_zotero_client: MagicMock, mock_settings: MagicMock, mock_translator: MagicMock
    ) -> None:
        """翻訳エラー発生時は errors に追加されてループが止まる"""
        mock_translator.translate.side_effect = TranslationError(
            message="quota exceeded", kind="rate_limit", status_code=429
        )
        annotations = [_make_annotation(tags=["za:translate"])]
        warnings, errors, stats = _call(annotations, mock_zotero_client, mock_settings, mock_translator)

        assert len(errors) == 1
        assert "translation_failed" in errors[0]
        assert stats["processed"] == 0

    def test_unexpected_exception_collected_in_errors(
        self, mock_zotero_client: MagicMock, mock_settings: MagicMock, mock_translator: MagicMock
    ) -> None:
        """予期しない例外も errors に記録される"""
        mock_translator.translate.side_effect = RuntimeError("unexpected")
        annotations = [_make_annotation(tags=["za:translate"])]
        warnings, errors, stats = _call(annotations, mock_zotero_client, mock_settings, mock_translator)

        assert len(errors) == 1
        assert "translation_unexpected_error" in errors[0]

    def test_empty_source_text_adds_warning(
        self, mock_zotero_client: MagicMock, mock_settings: MagicMock, mock_translator: MagicMock
    ) -> None:
        """本文が空の注釈は翻訳されず warning に記録される"""
        annotations = [_make_annotation(tags=["za:translate"], body="")]
        warnings, errors, stats = _call(annotations, mock_zotero_client, mock_settings, mock_translator)

        assert errors == []
        assert stats["processed"] == 0
        assert any("empty_source" in w for w in warnings)
        mock_translator.translate.assert_not_called()
