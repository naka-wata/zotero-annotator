from __future__ import annotations

from dataclasses import dataclass

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from zotero_annotator.services.translators.base import (
    TranslationError,
    TranslationInput,
    TranslationResult,
    Translator,
)
from zotero_annotator.services.translators.llm_common import (
    build_chat_completions_request,
    build_llm_request_headers,
    extract_chat_completion_translation_text,
    normalize_llm_api_error,
)
from zotero_annotator.services.translators.prompts import build_overlap_translation_messages


@dataclass(frozen=True)
class ChatCompletionsTranslator(Translator):
    # Shared translator for OpenAI-compatible chat/completions backends.
    api_key: str
    model: str
    base_url: str = "https://api.openai.com/v1"
    provider: str = "chatgpt"
    provider_label: str = "ChatGPT"
    timeout_seconds: int = 30
    max_retries: int = 3

    def _translate_once(self, *, input: TranslationInput) -> TranslationResult:
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        messages = build_overlap_translation_messages(
            previous_paragraph=input.previous_paragraph,
            current_paragraph=input.current_paragraph,
            next_paragraph=input.next_paragraph,
        )
        payload = build_chat_completions_request(
            model=self.model,
            messages=messages,
        )
        headers = build_llm_request_headers(api_key=self.api_key)

        try:
            resp = httpx.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise TranslationError(
                "temporary",
                f"{self.provider_label} timed out: {exc}",
                provider=self.provider,
            ) from exc
        except httpx.HTTPError as exc:
            raise TranslationError(
                "temporary",
                f"{self.provider_label} connection failed: {exc}",
                provider=self.provider,
            ) from exc

        if resp.status_code >= 400:
            raise normalize_llm_api_error(
                resp,
                provider=self.provider,
                provider_label=self.provider_label,
            )

        try:
            response_payload = resp.json()
        except ValueError as exc:
            raise TranslationError(
                "temporary",
                f"{self.provider_label} returned invalid JSON",
                provider=self.provider,
                status_code=resp.status_code,
            ) from exc

        translated_text = extract_chat_completion_translation_text(
            response_payload,
            provider=self.provider,
            provider_label=self.provider_label,
        )
        return TranslationResult(
            text=translated_text,
            provider=self.provider,
            model=self.model,
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
