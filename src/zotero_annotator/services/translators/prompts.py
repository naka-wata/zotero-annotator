from __future__ import annotations

TRANSLATION_SYSTEM_PROMPT = (
    "You are a translation engine. "
    "Translate only the user-provided text. "
    "Do not add explanations, notes, or quotation marks. "
    "Preserve line breaks, [MATH] tokens, and the original structure."
)


def build_translation_system_prompt() -> str:
    return TRANSLATION_SYSTEM_PROMPT


def build_translation_user_prompt(*, text: str, source_lang: str, target_lang: str) -> str:
    source_label = source_lang.strip() or "auto-detected source language"
    target_label = target_lang.strip()
    return (
        f"Source language: {source_label}\n"
        f"Target language: {target_label}\n"
        "Task: Translate the text into the target language.\n"
        "Rules:\n"
        "- Return only the translated text.\n"
        "- Preserve paragraph breaks, [MATH] tokens, and spacing as much as possible.\n"
        "- Do not add commentary or prefixes.\n"
        "<text>\n"
        f"{text}\n"
        "</text>"
    )


def build_translation_messages(*, text: str, source_lang: str, target_lang: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": build_translation_system_prompt()},
        {
            "role": "user",
            "content": build_translation_user_prompt(
                text=text,
                source_lang=source_lang,
                target_lang=target_lang,
            ),
        },
    ]
