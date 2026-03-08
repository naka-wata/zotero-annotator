from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Protocol


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
        status_code: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.provider = provider
        self.status_code = status_code


class Translator(Protocol):
    # Translator interface (翻訳I/F)
    def translate(self, input: TranslationInput) -> TranslationResult: ...
