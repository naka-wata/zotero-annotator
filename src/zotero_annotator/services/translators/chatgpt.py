from __future__ import annotations

from dataclasses import dataclass

from zotero_annotator.services.translators.base import TranslationError, TranslationResult, Translator
from zotero_annotator.services.translators.prompts import build_translation_messages


@dataclass(frozen=True)
class ChatGPTTranslator(Translator):
    # Minimal ChatGPT translator skeleton for provider wiring (provider配線用の最小骨組み)
    api_key: str
    model: str
    base_url: str = "https://api.openai.com/v1"
    timeout_seconds: int = 30

    def translate(self, text: str, source_lang: str, target_lang: str) -> TranslationResult:
        # Keep prompt construction stable so later OpenAI-compatible backends can share it.
        build_translation_messages(text=text, source_lang=source_lang, target_lang=target_lang)
        raise TranslationError(
            "temporary",
            "ChatGPT translator backend is configured but not implemented yet",
            provider="chatgpt",
        )
