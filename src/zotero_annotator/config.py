from __future__ import annotations

from functools import lru_cache
from typing import Literal

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
    run_max_paragraphs_per_item: int = Field(3, alias="RUN_MAX_PARAGRAPHS_PER_ITEM")

    # Logging
    log_level: str = Field("INFO", min_length=1, alias="LOG_LEVEL")

    # Fixed base URL for Zotero API.
    zotero_base_url: str = "https://api.zotero.org"


class TranslationSettings(_BaseEnvSettings):
    # Gemini
    gemini_api_key: str = Field(..., min_length=1, alias="GEMINI_API_KEY")
    gemini_model: str = Field(..., min_length=1, alias="GEMINI_MODEL")
    gemini_concurrency: int = Field(2, alias="GEMINI_CONCURRENCY")
    gemini_timeout_seconds: int = Field(30, alias="GEMINI_TIMEOUT_SECONDS")
    gemini_max_retries: int = Field(3, alias="GEMINI_MAX_RETRIES")
    gemini_quota_stop: bool = Field(True, alias="GEMINI_QUOTA_STOP")
    gemini_quota_exit_code: int = Field(10, alias="GEMINI_QUOTA_EXIT_CODE")
    target_lang: str = Field(..., min_length=1, alias="TARGET_LANG")


class Settings(CoreSettings, TranslationSettings):
    pass


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_core_settings() -> CoreSettings:
    return CoreSettings()


@lru_cache
def get_translation_settings() -> TranslationSettings:
    return TranslationSettings()
