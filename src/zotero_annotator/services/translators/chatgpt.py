from __future__ import annotations

from dataclasses import dataclass

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from zotero_annotator.services.translators.base import TranslationError, TranslationResult, Translator
from zotero_annotator.services.translators.llm_common import (
    build_chat_completions_request,
    build_openai_compatible_headers,
    extract_chat_completion_translation_text,
    normalize_openai_compatible_error,
)
from zotero_annotator.services.translators.prompts import build_translation_messages


@dataclass(frozen=True)
class ChatGPTTranslator(Translator):
    # ChatGPT translation backend using the OpenAI-compatible chat/completions API.
    api_key: str
    model: str
    base_url: str = "https://api.openai.com/v1"
    timeout_seconds: int = 30
    max_retries: int = 3

    def _translate_once(self, *, text: str, source_lang: str, target_lang: str) -> TranslationResult:
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        messages = build_translation_messages(
            text=text,
            source_lang=source_lang,
            target_lang=target_lang,
        )
        payload = build_chat_completions_request(
            model=self.model,
            messages=messages,
        )
        headers = build_openai_compatible_headers(api_key=self.api_key)

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
                f"ChatGPT timed out: {exc}",
                provider="chatgpt",
            ) from exc
        except httpx.HTTPError as exc:
            raise TranslationError(
                "temporary",
                f"ChatGPT connection failed: {exc}",
                provider="chatgpt",
            ) from exc

        if resp.status_code >= 400:
            raise normalize_openai_compatible_error(
                resp,
                provider="chatgpt",
                provider_label="ChatGPT",
            )

        try:
            response_payload = resp.json()
        except ValueError as exc:
            raise TranslationError(
                "temporary",
                "ChatGPT returned invalid JSON",
                provider="chatgpt",
                status_code=resp.status_code,
            ) from exc

        translated_text = extract_chat_completion_translation_text(
            response_payload,
            provider="chatgpt",
            provider_label="ChatGPT",
        )
        return TranslationResult(
            text=translated_text,
            provider="chatgpt",
            model=self.model,
        )

    def translate(self, text: str, source_lang: str, target_lang: str) -> TranslationResult:
        @retry(
            retry=retry_if_exception_type(_RetryableChatGPTError),
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
            reraise=True,
        )
        def _run() -> TranslationResult:
            try:
                return self._translate_once(
                    text=text,
                    source_lang=source_lang,
                    target_lang=target_lang,
                )
            except TranslationError as exc:
                if exc.kind in ("temporary", "rate_limit") and self.max_retries > 1:
                    raise _RetryableChatGPTError(exc)
                raise

        try:
            return _run()
        except TranslationError:
            raise
        except _RetryableChatGPTError as exc:
            raise exc.inner


class _RetryableChatGPTError(Exception):
    def __init__(self, inner: TranslationError) -> None:
        super().__init__(str(inner))
        self.inner = inner
