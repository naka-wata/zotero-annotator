from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, ClassVar, Literal, Optional, Union

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

TranslatorProviderInput = Literal["deepl", "chatgpt", "openai", "local_llm"]
TranslatorProvider = Literal["deepl", "chatgpt", "local_llm"]


@dataclass(frozen=True)
class TranslationRuntime:
    provider: TranslatorProvider
    target_lang: str
    source_lang: str = ""


@dataclass(frozen=True)
class DeepLRuntime:
    api_key: str
    api_url: str


@dataclass(frozen=True)
class LLMTranslatorRuntime:
    model: str
    base_url: str
    api_key: str = ""
    temperature: float = 0.0
    top_p: float | None = None


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

    # Extraction params that materially change which paragraphs enter translation.
    # Keep only the high-impact switches/thresholds env-configurable for now.
    # Filter out non-body text by minimum median font size.
    # 0 disables the filter; "auto" derives a threshold from the current PDF.
    para_min_median_coord_h: Union[float, Literal["auto"]] = Field(
        "auto",
        alias="PARA_MIN_MEDIAN_COORD_H",
    )
    para_min_median_coord_h_auto_ratio: float = Field(
        0.8,
        alias="PARA_MIN_MEDIAN_COORD_H_AUTO_RATIO",
    )
    # Skip algorithm/pseudocode blocks (e.g., "Algorithm 1 ...") to avoid noisy notes.
    para_skip_algorithms: bool = Field(True, alias="PARA_SKIP_ALGORITHMS")

    # Locked extraction internals: keep fixed until we intentionally expose them.
    para_merge_splits: ClassVar[bool] = True
    para_formula_placeholder: ClassVar[str] = "[MATH]"
    # Insert newlines around [MATH] (n) tokens for readability.
    para_math_newlines: ClassVar[bool] = True
    # Treat very short connector-only paragraphs (e.g., "where") specially: merge before filtering.
    para_connector_max_chars: ClassVar[int] = 20
    # Strip plot/axis label noise that sometimes appears before "Figure N:" in a paragraph.
    para_strip_plot_axis_prefix: ClassVar[bool] = True
    # Skip figure/table captions as standalone notes (e.g., "Figure 4: ...", "Table 1: ...").
    # If a caption is mixed with prose in the same paragraph, the caption prefix is removed and the prose is kept.
    para_skip_captions: bool = Field(False, alias="PARA_SKIP_CAPTIONS")
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
    translator_provider: TranslatorProviderInput = Field(
        "deepl", alias="TRANSLATOR_PROVIDER"
    )
    target_lang: str = Field(..., min_length=1, alias="TARGET_LANG")
    source_lang: Optional[str] = Field(None, alias="SOURCE_LANG")


class DeepLSettings(_BaseEnvSettings):
    # DeepL API settings (DeepL API設定)
    deepl_api_key: str = Field(..., min_length=1, alias="DEEPL_API_KEY")
    deepl_api_url: str = Field("https://api-free.deepl.com", min_length=1, alias="DEEPL_API_URL")


class ChatGPTSettings(_BaseEnvSettings):
    # OpenAI ChatGPT API settings (OpenAI ChatGPT API設定)
    openai_api_key: str = Field(..., min_length=1, alias="OPENAI_API_KEY")
    openai_model: str = Field(..., min_length=1, alias="OPENAI_MODEL")
    openai_base_url: str = Field("https://api.openai.com/v1", min_length=1, alias="OPENAI_BASE_URL")


class LocalLLMSettings(_BaseEnvSettings):
    # Local LLM settings for an OpenAI-compatible endpoint such as Ollama.
    local_llm_base_url: str = Field(..., min_length=1, alias="LOCAL_LLM_BASE_URL")
    local_llm_model: str = Field(..., min_length=1, alias="LOCAL_LLM_MODEL")
    local_llm_api_key: str = Field("", alias="LOCAL_LLM_API_KEY")
    local_llm_temperature: float = Field(0.1, alias="LOCAL_LLM_TEMPERATURE")
    local_llm_top_p: float = Field(0.9, alias="LOCAL_LLM_TOP_P")


@lru_cache
def get_core_settings() -> CoreSettings:
    return CoreSettings()


@lru_cache
def get_translation_settings() -> TranslatorSettings:
    # Backward compatible name: this returns translator selection + language config.
    return TranslatorSettings()


@lru_cache
def get_translation_runtime() -> TranslationRuntime:
    settings = get_translation_settings()
    return TranslationRuntime(
        provider=_normalize_translator_provider(settings.translator_provider),
        source_lang=(settings.source_lang or "").strip(),
        target_lang=settings.target_lang,
    )


@lru_cache
def get_deepl_settings() -> DeepLSettings:
    return DeepLSettings()


@lru_cache
def get_deepl_runtime() -> DeepLRuntime:
    try:
        settings = get_deepl_settings()
    except ValidationError as exc:
        raise RuntimeError(
            _format_provider_settings_error(
                provider_label="DeepL",
                required_env=("DEEPL_API_KEY",),
                optional_env=("DEEPL_API_URL",),
            )
        ) from exc

    return DeepLRuntime(
        api_key=settings.deepl_api_key,
        api_url=settings.deepl_api_url,
    )


@lru_cache
def get_chatgpt_settings() -> ChatGPTSettings:
    return ChatGPTSettings()


@lru_cache
def get_chatgpt_runtime() -> LLMTranslatorRuntime:
    return _build_llm_runtime(
        load_settings=get_chatgpt_settings,
        provider_label="ChatGPT",
        required_env=("OPENAI_API_KEY", "OPENAI_MODEL"),
        optional_env=("OPENAI_BASE_URL",),
        model_attr="openai_model",
        base_url_attr="openai_base_url",
        api_key_attr="openai_api_key",
    )


@lru_cache
def get_local_llm_settings() -> LocalLLMSettings:
    return LocalLLMSettings()


@lru_cache
def get_local_llm_runtime() -> LLMTranslatorRuntime:
    return _build_llm_runtime(
        load_settings=get_local_llm_settings,
        provider_label="Local LLM",
        required_env=("LOCAL_LLM_BASE_URL", "LOCAL_LLM_MODEL"),
        optional_env=("LOCAL_LLM_API_KEY", "LOCAL_LLM_TEMPERATURE", "LOCAL_LLM_TOP_P"),
        model_attr="local_llm_model",
        base_url_attr="local_llm_base_url",
        api_key_attr="local_llm_api_key",
        temperature_attr="local_llm_temperature",
        top_p_attr="local_llm_top_p",
    )


def _build_llm_runtime(
    *,
    load_settings: Callable[[], _BaseEnvSettings],
    provider_label: str,
    required_env: tuple[str, ...],
    optional_env: tuple[str, ...],
    model_attr: str,
    base_url_attr: str,
    api_key_attr: str,
    temperature_attr: str | None = None,
    top_p_attr: str | None = None,
) -> LLMTranslatorRuntime:
    try:
        settings = load_settings()
    except ValidationError as exc:
        raise RuntimeError(
            _format_provider_settings_error(
                provider_label=provider_label,
                required_env=required_env,
                optional_env=optional_env,
            )
        ) from exc

    return LLMTranslatorRuntime(
        api_key=getattr(settings, api_key_attr),
        model=getattr(settings, model_attr),
        base_url=getattr(settings, base_url_attr),
        temperature=getattr(settings, temperature_attr) if temperature_attr else 0.0,
        top_p=getattr(settings, top_p_attr) if top_p_attr else None,
    )


def _normalize_translator_provider(provider: TranslatorProviderInput) -> TranslatorProvider:
    # Keep openai as a backward-compatible alias for the ChatGPT provider.
    if provider == "openai":
        return "chatgpt"
    return provider


def _format_provider_settings_error(
    *,
    provider_label: str,
    required_env: tuple[str, ...],
    optional_env: tuple[str, ...] = (),
) -> str:
    required_text = ", ".join(required_env)
    message = f"{provider_label} translator settings are incomplete or invalid. Required: {required_text}."
    if optional_env:
        message += f" Optional: {', '.join(optional_env)}."
    return message
