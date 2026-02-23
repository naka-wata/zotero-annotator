from __future__ import annotations

from functools import lru_cache
from typing import Literal, Optional, Union

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class _BaseEnvSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",            # .env から設定を読み込む
        env_file_encoding="utf-8",  # .env を UTF-8 で読み込む
        case_sensitive=False,       # 環境変数名の大文字小文字を区別しない
        extra="ignore",             # 未使用の環境変数は無視する
    )


class CoreSettings(_BaseEnvSettings):
    # .env から設定項目を読み込む
    # 必須設定の場合は ... を指定し、デフォルト値がある場合は適宜設定する

    # Zotero
    z_scope: Literal["user", "group"] = Field(..., alias="Z_SCOPE")
    z_id: str = Field(..., min_length=1, alias="Z_ID")
    z_api_key: str = Field(..., min_length=1, alias="Z_API_KEY")
    z_target_tag: str = Field("to-translate", min_length=1, alias="Z_TARGET_TAG")
    z_done_tag: str = Field("translated", min_length=1, alias="Z_DONE_TAG")
    z_remove_tag: str = Field("to-translate", min_length=1, alias="Z_REMOVE_TAG")
    z_in_progress_tag: str = Field("translating", min_length=1, alias="Z_IN_PROGRESS_TAG")

    # GROBID
    grobid_url: str = Field(..., min_length=1, alias="GROBID_URL")
    grobid_timeout_seconds: int = Field(60, alias="GROBID_TIMEOUT_SECONDS")

    # Pipeline
    dedup_tag_prefix: str = "para:"
    para_min_chars: int = Field(60, alias="PARA_MIN_CHARS")
    para_max_chars: int = Field(1500, alias="PARA_MAX_CHARS")
    # Filter out non-body text like plot axis labels by coordinate height (h).
    # 0 disables the filter. Typical body lines are ~8-10 in this PDF.
    para_min_median_coord_h: Union[float, Literal["auto"]] = Field(0.0, alias="PARA_MIN_MEDIAN_COORD_H")
    # When PARA_MIN_MEDIAN_COORD_H=auto, compute threshold as (q75 * ratio).
    para_min_median_coord_h_auto_ratio: float = Field(0.7, alias="PARA_MIN_MEDIAN_COORD_H_AUTO_RATIO")
    para_merge_splits: bool = Field(False, alias="PARA_MERGE_SPLITS")
    para_formula_placeholder: str = Field("[MATH]", min_length=1, alias="PARA_FORMULA_PLACEHOLDER")
    # Insert newlines around [MATH] (n) tokens for readability.
    para_math_newlines: bool = Field(False, alias="PARA_MATH_NEWLINES")
    # Treat very short connector-only paragraphs (e.g., "where") specially: merge before filtering.
    para_connector_max_chars: int = Field(20, ge=1, alias="PARA_CONNECTOR_MAX_CHARS")
    # Skip algorithm/pseudocode blocks (e.g., "Algorithm 1 ...") to avoid noisy notes.
    para_skip_algorithms: bool = Field(False, alias="PARA_SKIP_ALGORITHMS")
    # Strip plot/axis label noise that sometimes appears before "Figure N:" in a paragraph.
    para_strip_plot_axis_prefix: bool = Field(False, alias="PARA_STRIP_PLOT_AXIS_PREFIX")
    # Skip figure/table captions as standalone notes (e.g., "Figure 4: ...", "Table 1: ...").
    # If a caption is mixed with prose in the same paragraph, the caption prefix is removed and the prose is kept.
    para_skip_captions: bool = Field(False, alias="PARA_SKIP_CAPTIONS")

    # Annotation output mode (what to create in Zotero)
    # - note: create note annotations (default)
    # - highlight: create a small fixed highlight rectangle (debug / minimal marking)
    annotation_mode: Literal["note", "highlight"] = Field("note", alias="ANNOTATION_MODE")
    run_max_paragraphs_per_item: int = Field(3, alias="RUN_MAX_PARAGRAPHS_PER_ITEM")
    run_delete_broken_annotations: bool = Field(False, alias="RUN_DELETE_BROKEN_ANNOTATIONS")
    run_repair_broken_annotations: bool = Field(True, alias="RUN_REPAIR_BROKEN_ANNOTATIONS")

    # Logging
    log_level: str = Field("INFO", min_length=1, alias="LOG_LEVEL")

    # Fixed base URL for Zotero API.
    zotero_base_url: str = "https://api.zotero.org"


class TranslatorSettings(_BaseEnvSettings):
    # Translator selection and language settings (翻訳プロバイダ選択と言語設定)
    translator_provider: Literal["deepl", "openai"] = Field(
        "deepl", alias="TRANSLATOR_PROVIDER"
    )
    target_lang: str = Field(..., min_length=1, alias="TARGET_LANG")
    source_lang: Optional[str] = Field(None, alias="SOURCE_LANG")


class DeepLSettings(_BaseEnvSettings):
    # DeepL API settings (DeepL API設定)
    deepl_api_key: str = Field(..., min_length=1, alias="DEEPL_API_KEY")
    deepl_api_url: str = Field("https://api-free.deepl.com", min_length=1, alias="DEEPL_API_URL")


@lru_cache
def get_core_settings() -> CoreSettings:
    return CoreSettings()


@lru_cache
def get_translation_settings() -> TranslatorSettings:
    # Backward compatible name: this returns translator selection + language config.
    return TranslatorSettings()


@lru_cache
def get_deepl_settings() -> DeepLSettings:
    return DeepLSettings()
