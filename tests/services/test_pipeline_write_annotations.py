from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from zotero_annotator.config import CoreSettings
from zotero_annotator.models.results import ItemResult
from zotero_annotator.services.paragraphs import Paragraph
from zotero_annotator.services.pipeline import _write_and_finalize

_MODULE = "zotero_annotator.services.pipeline"


@pytest.fixture
def mock_settings() -> MagicMock:
    settings = MagicMock(spec=CoreSettings)
    settings.dedup_tag_prefix = "para:"
    settings.z_base_done_tag = "base-done"
    settings.z_done_tag = "translated"
    settings.z_remove_tag = "to-translate"
    return settings


def _make_paragraph(hash_: str = "abc123") -> Paragraph:
    return Paragraph(text="Sample.", hash=hash_, dedup_hashes=None, coords=[], page=0)


def _make_payload(hash_: str = "abc123") -> dict:
    return {
        "annotationType": "note",
        "annotationComment": "test",
        "tags": [{"tag": f"para:{hash_}"}],
    }


def _make_item(item_key: str = "ITEM0001") -> dict:
    return {"key": item_key, "version": 1, "data": {"key": item_key, "tags": []}}


def _call(
    mock_zotero_client: MagicMock,
    mock_settings: MagicMock,
    planned_payloads: list[dict],
    paragraphs: list[Paragraph],
    existing_tags: set[str] | None = None,
    warnings: list[str] | None = None,
    *,
    max_paragraphs: int = 100,
    dry_run: bool = False,
    translator: MagicMock | None = None,
) -> ItemResult:
    return _write_and_finalize(
        planned_payloads,
        paragraphs,
        "ITEM0001",
        "PDF00001",
        "Test Title",
        _make_item(),
        mock_zotero_client,
        mock_settings,
        existing_tags or set(),
        warnings or [],
        max_paragraphs=max_paragraphs,
        dry_run=dry_run,
        translator=translator,
    )


class TestWriteAndFinalizeSuccess:
    def test_create_annotations_success(
        self, mock_zotero_client: MagicMock, mock_settings: MagicMock
    ) -> None:
        """正常系: create_annotations_resilient が成功 → annotations_created が設定される"""
        payloads = [_make_payload()]
        paragraphs = [_make_paragraph()]

        with patch(f"{_MODULE}._create_annotations_resilient", return_value=(1, [])) as mock_create:
            result = _call(mock_zotero_client, mock_settings, payloads, paragraphs)

        mock_create.assert_called_once()
        assert result.annotations_created == 1
        assert result.annotations_planned == 1
        assert result.skipped_reason is None

    def test_dry_run_skips_write(
        self, mock_zotero_client: MagicMock, mock_settings: MagicMock
    ) -> None:
        """dry_run=True のとき書き込みをスキップする"""
        payloads = [_make_payload()]
        paragraphs = [_make_paragraph()]

        with patch(f"{_MODULE}._create_annotations_resilient") as mock_create:
            result = _call(mock_zotero_client, mock_settings, payloads, paragraphs, dry_run=True)

        mock_create.assert_not_called()
        assert result.annotations_created == 0
        assert result.skipped_reason is None

    def test_empty_payloads_skips_write(
        self, mock_zotero_client: MagicMock, mock_settings: MagicMock
    ) -> None:
        """planned_payloads が空のとき書き込みをスキップする"""
        with patch(f"{_MODULE}._create_annotations_resilient") as mock_create:
            result = _call(mock_zotero_client, mock_settings, [], [])

        mock_create.assert_not_called()
        assert result.annotations_created == 0

    def test_partial_failure_returns_created_count(
        self, mock_zotero_client: MagicMock, mock_settings: MagicMock
    ) -> None:
        """部分失敗: 一部の注釈が失敗しても作成済み件数と警告が返る"""
        payloads = [_make_payload("aaa"), _make_payload("bbb")]
        paragraphs = [_make_paragraph("aaa"), _make_paragraph("bbb")]

        with patch(
            f"{_MODULE}._create_annotations_resilient",
            return_value=(1, ["batch_partial_failed index=1"]),
        ):
            result = _call(mock_zotero_client, mock_settings, payloads, paragraphs)

        assert result.annotations_created == 1
        assert result.annotations_planned == 2
        assert any("batch_partial_failed" in w for w in (result.warnings or []))


class TestWriteAndFinalizeError:
    def test_api_error_returns_skipped_result(
        self, mock_zotero_client: MagicMock, mock_settings: MagicMock
    ) -> None:
        """全失敗: HTTPError が発生した場合 skipped_reason 付きの ItemResult を返す"""
        payloads = [_make_payload()]
        paragraphs = [_make_paragraph()]

        with patch(
            f"{_MODULE}._create_annotations_resilient",
            side_effect=httpx.HTTPError("connection error"),
        ):
            result = _call(mock_zotero_client, mock_settings, payloads, paragraphs)

        assert result.skipped_reason is not None
        assert "create_annotations_failed" in result.skipped_reason
        assert result.annotations_created == 0


class TestWriteAndFinalizeTagFinalization:
    def test_tag_finalized_when_all_paragraphs_done(
        self, mock_zotero_client: MagicMock, mock_settings: MagicMock
    ) -> None:
        """全段落が完了済みのとき base-done タグを付与する"""
        paragraphs = [_make_paragraph("abc123")]
        payloads = [_make_payload("abc123")]

        mock_zotero_client.extract_tag_names.return_value = ["to-translate"]
        mock_zotero_client.merge_tags.return_value = ["base-done"]

        with patch(f"{_MODULE}._create_annotations_resilient", return_value=(1, [])):
            result = _call(
                mock_zotero_client, mock_settings, payloads, paragraphs,
                max_paragraphs=100,
            )

        mock_zotero_client.update_item_tags.assert_called_once()
        assert result.annotations_created == 1

    def test_tag_not_finalized_when_max_paragraphs_limits(
        self, mock_zotero_client: MagicMock, mock_settings: MagicMock
    ) -> None:
        """max_paragraphs < len(paragraphs) のとき完了扱いにしない"""
        paragraphs = [_make_paragraph("aaa"), _make_paragraph("bbb")]
        payloads = [_make_payload("aaa")]

        with patch(f"{_MODULE}._create_annotations_resilient", return_value=(1, [])):
            _call(
                mock_zotero_client, mock_settings, payloads, paragraphs,
                max_paragraphs=1,
            )

        mock_zotero_client.update_item_tags.assert_not_called()

    def test_tag_update_error_appends_warning(
        self, mock_zotero_client: MagicMock, mock_settings: MagicMock
    ) -> None:
        """tag_update が HTTPError のとき警告を追加して正常 ItemResult を返す"""
        paragraphs = [_make_paragraph("abc123")]
        payloads = [_make_payload("abc123")]

        mock_zotero_client.extract_tag_names.return_value = ["to-translate"]
        mock_zotero_client.merge_tags.return_value = ["base-done"]
        mock_zotero_client.update_item_tags.side_effect = httpx.HTTPError("tag error")

        with patch(f"{_MODULE}._create_annotations_resilient", return_value=(1, [])):
            result = _call(mock_zotero_client, mock_settings, payloads, paragraphs)

        assert result.skipped_reason is None
        assert any("tag_update_failed" in w for w in (result.warnings or []))
