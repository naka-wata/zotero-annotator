from __future__ import annotations

import re
from typing import Any

import httpx

from zotero_annotator.services.translators.base import (
    TranslationError,
    TranslationErrorKind,
)

_TRANSLATION_PREFIX_RE = re.compile(
    r"^(?:here is the translation|translation|translated(?:\s+text)?|output)\s*[:：]?\s*",
    re.IGNORECASE,
)


def build_llm_request_headers(*, api_key: str = "") -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
    }
    if api_key.strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"
    return headers


def build_chat_completions_request(
    *,
    model: str,
    messages: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "model": model,
        "messages": messages,
        "temperature": 0,
    }


def extract_chat_completion_translation_text(
    payload: object,
    *,
    provider: str,
    provider_label: str,
) -> str:
    if not isinstance(payload, dict):
        raise TranslationError(
            "temporary",
            f"{provider_label} response was not a JSON object",
            provider=provider,
        )

    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise TranslationError(
            "temporary",
            f"{provider_label} response missing choices",
            provider=provider,
        )

    choice = choices[0]
    if not isinstance(choice, dict):
        raise TranslationError(
            "temporary",
            f"{provider_label} response choice was invalid",
            provider=provider,
        )

    message = choice.get("message")
    if not isinstance(message, dict):
        raise TranslationError(
            "temporary",
            f"{provider_label} response missing message",
            provider=provider,
        )

    return postprocess_translation_text(
        _extract_message_content(
            message,
            provider=provider,
            provider_label=provider_label,
        ),
        provider=provider,
        provider_label=provider_label,
    )


def postprocess_translation_text(
    text: str,
    *,
    provider: str,
    provider_label: str,
) -> str:
    candidate = _unwrap_code_fence(text).strip()
    candidate = _TRANSLATION_PREFIX_RE.sub("", candidate, count=1).strip()
    if not candidate:
        raise TranslationError(
            "temporary",
            f"{provider_label} returned empty translation",
            provider=provider,
        )
    return candidate


def normalize_llm_api_error(
    resp: httpx.Response,
    *,
    provider: str,
    provider_label: str,
) -> TranslationError:
    detail, error_type, error_code = _safe_llm_api_error_detail(resp)
    kind = classify_llm_api_error(
        status_code=resp.status_code,
        detail=detail,
        error_type=error_type,
        error_code=error_code,
    )
    return TranslationError(
        kind,
        f"{provider_label} error ({resp.status_code}): {detail}",
        provider=provider,
        status_code=resp.status_code,
    )


def classify_llm_api_error(
    *,
    status_code: int,
    detail: str = "",
    error_type: str = "",
    error_code: str = "",
) -> TranslationErrorKind:
    tokens = " ".join(part for part in (detail, error_type, error_code) if part).lower()

    if status_code in (401, 403):
        return "auth"
    if status_code == 402:
        return "quota"
    if "insufficient_quota" in tokens or "quota" in tokens or "billing" in tokens:
        return "quota"
    if status_code == 429:
        return "rate_limit"
    if status_code >= 500:
        return "temporary"
    return "temporary"


def _extract_message_content(
    message: dict[str, Any],
    *,
    provider: str,
    provider_label: str,
) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str) and text:
                parts.append(text)
        if parts:
            return "".join(parts)

    refusal = message.get("refusal")
    if isinstance(refusal, str) and refusal.strip():
        raise TranslationError(
            "temporary",
            f"{provider_label} refused the translation request: {refusal.strip()}",
            provider=provider,
        )

    raise TranslationError(
        "temporary",
        f"{provider_label} response missing message content",
        provider=provider,
    )


def _unwrap_code_fence(text: str) -> str:
    candidate = text.strip()
    if not candidate.startswith("```") or not candidate.endswith("```"):
        return text

    lines = candidate.splitlines()
    if len(lines) >= 2 and lines[0].startswith("```") and lines[-1] == "```":
        return "\n".join(lines[1:-1])
    return text


def _safe_llm_api_error_detail(resp: httpx.Response) -> tuple[str, str, str]:
    detail = ""
    error_type = ""
    error_code = ""

    try:
        payload = resp.json()
    except Exception:
        payload = None

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                detail = message.strip()

            error_type_value = error.get("type")
            if isinstance(error_type_value, str) and error_type_value.strip():
                error_type = error_type_value.strip()

            error_code_value = error.get("code")
            if isinstance(error_code_value, str) and error_code_value.strip():
                error_code = error_code_value.strip()

    if detail:
        return detail, error_type, error_code

    text = (resp.text or "").strip()
    return (text[:200] if text else "unknown"), error_type, error_code
