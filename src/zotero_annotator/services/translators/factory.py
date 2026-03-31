from __future__ import annotations

from zotero_annotator.config import (
    get_chatgpt_runtime,
    get_deepl_runtime,
    get_local_llm_runtime,
    get_translation_runtime,
)
from zotero_annotator.services.translators.base import Translator
from zotero_annotator.services.translators.chat_completions import (
    OpenAICompatibleTranslator,
)
from zotero_annotator.services.translators.deepl import DeepLTranslator
from zotero_annotator.services.translators.ollama import OllamaTranslator


def build_translator() -> Translator:
    runtime = get_translation_runtime()

    if runtime.provider == "deepl":
        deepl = get_deepl_runtime()
        return DeepLTranslator(
            api_key=deepl.api_key,
            api_url=deepl.api_url,
        )

    if runtime.provider == "chatgpt":
        chatgpt = get_chatgpt_runtime()
        return OpenAICompatibleTranslator(
            api_key=chatgpt.api_key,
            model=chatgpt.model,
            base_url=chatgpt.base_url,
        )

    if runtime.provider == "local_llm":
        local_llm = get_local_llm_runtime()
        return OllamaTranslator(
            api_key=local_llm.api_key,
            model=local_llm.model,
            base_url=local_llm.base_url,
            temperature=local_llm.temperature,
            top_p=local_llm.top_p,
        )

    raise RuntimeError(f"Unsupported TRANSLATOR_PROVIDER: {runtime.provider}")
