from __future__ import annotations

from functools import lru_cache
from typing import ClassVar, Literal, Optional, Union

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
    z_base_done_tag: str = Field("base-done", min_length=1, alias="Z_BASE_DONE_TAG")
    z_done_tag: str = Field("translated", min_length=1, alias="Z_DONE_TAG")
    z_remove_tag: str = Field("to-translate", min_length=1, alias="Z_REMOVE_TAG")
    ann_pending_translation_tag: str = Field(
        "za:translate", min_length=1, alias="ANN_PENDING_TRANSLATION_TAG"
    )
    ann_translated_tag: str = Field(
        "za:translated", min_length=1, alias="ANN_TRANSLATED_TAG"
    )

    # Pipeline
    dedup_tag_prefix: str = "para:"
    para_min_chars: int = Field(60, alias="PARA_MIN_CHARS")
    para_max_chars: int = Field(1500, alias="PARA_MAX_CHARS")
    # Filter out non-body text like plot axis labels by coordinate height (h).
    # 0 disables the filter. Typical body lines are ~8-10 in this PDF.
    para_min_median_coord_h: ClassVar[Union[float, Literal["auto"]]] = "auto"
    para_min_median_coord_h_auto_ratio: ClassVar[float] = 0.8
    para_merge_splits: ClassVar[bool] = True
    para_formula_placeholder: ClassVar[str] = "[MATH]"
    # Insert newlines around [MATH] (n) tokens for readability.
    para_math_newlines: ClassVar[bool] = True
    # Treat very short connector-only paragraphs (e.g., "where") specially: merge before filtering.
    para_connector_max_chars: ClassVar[int] = 20
    # Skip algorithm/pseudocode blocks (e.g., "Algorithm 1 ...") to avoid noisy notes.
    para_skip_algorithms: ClassVar[bool] = True
    # Strip plot/axis label noise that sometimes appears before "Figure N:" in a paragraph.
    para_strip_plot_axis_prefix: ClassVar[bool] = True
    # Skip figure/table captions as standalone notes (e.g., "Figure 4: ...", "Table 1: ...").
    # If a caption is mixed with prose in the same paragraph, the caption prefix is removed and the prose is kept.
    para_skip_captions: ClassVar[bool] = True
    # Drop inline citation markers like "[23]" or "[3, 4]" from extracted text.
    # Default: keep citations in body text.
    para_drop_citations: bool = Field(False, alias="PARA_DROP_CITATIONS")
    # Drop footnote markers like "layer1." -> "layer." (only when it looks like a footnote marker).
    # Default: keep as-is (some papers use it as meaningful index).
    para_drop_footnote_markers: bool = Field(False, alias="PARA_DROP_FOOTNOTE_MARKERS")
    # Skip references/bibliography section paragraphs (and anything after a "References" heading).
    para_skip_references: bool = Field(True, alias="PARA_SKIP_REFERENCES")
    # Skip table-body-like paragraphs (dense numeric / short tokens), since tables are usually not
    # helpful as note annotations. Captions are handled separately.
    para_skip_table_like: bool = Field(True, alias="PARA_SKIP_TABLE_LIKE")

    # Annotation output mode (what to create in Zotero)
    # - note: create note annotations (default)
    # - highlight: create a small fixed highlight rectangle (debug / minimal marking)
    annotation_mode: ClassVar[Literal["note", "highlight"]] = "note"
    run_max_paragraphs_per_item: ClassVar[int] = 100
    run_delete_broken_annotations: ClassVar[bool] = True
    run_repair_broken_annotations: ClassVar[bool] = True

    # Logging
    log_level: ClassVar[str] = "INFO"

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
