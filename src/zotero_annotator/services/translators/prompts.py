from __future__ import annotations

OVERLAP_TRANSLATION_SYSTEM_PROMPT = (
    "You are a professional academic translator for paper annotation.\n\n"
    "Translate only the TARGET paragraph into natural, formal Japanese suitable for academic writing.\n\n"
    "Use the surrounding paragraphs only to understand context.\n"
    "Do not translate the surrounding paragraphs.\n\n"
    "Rules:\n"
    "- Translate only the TARGET paragraph\n"
    "- Return only the Japanese translation of TARGET\n"
    "- Do not add explanations, notes, summaries, headers, labels, or quotation marks\n"
    "- Preserve the original meaning, nuance, and logical structure\n"
    "- Do not omit or add information\n"
    "- Keep terminology consistent with the surrounding context\n"
    "- Preserve citations such as [12], [3, 4], years, equation numbers such as (1), and section numbers\n"
    "- Preserve placeholders and special tokens exactly, including [MATH]\n"
    "- Preserve variable names, symbols, and technical notation when they should remain unchanged\n"
    "- If TARGET is a heading, caption, or short label, translate it appropriately while preserving numbering\n"
    "- Keep sentence and paragraph boundaries as naturally as possible in Japanese"
)

OVERLAP_TRANSLATION_USER_PROMPT_TEMPLATE = (
    "Context (previous):\n"
    "{previous_paragraph}\n\n"
    "TARGET:\n"
    "{current_paragraph}\n\n"
    "Context (next):\n"
    "{next_paragraph}\n\n"
    "Output:\n"
    "Japanese translation of TARGET only."
)


def _resolve_target_paragraph(*, current_paragraph: str | None = None, text: str | None = None) -> str:
    target_paragraph = current_paragraph if current_paragraph is not None else text
    if target_paragraph is None or not target_paragraph.strip():
        raise ValueError("current_paragraph must not be empty")
    return target_paragraph


def build_overlap_translation_system_prompt() -> str:
    return OVERLAP_TRANSLATION_SYSTEM_PROMPT


def build_overlap_translation_user_prompt(
    *,
    current_paragraph: str,
    previous_paragraph: str = "",
    next_paragraph: str = "",
) -> str:
    return OVERLAP_TRANSLATION_USER_PROMPT_TEMPLATE.format(
        previous_paragraph=previous_paragraph,
        current_paragraph=_resolve_target_paragraph(current_paragraph=current_paragraph),
        next_paragraph=next_paragraph,
    )


def build_overlap_translation_messages(
    *,
    current_paragraph: str,
    previous_paragraph: str = "",
    next_paragraph: str = "",
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": build_overlap_translation_system_prompt()},
        {
            "role": "user",
            "content": build_overlap_translation_user_prompt(
                previous_paragraph=previous_paragraph,
                current_paragraph=current_paragraph,
                next_paragraph=next_paragraph,
            ),
        },
    ]


def build_translation_system_prompt() -> str:
    return build_overlap_translation_system_prompt()


def build_translation_user_prompt(
    *,
    text: str | None = None,
    source_lang: str = "",
    target_lang: str = "",
    current_paragraph: str | None = None,
    previous_paragraph: str = "",
    next_paragraph: str = "",
) -> str:
    _ = source_lang, target_lang
    return build_overlap_translation_user_prompt(
        previous_paragraph=previous_paragraph,
        current_paragraph=_resolve_target_paragraph(
            current_paragraph=current_paragraph,
            text=text,
        ),
        next_paragraph=next_paragraph,
    )


def build_translation_messages(
    *,
    text: str | None = None,
    source_lang: str = "",
    target_lang: str = "",
    current_paragraph: str | None = None,
    previous_paragraph: str = "",
    next_paragraph: str = "",
) -> list[dict[str, str]]:
    _ = source_lang, target_lang
    return build_overlap_translation_messages(
        previous_paragraph=previous_paragraph,
        current_paragraph=_resolve_target_paragraph(
            current_paragraph=current_paragraph,
            text=text,
        ),
        next_paragraph=next_paragraph,
    )
