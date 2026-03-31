from __future__ import annotations

from dataclasses import dataclass

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from zotero_annotator.services.translators.base import (
    TranslationError,
    TranslationInput,
    TranslationResult,
    Translator,
)
from zotero_annotator.services.translators.llm_common import (
    request_chat_completions_translation,
)


@dataclass(frozen=True)
class OpenAICompatibleTranslator(Translator):
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

    def translate(self, input: TranslationInput) -> TranslationResult:
        @retry(
            retry=retry_if_exception_type(_RetryableLLMError),
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
            reraise=True,
        )
        def _run() -> TranslationResult:
            try:
                return self._translate_once(input=input)
            except TranslationError as exc:
                if exc.kind in ("temporary", "rate_limit") and self.max_retries > 1:
                    raise _RetryableLLMError(exc)
                raise

        try:
            return _run()
        except TranslationError:
            raise
        except _RetryableLLMError as exc:
            raise exc.inner


class _RetryableLLMError(Exception):
    def __init__(self, inner: TranslationError) -> None:
        super().__init__(str(inner))
        self.inner = inner
