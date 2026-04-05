from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from zotero_annotator.config import CoreSettings
from zotero_annotator.models.results import ItemResult
from zotero_annotator.services.paragraphs import Paragraph
from zotero_annotator.services.pipeline import _run_self_healing

_MODULE = "zotero_annotator.services.pipeline"


@pytest.fixture
def mock_settings() -> MagicMock:
    settings = MagicMock(spec=CoreSettings)
    settings.dedup_tag_prefix = "para:"
    settings.run_repair_broken_annotations = False
    return settings


def _make_paragraph(text: str = "Sample paragraph.", hash_: str = "abc123") -> Paragraph:
    return Paragraph(text=text, hash=hash_, dedup_hashes=None, coords=[], page=0)


def _call(
    mock_zotero_client: MagicMock,
    mock_settings: MagicMock,
    existing_tags: set[str],
    *,
    dry_run: bool = False,
    delete_broken_annotations: bool = False,
    paragraphs: list[Paragraph] | None = None,
) -> list[str] | ItemResult:
    return _run_self_healing(
        "PDF00001",
        mock_zotero_client,
        mock_settings,
        paragraphs or [],
        None,
        existing_tags,
        dry_run=dry_run,
        delete_broken_annotations=delete_broken_annotations,
        item_key="ITEM0001",
        title="Test Title",
    )


class TestRunSelfHealingDryRun:
    def test_dry_run_returns_empty_warnings(
        self, mock_zotero_client: MagicMock, mock_settings: MagicMock
    ) -> None:
        """dry_run=True のとき何もせず空リストを返す"""
        with patch(f"{_MODULE}.count_broken_annotations") as mock_count:
            result = _call(mock_zotero_client, mock_settings, set(), dry_run=True)

        assert result == []
        mock_count.assert_not_called()


class TestRunSelfHealingNoBroken:
    def test_no_broken_annotations_returns_empty_warnings(
        self, mock_zotero_client: MagicMock, mock_settings: MagicMock
    ) -> None:
        """壊れた注釈がない場合は空のwarningsを返す"""
        with (
            patch(f"{_MODULE}.count_broken_annotations", return_value=(0, 0)),
            patch(f"{_MODULE}.collect_existing_tags") as mock_refresh,
        ):
            result = _call(mock_zotero_client, mock_settings, set())

        assert result == []
        mock_refresh.assert_not_called()

    def test_count_error_falls_back_to_zero(
        self, mock_zotero_client: MagicMock, mock_settings: MagicMock
    ) -> None:
        """count_broken_annotations が HTTP エラーのとき警告を追加して続行する"""
        with (
            patch(
                f"{_MODULE}.count_broken_annotations",
                side_effect=httpx.HTTPError("timeout"),
            ),
            patch(f"{_MODULE}.collect_existing_tags") as mock_refresh,
        ):
            result = _call(mock_zotero_client, mock_settings, set())

        assert isinstance(result, list)
        assert any("count_broken_annotations_failed" in w for w in result)
        mock_refresh.assert_not_called()


class TestRunSelfHealingBrokenDetected:
    def test_broken_annotations_detected_adds_warning(
        self, mock_zotero_client: MagicMock, mock_settings: MagicMock
    ) -> None:
        """壊れた注釈が検出されたとき warnings に検出メッセージが含まれる"""
        with (
            patch(f"{_MODULE}.count_broken_annotations", return_value=(3, 1)),
            patch(f"{_MODULE}.collect_existing_tags", return_value=set()),
        ):
            result = _call(mock_zotero_client, mock_settings, set())

        assert isinstance(result, list)
        assert any("broken_annotations_detected" in w for w in result)
        assert any("total=3" in w for w in result)

    def test_broken_detected_refreshes_existing_tags_inplace(
        self, mock_zotero_client: MagicMock, mock_settings: MagicMock
    ) -> None:
        """broken_total > 0 のとき既存タグが in-place で更新される"""
        existing_tags: set[str] = {"para:old"}
        with (
            patch(f"{_MODULE}.count_broken_annotations", return_value=(1, 0)),
            patch(
                f"{_MODULE}.collect_existing_tags",
                return_value={"para:new1", "para:new2"},
            ),
        ):
            result = _call(mock_zotero_client, mock_settings, existing_tags)

        assert isinstance(result, list)
        assert existing_tags == {"para:new1", "para:new2"}

    def test_refresh_error_returns_item_result(
        self, mock_zotero_client: MagicMock, mock_settings: MagicMock
    ) -> None:
        """修復・削除後のタグ再取得が失敗した場合 ItemResult を返す"""
        with (
            patch(f"{_MODULE}.count_broken_annotations", return_value=(2, 0)),
            patch(
                f"{_MODULE}.collect_existing_tags",
                side_effect=httpx.HTTPError("connection refused"),
            ),
        ):
            result = _call(mock_zotero_client, mock_settings, set())

        assert isinstance(result, ItemResult)
        assert result.skipped_reason is not None
        assert "list_annotations_failed_after_repair_delete" in result.skipped_reason


class TestRunSelfHealingRepair:
    def test_repair_called_when_enabled_and_para_tagged(
        self, mock_zotero_client: MagicMock, mock_settings: MagicMock
    ) -> None:
        """run_repair_broken_annotations=True かつ broken_para_tagged > 0 のとき修復が呼ばれる"""
        mock_settings.run_repair_broken_annotations = True
        paragraphs = [_make_paragraph()]
        with (
            patch(f"{_MODULE}.count_broken_annotations", return_value=(2, 1)),
            patch(
                f"{_MODULE}.repair_broken_annotations_for_pdf",
                return_value=(1, []),
            ) as mock_repair,
            patch(f"{_MODULE}.collect_existing_tags", return_value=set()),
        ):
            result = _call(
                mock_zotero_client,
                mock_settings,
                set(),
                paragraphs=paragraphs,
            )

        mock_repair.assert_called_once()
        assert isinstance(result, list)
        assert any("repaired_broken_annotations=1" in w for w in result)

    def test_repair_not_called_when_no_para_tagged(
        self, mock_zotero_client: MagicMock, mock_settings: MagicMock
    ) -> None:
        """broken_para_tagged == 0 のとき修復は呼ばれない"""
        mock_settings.run_repair_broken_annotations = True
        with (
            patch(f"{_MODULE}.count_broken_annotations", return_value=(2, 0)),
            patch(f"{_MODULE}.repair_broken_annotations_for_pdf") as mock_repair,
            patch(f"{_MODULE}.collect_existing_tags", return_value=set()),
        ):
            _call(mock_zotero_client, mock_settings, set())

        mock_repair.assert_not_called()

    def test_repair_http_error_adds_warning(
        self, mock_zotero_client: MagicMock, mock_settings: MagicMock
    ) -> None:
        """修復中の HTTP エラーは警告として記録され処理を続行する"""
        mock_settings.run_repair_broken_annotations = True
        with (
            patch(f"{_MODULE}.count_broken_annotations", return_value=(2, 1)),
            patch(
                f"{_MODULE}.repair_broken_annotations_for_pdf",
                side_effect=httpx.HTTPError("repair failed"),
            ),
            patch(f"{_MODULE}.collect_existing_tags", return_value=set()),
        ):
            result = _call(mock_zotero_client, mock_settings, set())

        assert isinstance(result, list)
        assert any("repair_broken_annotations_failed" in w for w in result)


class TestRunSelfHealingDelete:
    def test_delete_called_when_flagged_and_broken(
        self, mock_zotero_client: MagicMock, mock_settings: MagicMock
    ) -> None:
        """delete_broken_annotations=True かつ broken_total > 0 のとき削除が呼ばれる"""
        with (
            patch(f"{_MODULE}.count_broken_annotations", return_value=(3, 0)),
            patch(
                f"{_MODULE}.delete_broken_annotations_for_pdf",
                return_value=(3, []),
            ) as mock_delete,
            patch(f"{_MODULE}.collect_existing_tags", return_value=set()),
        ):
            result = _call(
                mock_zotero_client,
                mock_settings,
                set(),
                delete_broken_annotations=True,
            )

        mock_delete.assert_called_once()
        assert isinstance(result, list)
        assert any("deleted_broken_annotations=3" in w for w in result)

    def test_delete_not_called_when_flag_is_false(
        self, mock_zotero_client: MagicMock, mock_settings: MagicMock
    ) -> None:
        """delete_broken_annotations=False のとき削除は呼ばれない"""
        with (
            patch(f"{_MODULE}.count_broken_annotations", return_value=(3, 0)),
            patch(f"{_MODULE}.delete_broken_annotations_for_pdf") as mock_delete,
            patch(f"{_MODULE}.collect_existing_tags", return_value=set()),
        ):
            _call(mock_zotero_client, mock_settings, set(), delete_broken_annotations=False)

        mock_delete.assert_not_called()

    def test_delete_http_error_adds_warning(
        self, mock_zotero_client: MagicMock, mock_settings: MagicMock
    ) -> None:
        """削除中の HTTP エラーは警告として記録され処理を続行する"""
        with (
            patch(f"{_MODULE}.count_broken_annotations", return_value=(2, 0)),
            patch(
                f"{_MODULE}.delete_broken_annotations_for_pdf",
                side_effect=httpx.HTTPError("delete failed"),
            ),
            patch(f"{_MODULE}.collect_existing_tags", return_value=set()),
        ):
            result = _call(
                mock_zotero_client,
                mock_settings,
                set(),
                delete_broken_annotations=True,
            )

        assert isinstance(result, list)
        assert any("delete_broken_annotations_failed" in w for w in result)
