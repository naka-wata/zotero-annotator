from __future__ import annotations

from dataclasses import dataclass

from zotero_annotator.services.translators.base import (
    BaseRetryTranslator,
    TranslationInput,
    TranslationResult,
)
from zotero_annotator.services.translators.llm_common import (
    request_chat_completions_translation,
)


@dataclass(frozen=True)
class OpenAICompatibleTranslator(BaseRetryTranslator):
    # Shared translator for OpenAI-compatible chat/completions backends.
    api_key: str
    model: str
    base_url: str = "https://api.openai.com/v1"
    provider: str = "chatgpt"
    provider_label: str = "ChatGPT"
    timeout_seconds: int = 30
    max_retries: int = 3
    connection_failure_hint: str = ""
    temperature: float = 0.0
    top_p: float | None = None

    def _translate_once(self, *, input: TranslationInput) -> TranslationResult:
        return request_chat_completions_translation(
            api_key=self.api_key,
            model=self.model,
            base_url=self.base_url,
            input=input,
            provider=self.provider,
            provider_label=self.provider_label,
            timeout_seconds=self.timeout_seconds,
            connection_failure_hint=self.connection_failure_hint,
            temperature=self.temperature,
            top_p=self.top_p,
        )
