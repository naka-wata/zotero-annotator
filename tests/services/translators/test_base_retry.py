from __future__ import annotations

import pytest

from zotero_annotator.services.translators.base import (
    BaseRetryTranslator,
    TranslationError,
    TranslationInput,
    TranslationResult,
)

_INPUT = TranslationInput(
    previous_paragraph="",
    current_paragraph="Hello",
    next_paragraph="",
    source_lang="EN",
    target_lang="JA",
)

_OK_RESULT = TranslationResult(text="こんにちは", provider="test")


class _StubTranslator(BaseRetryTranslator):
    # テスト用スタブ: responses リストの要素を順に返す。
    # 要素が Exception なら raise する。
    def __init__(self, max_retries: int, responses: list[TranslationResult | TranslationError]) -> None:
        self.max_retries = max_retries
        self._responses = iter(responses)
        self.call_count = 0

    def _translate_once(self, *, input: TranslationInput) -> TranslationResult:
        self.call_count += 1
        response = next(self._responses)
        if isinstance(response, Exception):
            raise response
        return response


def _temporary_error() -> TranslationError:
    return TranslationError("temporary", "connection error", provider="test")


def _rate_limit_error() -> TranslationError:
    return TranslationError("rate_limit", "rate limited", provider="test")


def _auth_error() -> TranslationError:
    return TranslationError("auth", "unauthorized", provider="test")


def test_temporary_error_triggers_retry() -> None:
    # temporary エラーが 1 回出た後に成功する → 合計 2 回呼ばれる
    translator = _StubTranslator(max_retries=3, responses=[_temporary_error(), _OK_RESULT])
    result = translator.translate(_INPUT)
    assert result == _OK_RESULT
    assert translator.call_count == 2


def test_rate_limit_error_triggers_retry() -> None:
    # rate_limit エラーが 1 回出た後に成功する → 合計 2 回呼ばれる
    translator = _StubTranslator(max_retries=3, responses=[_rate_limit_error(), _OK_RESULT])
    result = translator.translate(_INPUT)
    assert result == _OK_RESULT
    assert translator.call_count == 2


def test_auth_error_does_not_retry() -> None:
    # auth エラーは即座に失敗し、1 回しか呼ばれない
    translator = _StubTranslator(max_retries=3, responses=[_auth_error()])
    with pytest.raises(TranslationError) as exc_info:
        translator.translate(_INPUT)
    assert exc_info.value.kind == "auth"
    assert translator.call_count == 1


def test_exceeding_retry_limit_raises() -> None:
    # リトライ上限（3 回）を超えると最後のエラーが再 raise される
    errors: list[TranslationResult | TranslationError] = [
        _temporary_error(),
        _temporary_error(),
        _temporary_error(),
    ]
    translator = _StubTranslator(max_retries=3, responses=errors)
    with pytest.raises(TranslationError) as exc_info:
        translator.translate(_INPUT)
    assert exc_info.value.kind == "temporary"
    assert translator.call_count == 3


def test_no_retry_when_max_retries_is_one() -> None:
    # max_retries=1 のとき、temporary エラーでもリトライしない
    translator = _StubTranslator(max_retries=1, responses=[_temporary_error()])
    with pytest.raises(TranslationError) as exc_info:
        translator.translate(_INPUT)
    assert exc_info.value.kind == "temporary"
    assert translator.call_count == 1
