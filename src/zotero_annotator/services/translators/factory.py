from __future__ import annotations

from zotero_annotator.config import get_deepl_settings, get_translation_settings
from zotero_annotator.services.translators.base import Translator
from zotero_annotator.services.translators.deepl import DeepLTranslator


def build_translator() -> Translator:
    settings = get_translation_settings()

    if settings.translator_provider == "deepl":
        deepl = get_deepl_settings()
        return DeepLTranslator(
            api_key=deepl.deepl_api_key,
            api_url=deepl.deepl_api_url,
        )

    # openai is planned but not implemented yet (openaiは後で実装)
    raise RuntimeError("TRANSLATOR_PROVIDER=openai is not implemented yet")

