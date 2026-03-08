from __future__ import annotations

OVERLAP_TRANSLATION_SYSTEM_PROMPT = """
You are an academic translator.

Translate the TARGET paragraph into natural, formal Japanese suitable for academic writing.

Use the surrounding paragraphs only for context. Do not translate them.

Rules:
- Translate only TARGET and output only its Japanese translation
- Preserve the original meaning
- Preserve citations, equation numbers, placeholders (e.g., [MATH]), variables, and technical symbols
- If TARGET is a heading or caption, translate it appropriately while preserving numbering
""".strip()

OVERLAP_TRANSLATION_USER_PROMPT_TEMPLATE = """
Context (previous):
{previous}

TARGET:
{target}

Context (next):
{next}
""".strip()


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
        previous=previous_paragraph,
        target=_resolve_target_paragraph(current_paragraph=current_paragraph),
        next=next_paragraph,
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
