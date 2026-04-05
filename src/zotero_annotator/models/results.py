from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ItemResult:
    item_key: str
    title: str
    pdf_key: str | None

    paragraphs_total: int
    paragraphs_skipped_duplicate: int
    paragraphs_processed: int

    annotations_planned: int
    annotations_created: int

    skipped_reason: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class TranslationItemResult:
    item_key: str
    title: str
    pdf_key: str | None

    annotations_total: int
    annotations_targeted: int
    annotations_processed: int
    annotations_updated: int

    skipped_reason: str | None = None
    warnings: list[str] = field(default_factory=list)


def make_skipped_item_result(
    item_key: str,
    title: str,
    pdf_key: str | None,
    reason: str,
) -> ItemResult:
    return ItemResult(
        item_key=item_key,
        title=title,
        pdf_key=pdf_key,
        paragraphs_total=0,
        paragraphs_skipped_duplicate=0,
        paragraphs_processed=0,
        annotations_planned=0,
        annotations_created=0,
        skipped_reason=reason,
    )


def make_skipped_translation_result(
    item_key: str,
    title: str,
    pdf_key: str | None,
    reason: str,
) -> TranslationItemResult:
    return TranslationItemResult(
        item_key=item_key,
        title=title,
        pdf_key=pdf_key,
        annotations_total=0,
        annotations_targeted=0,
        annotations_processed=0,
        annotations_updated=0,
        skipped_reason=reason,
    )
