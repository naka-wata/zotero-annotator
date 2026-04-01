from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal, Protocol

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


@dataclass(frozen=True)
class TranslationInput:
    # Translation request with paragraph context (前後段落を含む翻訳入力)
    previous_paragraph: str
    current_paragraph: str
    next_paragraph: str
    source_lang: str
    target_lang: str


@dataclass(frozen=True)
class TranslationResult:
    # Translation output (翻訳結果)
    text: str
    provider: str
    model: str = ""


TranslationErrorKind = Literal["quota", "auth", "rate_limit", "temporary"]


class TranslationError(RuntimeError):
    # Unified translation error (翻訳エラーの共通例外)
    def __init__(
        self,
        kind: TranslationErrorKind,
        message: str,
        *,
        provider: str = "",
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.provider = provider
        self.status_code = status_code


class Translator(Protocol):
    # Translator interface (翻訳I/F)
    def translate(self, input: TranslationInput) -> TranslationResult: ...


class _RetryableError(Exception):
    # Wrapper used to allow tenacity retry on selected TranslationError kinds (tenacity用ラッパ)
    def __init__(self, inner: TranslationError) -> None:
        super().__init__(str(inner))
        self.inner = inner


class BaseRetryTranslator:
    # Base class providing shared retry logic for translator implementations (リトライ処理の共通基底クラス)
    max_retries: int

    def translate(self, input: TranslationInput) -> TranslationResult:
        return self._with_retry(lambda: self._translate_once(input=input))

    def _translate_once(self, *, input: TranslationInput) -> TranslationResult:
        raise NotImplementedError

    def _with_retry(self, fn: Callable[[], TranslationResult]) -> TranslationResult:
        @retry(
            retry=retry_if_exception_type(_RetryableError),
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
            reraise=True,
        )
        def _run() -> TranslationResult:
            try:
                return fn()
            except TranslationError as exc:
                if exc.kind in ("temporary", "rate_limit") and self.max_retries > 1:
                    raise _RetryableError(exc)
                raise

        try:
            return _run()
        except TranslationError:
            raise
        except _RetryableError as exc:
            raise exc.inner
