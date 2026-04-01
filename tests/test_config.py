"""config.py のバリデーションテスト."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from zotero_annotator.config import ParagraphExtractionSettings, ZoteroSettings


class TestParagraphExtractionSettings:
    """ParagraphExtractionSettings のバリデーションテスト."""

    def _valid_kwargs(self) -> dict:
        return {}  # デフォルト値ですべて有効

    def test_default_values_are_valid(self) -> None:
        # .env が読み込まれる環境でも para_min_chars <= para_max_chars を確認する
        s = ParagraphExtractionSettings()
        assert s.para_min_chars <= s.para_max_chars

    def test_valid_range(self) -> None:
        s = ParagraphExtractionSettings(PARA_MIN_CHARS=100, PARA_MAX_CHARS=500)
        assert s.para_min_chars == 100
        assert s.para_max_chars == 500

    def test_equal_min_max_is_valid(self) -> None:
        s = ParagraphExtractionSettings(PARA_MIN_CHARS=200, PARA_MAX_CHARS=200)
        assert s.para_min_chars == 200

    def test_min_greater_than_max_raises(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ParagraphExtractionSettings(PARA_MIN_CHARS=500, PARA_MAX_CHARS=100)
        assert "PARA_MIN_CHARS" in str(exc_info.value)
        assert "PARA_MAX_CHARS" in str(exc_info.value)


class TestZoteroSettings:
    """ZoteroSettings のバリデーションテスト."""

    def _valid_kwargs(self) -> dict:
        return {
            "Z_SCOPE": "user",
            "Z_ID": "12345",
            "Z_API_KEY": "real_api_key",
        }

    def test_valid_settings(self) -> None:
        s = ZoteroSettings(**self._valid_kwargs())
        assert s.z_scope == "user"
        assert s.z_id == "12345"

    def test_placeholder_z_id_raises(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["Z_ID"] = "..."
        with pytest.raises(ValidationError) as exc_info:
            ZoteroSettings(**kwargs)
        assert "Z_ID" in str(exc_info.value)

    def test_placeholder_z_api_key_raises(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["Z_API_KEY"] = "..."
        with pytest.raises(ValidationError) as exc_info:
            ZoteroSettings(**kwargs)
        assert "Z_API_KEY" in str(exc_info.value)

    def test_both_placeholders_raises(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["Z_ID"] = "..."
        kwargs["Z_API_KEY"] = "..."
        with pytest.raises(ValidationError) as exc_info:
            ZoteroSettings(**kwargs)
        error_str = str(exc_info.value)
        assert "Z_ID" in error_str
        assert "Z_API_KEY" in error_str
