from __future__ import annotations

from dataclasses import dataclass

from zotero_annotator.services.translators.chat_completions import (
    OpenAICompatibleTranslator,
)


@dataclass(frozen=True)
class OllamaTranslator(OpenAICompatibleTranslator):
    # Local translator backed by Ollama's OpenAI-compatible chat/completions API.
    provider: str = "local_llm"
    provider_label: str = "Ollama"
    timeout_seconds: int = 120
    connection_failure_hint: str = (
        "Confirm the Ollama server is running and LOCAL_LLM_BASE_URL points to its OpenAI-compatible /v1 endpoint"
    )
