from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from zotero_annotator.services.translators.base import (
    TranslationError,
    TranslationInput,
    TranslationResult,
    Translator,
)


@dataclass(frozen=True)
class DeepLTranslator(Translator):
    # Minimal DeepL translator client (DeepL翻訳クライアント最小実装)
    api_key: str
    api_url: str = "https://api-free.deepl.com"
    timeout_seconds: int = 30
    max_retries: int = 3

    def _translate_once(self, *, input: TranslationInput) -> TranslationResult:
        url = f"{self.api_url.rstrip('/')}/v2/translate"
        data = {
            "text": input.current_paragraph,
            "target_lang": input.target_lang,
        }
        if input.source_lang:
            data["source_lang"] = input.source_lang
        headers = {
            # DeepL deprecated legacy form-body auth; use header-based auth.
            # (DeepLはフォーム認証が廃止され、ヘッダー認証が必須)
            "Authorization": f"DeepL-Auth-Key {self.api_key}",
        }

        try:
            resp = httpx.post(url, data=data, headers=headers, timeout=self.timeout_seconds)
        except httpx.TimeoutException as exc:
            raise TranslationError("temporary", f"DeepL timed out: {exc}", provider="deepl") from exc
        except httpx.HTTPError as exc:
            raise TranslationError("temporary", f"DeepL connection failed: {exc}", provider="deepl") from exc

        if resp.status_code >= 400:
            kind = _classify_deepl_error(resp.status_code)
            detail = _safe_deepl_error_detail(resp)
            raise TranslationError(kind, f"DeepL error ({resp.status_code}): {detail}", provider="deepl", status_code=resp.status_code)

        payload = resp.json()
        translations = payload.get("translations") or []
        if not translations or not isinstance(translations, list):
            raise TranslationError("temporary", "DeepL response missing translations", provider="deepl")
        translated_text = (translations[0] or {}).get("text") or ""
        if not translated_text:
            raise TranslationError("temporary", "DeepL returned empty translation", provider="deepl")
        return TranslationResult(text=translated_text, provider="deepl", model="")

    def translate(self, input: TranslationInput) -> TranslationResult:
        # Retry only on temporary/rate-limit errors (temporary/rate_limitのみリトライ)
        @retry(
            retry=retry_if_exception_type(_RetryableDeepLError),
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
            reraise=True,
        )
        def _run() -> TranslationResult:
            try:
                return self._translate_once(input=input)
            except TranslationError as exc:
                if exc.kind in ("temporary", "rate_limit") and self.max_retries > 1:
                    raise _RetryableDeepLError(exc)
                raise

        try:
            return _run()
        except TranslationError as exc:
            raise
        except _RetryableDeepLError as exc:
            raise exc.inner


def _classify_deepl_error(status_code: int):
    # DeepL error classification (DeepLエラー分類)
    if status_code in (401, 403):
        return "auth"
    if status_code == 429:
        return "rate_limit"
    if status_code == 456:
        return "quota"
    if status_code >= 500:
        return "temporary"
    return "temporary"


def _safe_deepl_error_detail(resp: httpx.Response) -> str:
    # Best-effort detail extraction without large dumps (巨大なレスポンスを避けて詳細を抽出)
    try:
        j = resp.json()
        msg = j.get("message") or j.get("error") or ""
        if isinstance(msg, str) and msg.strip():
            return msg.strip()
    except Exception:
        pass
    text = (resp.text or "").strip()
    return text[:200] if text else "unknown"


class _RetryableDeepLError(Exception):
    # Wrapper used to allow tenacity retry on selected TranslationError kinds (tenacity用ラッパ)
    def __init__(self, inner: TranslationError) -> None:
        super().__init__(str(inner))
        self.inner = inner
