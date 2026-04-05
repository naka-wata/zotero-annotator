from __future__ import annotations

import re
from typing import Any

import httpx

from zotero_annotator.services.translators.base import (
    TranslationError,
    TranslationErrorKind,
    TranslationInput,
    TranslationResult,
)
from zotero_annotator.services.translators.prompts import (
    build_overlap_translation_messages,
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
    temperature: float = 0.0,
    top_p: float | None = None,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if top_p is not None:
        payload["top_p"] = top_p
    return payload


def build_chat_completions_url(*, base_url: str) -> str:
    return f"{base_url.rstrip('/')}/chat/completions"


def build_overlap_translation_request(
    *,
    model: str,
    input: TranslationInput,
    provider: str,
    provider_label: str,
    temperature: float = 0.0,
    top_p: float | None = None,
) -> dict[str, Any]:
    try:
        messages = build_overlap_translation_messages(
            previous_paragraph=input.previous_paragraph,
            current_paragraph=input.current_paragraph,
            next_paragraph=input.next_paragraph,
        )
    except ValueError as exc:
        raise TranslationError(
            "temporary",
            f"{provider_label} translation request was invalid: {exc}",
            provider=provider,
        ) from exc

    return build_chat_completions_request(
        model=model,
        messages=messages,
        temperature=temperature,
        top_p=top_p,
    )


def request_chat_completions_translation(
    *,
    api_key: str,
    model: str,
    base_url: str,
    input: TranslationInput,
    provider: str,
    provider_label: str,
    timeout_seconds: int,
    connection_failure_hint: str = "",
    temperature: float = 0.0,
    top_p: float | None = None,
) -> TranslationResult:
    url = build_chat_completions_url(base_url=base_url)
    payload = build_overlap_translation_request(
        model=model,
        input=input,
        provider=provider,
        provider_label=provider_label,
        temperature=temperature,
        top_p=top_p,
    )
    headers = build_llm_request_headers(api_key=api_key)

    try:
        resp = httpx.post(
            url,
            json=payload,
            headers=headers,
            timeout=timeout_seconds,
        )
    except httpx.TimeoutException as exc:
        raise TranslationError(
            "temporary",
            _format_transport_error_message(
                provider_label=provider_label,
                detail=f"timed out after {timeout_seconds}s",
                endpoint_url=url,
                exception=exc,
                connection_failure_hint=connection_failure_hint,
            ),
            provider=provider,
        ) from exc
    except httpx.ConnectError as exc:
        raise TranslationError(
            "temporary",
            _format_transport_error_message(
                provider_label=provider_label,
                detail="connection failed",
                endpoint_url=url,
                exception=exc,
                connection_failure_hint=connection_failure_hint,
            ),
            provider=provider,
        ) from exc
    except httpx.HTTPError as exc:
        raise TranslationError(
            "temporary",
            _format_transport_error_message(
                provider_label=provider_label,
                detail="request failed",
                endpoint_url=url,
                exception=exc,
                connection_failure_hint=connection_failure_hint,
            ),
            provider=provider,
        ) from exc

    if resp.status_code >= 400:
        raise normalize_llm_api_error(
            resp,
            provider=provider,
            provider_label=provider_label,
        )

    try:
        response_payload = resp.json()
    except ValueError as exc:
        raise TranslationError(
            "temporary",
            f"{provider_label} returned invalid JSON",
            provider=provider,
            status_code=resp.status_code,
        ) from exc

    translated_text = extract_chat_completion_translation_text(
        response_payload,
        provider=provider,
        provider_label=provider_label,
    )
    return TranslationResult(
        text=translated_text,
        provider=provider,
        model=model,
    )


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


def _format_transport_error_message(
    *,
    provider_label: str,
    detail: str,
    endpoint_url: str,
    exception: Exception,
    connection_failure_hint: str,
) -> str:
    message = f"{provider_label} {detail} while calling {endpoint_url}: {exception}"
    if connection_failure_hint:
        message = f"{message}. {connection_failure_hint}"
    return message
