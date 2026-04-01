from __future__ import annotations

import json
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from zotero_annotator.clients.zotero import ZoteroClient
from zotero_annotator.config import CoreSettings
from zotero_annotator.models.results import (
    ItemResult,
    TranslationItemResult,
    make_skipped_item_result,
    make_skipped_translation_result,
)
from zotero_annotator.services.annotation_position import build_note_position
from zotero_annotator.services.paragraphs import Paragraph
from zotero_annotator.services.pdf_pages import get_pdf_page_sizes
from zotero_annotator.services.pymupdf_adapter import extract_paragraphs_from_pdf_bytes
from zotero_annotator.services.translators.base import (
    TranslationError,
    TranslationInput,
    Translator,
)

AnnotationMode = Literal["note", "highlight"]


def _build_translation_input(
    *,
    current_paragraph: str,
    source_lang: str,
    target_lang: str,
    previous_paragraph: str = "",
    next_paragraph: str = "",
) -> TranslationInput:
    return TranslationInput(
        previous_paragraph=previous_paragraph,
        current_paragraph=current_paragraph,
        next_paragraph=next_paragraph,
        source_lang=source_lang,
        target_lang=target_lang,
    )


def _build_paragraph_translation_input(
    paragraphs: Sequence[Paragraph],
    index: int,
    *,
    source_lang: str,
    target_lang: str,
) -> TranslationInput:
    previous_paragraph = paragraphs[index - 1].text if index > 0 else ""
    next_paragraph = paragraphs[index + 1].text if index + 1 < len(paragraphs) else ""
    return _build_translation_input(
        previous_paragraph=previous_paragraph,
        current_paragraph=paragraphs[index].text,
        next_paragraph=next_paragraph,
        source_lang=source_lang,
        target_lang=target_lang,
    )


@dataclass
class _ItemResolution:
    """Single item resolved from an explicit key or tag iteration."""
    item_key: str
    item: dict[str, Any] | None
    lookup_error: httpx.HTTPError | None


def _iter_target_items(
    zotero: ZoteroClient,
    *,
    item_keys: Sequence[str] | None,
    tag: str,
    max_items: int,
) -> Iterator[_ItemResolution]:
    """Yield items either from explicit keys or by tag, up to max_items.

    - item_keys: maintains insertion order, deduplicates, fetches each item.
      Lookup failures are yielded with lookup_error set.
    - tag: iterates Zotero items tagged with `tag`; no lookup failure possible.
    """
    if item_keys:
        seen: set[str] = set()
        ordered_keys: list[str] = []
        for k in item_keys:
            if k and k not in seen:
                seen.add(k)
                ordered_keys.append(k)
        for index, item_key in enumerate(ordered_keys):
            if index >= max_items:
                break
            try:
                item = zotero.get_item(item_key)
                yield _ItemResolution(item_key=item_key, item=item, lookup_error=None)
            except httpx.HTTPError as exc:
                yield _ItemResolution(item_key=item_key, item=None, lookup_error=exc)
    else:
        for index, item in enumerate(zotero.iter_items_by_tag(tag=tag, limit_per_page=100)):
            if index >= max_items:
                break
            yield _ItemResolution(item_key=item.get("key") or "", item=item, lookup_error=None)


def _extract_paragraphs_from_pdf(
    pdf_bytes: bytes,
    pdf_key: str,
    item_key: str,
    title: str,
    zotero: ZoteroClient,
    settings: CoreSettings,
) -> tuple[list[Paragraph], set[str]] | ItemResult:
    """段落抽出と既存タグ収集の共通処理。

    成功時は (paragraphs, existing_tags) を返す。
    失敗時はスキップ済み ItemResult を返す。
    """
    try:
        paragraphs = extract_paragraphs_from_pdf_bytes(
            pdf_bytes,
            settings=settings,
        )
    except (httpx.HTTPError, ValueError, RuntimeError) as exc:
        return ItemResult(
            item_key=item_key,
            title=title,
            pdf_key=pdf_key,
            paragraphs_total=0,
            paragraphs_skipped_duplicate=0,
            paragraphs_processed=0,
            annotations_planned=0,
            annotations_created=0,
            skipped_reason=f"extract_failed: {exc}",
        )

    try:
        existing_tags = collect_existing_tags(zotero, pdf_key)
    except httpx.HTTPError as exc:
        return ItemResult(
            item_key=item_key,
            title=title,
            pdf_key=pdf_key,
            paragraphs_total=len(paragraphs),
            paragraphs_skipped_duplicate=0,
            paragraphs_processed=0,
            annotations_planned=0,
            annotations_created=0,
            skipped_reason=f"list_annotations_failed: {exc}",
        )

    return (paragraphs, existing_tags)


def _fetch_item_and_pdf(
    item_key: str,
    item: dict[str, Any],
    zotero: ZoteroClient,
) -> tuple[str, str] | ItemResult:
    """item/PDF 取得の共通処理（children 取得・PDF 特定まで）。

    成功時は (title, pdf_key) を返す。
    失敗時はスキップ済み ItemResult を返す。
    """
    title = (item.get("data") or {}).get("title") or item_key

    try:
        children = zotero.list_children(item_key)
    except httpx.HTTPError as exc:
        return make_skipped_item_result(
            item_key=item_key,
            title=title,
            pdf_key=None,
            reason=f"children_fetch_failed: {exc}",
        )

    pdf = zotero.pick_pdf_attachment(children)
    if not pdf:
        return make_skipped_item_result(
            item_key=item_key,
            title=title,
            pdf_key=None,
            reason="no_pdf_attachment",
        )

    pdf_key = pdf.get("key") or ""
    return (title, pdf_key)


def run_translate_existing_notes(
    settings: CoreSettings,
    *,
    dry_run: bool,
    max_items: int,
    translator: Translator,
    source_lang: str,
    target_lang: str,
    override_tag: str | None = None,
    item_keys: Sequence[str] | None = None,
) -> list[TranslationItemResult]:
    """
    Translate existing Zotero annotation note bodies in-place.

    - Fetch existing annotations from Zotero (既存注釈の取得)
    - Use current note body as source text (annotationComment / note 本文を翻訳元にする)
    - Update only the body field in place (本文のみ更新)
    - Never create new annotations (新規注釈は作らない)
    """
    results: list[TranslationItemResult] = []
    tag = override_tag or settings.z_base_done_tag
    with ZoteroClient(
        base_url=settings.zotero_base_url,
        api_key=settings.z_api_key,
        scope=settings.z_scope,
        library_id=settings.z_id,
    ) as zotero:
        for resolution in _iter_target_items(zotero, item_keys=item_keys, tag=tag, max_items=max_items):
            if resolution.lookup_error is not None:
                results.append(
                    TranslationItemResult(
                        item_key=resolution.item_key,
                        title=resolution.item_key,
                        pdf_key=None,
                        annotations_total=0,
                        annotations_targeted=0,
                        annotations_processed=0,
                        annotations_updated=0,
                        skipped_reason=f"stage=fetch_item item_lookup_failed item_key={resolution.item_key}: {resolution.lookup_error}",
                    )
                )
                continue
            assert resolution.item is not None
            results.append(
                process_item_translate_existing_notes(
                    settings,
                    zotero=zotero,
                    item=resolution.item,
                    dry_run=dry_run,
                    translator=translator,
                    source_lang=source_lang,
                    target_lang=target_lang,
                )
            )

    return results


def process_item_translate_existing_notes(
    settings: CoreSettings,
    *,
    zotero: ZoteroClient,
    item: dict[str, Any],
    dry_run: bool,
    translator: Translator,
    source_lang: str,
    target_lang: str,
) -> TranslationItemResult:
    item_key = item.get("key") or ""
    warnings: list[str] = []

    fetch_result = _fetch_item_and_pdf(item_key, item, zotero)
    if isinstance(fetch_result, ItemResult):
        return make_skipped_translation_result(
            item_key=fetch_result.item_key, title=fetch_result.title,
            pdf_key=fetch_result.pdf_key, reason=fetch_result.skipped_reason or "",
        )
    title, pdf_key = fetch_result

    try:
        annotations = list(zotero.iter_annotations(parent_key=pdf_key, limit_per_page=100))
    except httpx.HTTPError as exc:
        return make_skipped_translation_result(
            item_key=item_key, title=title, pdf_key=pdf_key,
            reason=f"stage=fetch_annotations list_annotations_failed item_key={item_key} pdf_key={pdf_key}: {exc}",
        )

    write_enabled = not dry_run
    ann_warnings, ann_errors, stats = _translate_pending_annotations(
        annotations=annotations, translator=translator, settings=settings,
        write_enabled=write_enabled, zotero=zotero, item_key=item_key,
        source_lang=source_lang, target_lang=target_lang,
    )
    warnings.extend(ann_warnings)
    targeted, processed, updated = stats["targeted"], stats["processed"], stats["updated"]

    if ann_errors:
        return TranslationItemResult(
            item_key=item_key, title=title, pdf_key=pdf_key,
            annotations_total=len(annotations),
            annotations_targeted=targeted, annotations_processed=processed, annotations_updated=updated,
            skipped_reason=ann_errors[0], warnings=warnings,
        )

    skipped_reason = None
    if targeted == 0:
        skipped_reason = f"stage=match no_pending_tagged_annotations item_key={item_key} pdf_key={pdf_key}"
    elif processed == 0:
        skipped_reason = f"stage=source no_valid_translation_targets item_key={item_key} pdf_key={pdf_key}"

    _update_item_tag_if_complete(zotero, write_enabled, item, item_key, pdf_key, settings, warnings)

    return TranslationItemResult(
        item_key=item_key, title=title, pdf_key=pdf_key,
        annotations_total=len(annotations), annotations_targeted=targeted,
        annotations_processed=processed, annotations_updated=updated,
        skipped_reason=skipped_reason, warnings=warnings,
    )


def _translate_pending_annotations(
    annotations: list[dict[str, Any]],
    translator: Translator,
    settings: CoreSettings,
    *,
    write_enabled: bool,
    zotero: ZoteroClient,
    item_key: str,
    source_lang: str,
    target_lang: str,
) -> tuple[list[str], list[str], dict[str, Any]]:
    """annotations をフィルタリングして翻訳を実行し (warnings, errors, stats) を返す。"""
    warnings: list[str] = []
    errors: list[str] = []
    targeted = 0
    processed = 0
    updated = 0
    skipped_non_pending = 0
    skipped_already_translated = 0
    targeted_missing_para_tag = 0
    targeted_invalid_para_tag = 0
    targeted_multiple_para_tags = 0

    for ann in annotations:
        ann_key = ann.get("key") or ""
        version = ann.get("version")
        data = dict(ann.get("data") or {})
        tags = zotero.extract_tag_names(ann)
        if settings.ann_translated_tag in tags:
            skipped_already_translated += 1
            continue
        if settings.ann_pending_translation_tag not in tags:
            skipped_non_pending += 1
            continue

        para_tags, invalid_para_tags = _split_para_tags(tags=tags, dedup_prefix=settings.dedup_tag_prefix)
        targeted += 1
        if invalid_para_tags:
            targeted_invalid_para_tag += 1
        if not para_tags:
            targeted_missing_para_tag += 1
        if len(para_tags) > 1:
            targeted_multiple_para_tags += 1

        body_field = _detect_annotation_body_field(data)
        source_text = str(data.get(body_field) or "").strip()
        if not source_text:
            warnings.append(
                f"stage=source empty_source item_key={item_key} annotation_key={ann_key} field={body_field}"
            )
            continue

        try:
            translated_text = translator.translate(
                _build_translation_input(
                    current_paragraph=source_text,
                    source_lang=source_lang,
                    target_lang=target_lang,
                )
            ).text
        except TranslationError as exc:
            errors.append(
                f"stage=translate translation_failed item_key={item_key} annotation_key={ann_key} "
                f"kind={exc.kind} status={exc.status_code}: {exc}"
            )
            break
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            errors.append(
                f"stage=translate item_key={item_key} annotation_key={ann_key} reason=http_error: {exc}"
            )
            break
        except Exception as exc:
            errors.append(
                f"stage=translate item_key={item_key} annotation_key={ann_key} reason=unexpected_error: {exc}"
            )
            break
        processed += 1

        updated_now, warning_message, error_message = _apply_translated_annotation_update(
            zotero=zotero,
            write_enabled=write_enabled,
            item_key=item_key,
            annotation_key=ann_key,
            body_field=body_field,
            annotation_data=data,
            version=version,
            translated_text=translated_text,
            pending_tag=settings.ann_pending_translation_tag,
            translated_tag=settings.ann_translated_tag,
        )
        if warning_message:
            warnings.append(warning_message)
        if error_message:
            errors.append(error_message)
            break
        updated += updated_now

    stats = {
        "targeted": targeted,
        "processed": processed,
        "updated": updated,
        "skipped_non_pending": skipped_non_pending,
        "skipped_already_translated": skipped_already_translated,
        "targeted_missing_para_tag": targeted_missing_para_tag,
        "targeted_invalid_para_tag": targeted_invalid_para_tag,
        "targeted_multiple_para_tags": targeted_multiple_para_tags,
    }
    if skipped_already_translated:
        warnings.append(f"stage=match skipped_already_translated count={skipped_already_translated}")
    if skipped_non_pending:
        warnings.append(f"stage=match skipped_without_pending_tag count={skipped_non_pending}")
    if targeted_missing_para_tag:
        warnings.append(f"stage=match targeted_missing_para_hash_tag count={targeted_missing_para_tag}")
    if targeted_invalid_para_tag:
        warnings.append(f"stage=match targeted_invalid_para_tags count={targeted_invalid_para_tag}")
    if targeted_multiple_para_tags:
        warnings.append(f"stage=match targeted_multiple_para_tags count={targeted_multiple_para_tags}")
    return warnings, errors, stats


def _update_item_tag_if_complete(
    zotero: ZoteroClient,
    write_enabled: bool,
    item: dict[str, Any],
    item_key: str,
    pdf_key: str,
    settings: CoreSettings,
    warnings: list[str],
) -> None:
    """翻訳完了時にアイテムタグを base-done → translated へ更新する。"""
    if not write_enabled:
        return
    pending_count, pending_check_warning = _count_pending_annotations_for_translation(
        zotero=zotero,
        item_key=item_key,
        pdf_key=pdf_key,
        pending_tag=settings.ann_pending_translation_tag,
    )
    if pending_check_warning:
        warnings.append(pending_check_warning)
    elif pending_count == 0:
        current_tags = zotero.extract_tag_names(item)
        next_tags = zotero.merge_tags(
            current=current_tags,
            add=[settings.z_done_tag],
            remove=[settings.z_base_done_tag],
        )
        try:
            zotero.update_item_tags(item_key=item_key, tags=next_tags)
        except httpx.HTTPError as exc:
            warnings.append(f"tag_update_failed: {exc}")


def _count_pending_annotations_for_translation(
    *,
    zotero: ZoteroClient,
    item_key: str,
    pdf_key: str,
    pending_tag: str,
) -> tuple[int | None, str | None]:
    try:
        latest_annotations = list(zotero.iter_annotations(parent_key=pdf_key, limit_per_page=100))
    except httpx.HTTPError as exc:
        return (
            None,
            f"stage=fetch_annotations list_annotations_for_completion_check_failed "
            f"item_key={item_key} pdf_key={pdf_key}: {exc}",
        )

    pending_count = sum(
        1
        for ann in latest_annotations
        if pending_tag in zotero.extract_tag_names(ann)
    )
    return pending_count, None


def run_no_translation(
    settings: CoreSettings,
    *,
    dry_run: bool,
    max_items: int,
    max_paragraphs_per_item: int,
    annotation_mode: AnnotationMode = "note",
    override_tag: str | None = None,
    item_keys: Sequence[str] | None = None,
    translator: Translator | None = None,
    source_lang: str = "",
    target_lang: str = "",
    delete_broken_annotations: bool = False,
) -> list[ItemResult]:
    """
    No-translation pipeline (翻訳なしパイプライン).

    - Fetch items by tag from Zotero (タグ付きアイテム取得)
    - Download PDF attachment (PDF添付の取得)
    - Parse paragraphs via PyMuPDF (PyMuPDFで段落抽出)
    - Create note/highlight annotations with para:<hash> tag (注釈作成＋重複防止タグ)
    """
    results: list[ItemResult] = []
    tag = override_tag or settings.z_target_tag
    with ZoteroClient(
        base_url=settings.zotero_base_url,
        api_key=settings.z_api_key,
        scope=settings.z_scope,
        library_id=settings.z_id,
    ) as zotero:
        for resolution in _iter_target_items(zotero, item_keys=item_keys, tag=tag, max_items=max_items):
            if resolution.lookup_error is not None:
                results.append(
                    ItemResult(
                        item_key=resolution.item_key,
                        title=resolution.item_key,
                        pdf_key=None,
                        paragraphs_total=0,
                        paragraphs_skipped_duplicate=0,
                        paragraphs_processed=0,
                        annotations_planned=0,
                        annotations_created=0,
                        skipped_reason="item_lookup_failed",
                    )
                )
                continue
            assert resolution.item is not None
            results.append(
                process_item_no_translation(
                    settings,
                    zotero=zotero,
                    item=resolution.item,
                    dry_run=dry_run,
                    max_paragraphs=max_paragraphs_per_item,
                    annotation_mode=annotation_mode,
                    translator=translator,
                    source_lang=source_lang,
                    target_lang=target_lang,
                    delete_broken_annotations=delete_broken_annotations,
                )
            )

    return results


def _build_annotation_payloads(
    paragraphs: Sequence[Paragraph],
    existing_tags: set[str],
    pdf_key: str,
    translator: Translator | None,
    settings: CoreSettings,
    *,
    item_key: str,
    title: str,
    source_lang: str,
    target_lang: str,
    annotation_mode: AnnotationMode,
    page_sizes: dict[int, tuple[float, float]] | None,
    max_paragraphs: int,
) -> list[dict[str, Any]] | ItemResult:
    """
    Build annotation payloads for each paragraph.
    Returns the list on success, or an ItemResult on translation error.
    (段落ごとに注釈ペイロードを構築する。成功時はリスト、翻訳エラー時は ItemResult を返す)
    """
    planned_payloads: list[dict[str, Any]] = []
    dup = 0
    processed = 0

    for index, p in enumerate(paragraphs[:max_paragraphs]):
        processed += 1
        dedup_tags = [f"{settings.dedup_tag_prefix}{h}" for h in (p.dedup_hashes or [p.hash])]
        if any(t in existing_tags for t in dedup_tags):
            dup += 1
            continue
        source_text = p.text
        comment_text = source_text
        if translator is not None:
            try:
                comment_text = translator.translate(
                    _build_paragraph_translation_input(
                        paragraphs,
                        index,
                        source_lang=source_lang,
                        target_lang=target_lang,
                    )
                ).text
                comment_text = _maybe_append_source_snippet(
                    translated=comment_text,
                    source=source_text,
                    enabled=True,
                    chars=_SOURCE_SNIPPET_CHARS,
                )
            except TranslationError as exc:
                # Avoid partial mixed-language annotations; treat translation errors as fatal for the item.
                # (翻訳エラー時に中途半端に注釈を作らない)
                return ItemResult(
                    item_key=item_key,
                    title=title,
                    pdf_key=pdf_key,
                    paragraphs_total=len(paragraphs),
                    paragraphs_skipped_duplicate=dup,
                    paragraphs_processed=processed,
                    annotations_planned=0,
                    annotations_created=0,
                    skipped_reason=f"translation_failed(kind={exc.kind} status={exc.status_code}): {exc}",
                )
        annotation_extra_tags = [settings.ann_pending_translation_tag] if translator is None else []
        planned_payloads.append(
            build_annotation_payload(
                paragraph=p,
                comment_text=comment_text,
                pdf_key=pdf_key,
                dedup_tags=dedup_tags,
                extra_tags=annotation_extra_tags,
                annotation_mode=annotation_mode,
                page_sizes=page_sizes,
            )
        )

    return planned_payloads


def _run_self_healing(
    pdf_key: str,
    zotero: ZoteroClient,
    settings: CoreSettings,
    paragraphs: list[Paragraph],
    page_sizes: dict[int, tuple[float, float]] | None,
    existing_tags: set[str],
    *,
    dry_run: bool,
    delete_broken_annotations: bool,
    item_key: str,
    title: str,
) -> list[str] | ItemResult:
    """壊れた注釈の修復・削除を行い、warnings を返す。

    dry_run=True のときは何もしない。
    existing_tags は broken_total > 0 のとき in-place で更新される。
    修復・削除後の再取得に失敗した場合は ItemResult を返す。
    """
    if dry_run:
        return []

    warnings: list[str] = []

    try:
        broken_total, broken_para_tagged = count_broken_annotations(zotero, pdf_key, dedup_prefix=settings.dedup_tag_prefix)
    except httpx.HTTPError as exc:
        warnings.append(f"count_broken_annotations_failed: {exc}")
        broken_total, broken_para_tagged = 0, 0

    if broken_total:
        warnings.append(f"broken_annotations_detected total={broken_total} para_tagged={broken_para_tagged}")

    if settings.run_repair_broken_annotations and broken_para_tagged:
        try:
            repaired, repair_warnings = repair_broken_annotations_for_pdf(
                zotero,
                pdf_key,
                paragraphs=paragraphs,
                dedup_prefix=settings.dedup_tag_prefix,
                page_sizes=page_sizes,
            )
            if repaired:
                warnings.append(f"repaired_broken_annotations={repaired}")
            warnings.extend(repair_warnings)
        except httpx.HTTPError as exc:
            warnings.append(f"repair_broken_annotations_failed: {exc}")

    if delete_broken_annotations and broken_total:
        try:
            deleted, delete_warnings = delete_broken_annotations_for_pdf(zotero, pdf_key)
            if deleted:
                warnings.append(f"deleted_broken_annotations={deleted}")
            warnings.extend(delete_warnings)
        except httpx.HTTPError as exc:
            warnings.append(f"delete_broken_annotations_failed: {exc}")

    # Refresh after repair/delete to avoid dedup mismatches.
    if broken_total:
        try:
            refreshed = collect_existing_tags(zotero, pdf_key)
            existing_tags.clear()
            existing_tags.update(refreshed)
        except httpx.HTTPError as exc:
            return ItemResult(
                item_key=item_key,
                title=title,
                pdf_key=pdf_key,
                paragraphs_total=len(paragraphs),
                paragraphs_skipped_duplicate=0,
                paragraphs_processed=0,
                annotations_planned=0,
                annotations_created=0,
                skipped_reason=f"list_annotations_failed_after_repair_delete: {exc}",
            )

    return warnings


def _write_and_finalize(
    planned_payloads: list[dict[str, Any]],
    paragraphs: list[Paragraph],
    item_key: str,
    pdf_key: str,
    title: str,
    item: dict[str, Any],
    zotero: ZoteroClient,
    settings: CoreSettings,
    existing_tags: set[str],
    warnings: list[str],
    *,
    max_paragraphs: int,
    dry_run: bool,
    translator: Translator | None,
) -> ItemResult:
    """Zotero への書き込みとタグ自動確定を行い ItemResult を返す。"""
    processed = min(max_paragraphs, len(paragraphs))
    dup = processed - len(planned_payloads)
    planned_dedup_tags: set[str] = {
        t["tag"]
        for payload in planned_payloads
        for t in payload.get("tags", [])
        if t["tag"].startswith(settings.dedup_tag_prefix)
    }

    created = 0
    if planned_payloads and not dry_run:
        try:
            created, create_warnings = _create_annotations_resilient(
                zotero, planned_payloads, batch_size=10
            )
            warnings.extend(create_warnings)
        except httpx.HTTPError as exc:
            return ItemResult(
                item_key=item_key,
                title=title,
                pdf_key=pdf_key,
                paragraphs_total=len(paragraphs),
                paragraphs_skipped_duplicate=dup,
                paragraphs_processed=processed,
                annotations_planned=len(planned_payloads),
                annotations_created=0,
                skipped_reason=f"create_annotations_failed: {exc}",
            )

    # Auto finalize tags only when all paragraphs are complete (全段落が完了した時だけタグを更新)
    if not dry_run and max_paragraphs >= len(paragraphs):
        required = {f"{settings.dedup_tag_prefix}{h}" for p in paragraphs for h in (p.dedup_hashes or [p.hash])}
        available = set(existing_tags) | set(planned_dedup_tags)
        if required.issubset(available):
            finalize_add_tag = settings.z_done_tag if translator is not None else settings.z_base_done_tag
            finalize_remove_tags = [settings.z_remove_tag]
            if translator is not None:
                finalize_remove_tags.append(settings.z_base_done_tag)
            current = zotero.extract_tag_names(item)
            next_tags = zotero.merge_tags(
                current=current,
                add=[finalize_add_tag],
                remove=finalize_remove_tags,
            )
            try:
                zotero.update_item_tags(item_key=item_key, tags=next_tags)
            except httpx.HTTPError as exc:
                warnings.append(f"tag_update_failed: {exc}")

    return ItemResult(
        item_key=item_key,
        title=title,
        pdf_key=pdf_key,
        paragraphs_total=len(paragraphs),
        paragraphs_skipped_duplicate=dup,
        paragraphs_processed=processed,
        annotations_planned=len(planned_payloads),
        annotations_created=created,
        warnings=warnings,
    )


def process_item_no_translation(
    settings: CoreSettings,
    *,
    zotero: ZoteroClient,
    item: dict[str, Any],
    dry_run: bool,
    max_paragraphs: int,
    annotation_mode: AnnotationMode,
    translator: Translator | None,
    source_lang: str,
    target_lang: str,
    delete_broken_annotations: bool,
) -> ItemResult:
    item_key = item.get("key") or ""
    warnings: list[str] = []

    fetch_result = _fetch_item_and_pdf(item_key, item, zotero)
    if isinstance(fetch_result, ItemResult):
        return fetch_result
    title, pdf_key = fetch_result

    try:
        pdf_bytes = zotero.download_attachment(zotero.build_file_url(pdf_key))
    except httpx.HTTPError as exc:
        return make_skipped_item_result(
            item_key=item_key, title=title, pdf_key=pdf_key,
            reason=f"pdf_download_failed: {exc}",
        )

    page_sizes = get_pdf_page_sizes(pdf_bytes)

    extract_result = _extract_paragraphs_from_pdf(
        pdf_bytes, pdf_key, item_key, title, zotero, settings
    )
    if isinstance(extract_result, ItemResult):
        return extract_result
    paragraphs, existing_tags = extract_result

    heal_result = _run_self_healing(
        pdf_key, zotero, settings, paragraphs, page_sizes, existing_tags,
        dry_run=dry_run, delete_broken_annotations=delete_broken_annotations,
        item_key=item_key, title=title,
    )
    if isinstance(heal_result, ItemResult):
        return heal_result
    warnings.extend(heal_result)

    build_result = _build_annotation_payloads(
        paragraphs, existing_tags, pdf_key, translator, settings,
        item_key=item_key, title=title, source_lang=source_lang,
        target_lang=target_lang, annotation_mode=annotation_mode,
        page_sizes=page_sizes, max_paragraphs=max_paragraphs,
    )
    if isinstance(build_result, ItemResult):
        return build_result

    return _write_and_finalize(
        build_result, paragraphs, item_key, pdf_key, title, item,
        zotero, settings, existing_tags, warnings,
        max_paragraphs=max_paragraphs, dry_run=dry_run, translator=translator,
    )


def delete_broken_annotations_for_pdf(zotero: ZoteroClient, pdf_key: str) -> tuple[int, list[str]]:
    """
    Delete annotation items that are missing required fields in Zotero 7 DB:
    annotationSortIndex / annotationPageLabel / annotationPosition.

    (必須フィールド欠落の注釈を削除する)
    """
    warnings: list[str] = []
    deleted = 0

    for ann in zotero.iter_annotations(parent_key=pdf_key, limit_per_page=100):
        ann_key = ann.get("key") or ""
        version = ann.get("version")
        data = ann.get("data") or {}

        sort_index = data.get("annotationSortIndex")
        page_label = data.get("annotationPageLabel")
        position = data.get("annotationPosition")

        has_sort_index = isinstance(sort_index, str) and bool(sort_index.strip())
        has_page_label = isinstance(page_label, str) and bool(page_label.strip())
        has_position = (isinstance(position, str) and bool(position.strip())) or isinstance(position, dict)

        if has_sort_index and has_page_label and has_position:
            continue

        try:
            zotero.delete_item(item_key=ann_key, version=version if isinstance(version, int) else None)
            deleted += 1
        except httpx.HTTPError as exc:
            warnings.append(f"delete_failed annotation_key={ann_key}: {exc}")

    return deleted, warnings


def count_broken_annotations(zotero: ZoteroClient, pdf_key: str, *, dedup_prefix: str) -> tuple[int, int]:
    """
    Count annotations missing required fields; also count those that are para-tagged.
    (必須フィールド欠落の注釈数と、そのうちparaタグ付きの数を数える)
    """
    total = 0
    para_tagged = 0
    for ann in zotero.iter_annotations(parent_key=pdf_key, limit_per_page=100):
        data = ann.get("data") or {}
        sort_index = data.get("annotationSortIndex")
        page_label = data.get("annotationPageLabel")
        position = data.get("annotationPosition")

        has_sort_index = isinstance(sort_index, str) and bool(sort_index.strip())
        has_page_label = isinstance(page_label, str) and bool(page_label.strip())
        has_position = (isinstance(position, str) and bool(position.strip())) or isinstance(position, dict)
        if has_sort_index and has_page_label and has_position:
            continue
        total += 1

        tags = zotero.extract_tag_names(ann)
        if any(isinstance(t, str) and t.startswith(dedup_prefix) for t in tags):
            para_tagged += 1
    return total, para_tagged


def repair_broken_annotations_for_pdf(
    zotero: ZoteroClient,
    pdf_key: str,
    *,
    paragraphs: list[Paragraph],
    dedup_prefix: str,
    page_sizes: dict[int, tuple[float, float]] | None = None,
) -> tuple[int, list[str]]:
    """
    Repair broken annotations that have a para:<hash> tag matching current paragraphs.
    (paraタグで段落に紐づけできる壊れ注釈を修復する)
    """
    warnings: list[str] = []
    repaired = 0

    pos_by_tag: dict[str, dict[str, str]] = {}
    for p in paragraphs:
        note_pos = build_note_position(p, page_sizes=page_sizes)
        patch = {
            "annotationPosition": json.dumps(note_pos.annotation_position),
            "annotationPageLabel": str(note_pos.page_index + 1),
            "annotationSortIndex": note_pos.annotation_sort_index,
        }
        for h in (p.dedup_hashes or [p.hash]):
            pos_by_tag[f"{dedup_prefix}{h}"] = patch

    for ann in zotero.iter_annotations(parent_key=pdf_key, limit_per_page=100):
        ann_key = ann.get("key") or ""
        version = ann.get("version")
        data = dict(ann.get("data") or {})

        sort_index = data.get("annotationSortIndex")
        page_label = data.get("annotationPageLabel")
        position = data.get("annotationPosition")
        has_sort_index = isinstance(sort_index, str) and bool(sort_index.strip())
        has_page_label = isinstance(page_label, str) and bool(page_label.strip())
        has_position = (isinstance(position, str) and bool(position.strip())) or isinstance(position, dict)
        if has_sort_index and has_page_label and has_position:
            continue

        tags = zotero.extract_tag_names(ann)
        para_tags = [t for t in tags if isinstance(t, str) and t.startswith(dedup_prefix)]
        ref_tag = next((t for t in para_tags if t in pos_by_tag), None)
        if not ref_tag:
            continue

        patch = pos_by_tag[ref_tag]
        data.setdefault("key", ann_key)
        data.setdefault("itemType", "annotation")
        data.update(patch)

        try:
            zotero.update_item(item_key=ann_key, data=data, version=version if isinstance(version, int) else None)
            repaired += 1
        except httpx.HTTPError as exc:
            warnings.append(f"repair_failed annotation_key={ann_key}: {exc}")

    return repaired, warnings


def _create_annotations_resilient(
    zotero: ZoteroClient, payloads: list[dict[str, Any]], *, batch_size: int
) -> tuple[int, list[str]]:
    """
    Create annotations in smaller batches to reduce partial failure impact.
    Falls back to per-item create for failed indices if Zotero returns them.

    (一括作成を小分けにし、失敗分は可能なら1件ずつ再送する)
    """
    if batch_size < 1:
        batch_size = 1

    created_total = 0
    warnings: list[str] = []

    for start in range(0, len(payloads), batch_size):
        chunk = payloads[start : start + batch_size]
        resp = zotero.create_annotations(chunk)
        created, failed_indices, w = _summarize_zotero_create_response(resp, planned=len(chunk))
        created_total += created
        warnings.extend(w)

        # Retry failed ones individually once (best-effort).
        for i in failed_indices:
            if i < 0 or i >= len(chunk):
                continue
            try:
                resp_one = zotero.create_annotations([chunk[i]])
            except httpx.HTTPError as exc:
                warnings.append(f"zotero_create_retry_failed index={start+i}: {exc}")
                continue
            created_one, _, w_one = _summarize_zotero_create_response(resp_one, planned=1)
            created_total += created_one
            warnings.extend(w_one)

    return created_total, warnings


def _summarize_zotero_create_response(resp: Any, *, planned: int) -> tuple[int, list[int], list[str]]:
    """
    Zotero batch create may return 200 with partial failures.
    This helper returns (created_count, failed_indices, warnings).

    (Zoteroの一括作成は成功/失敗が混在しうるためサマリ化する)
    """
    warnings: list[str] = []
    failed_indices: list[int] = []

    if isinstance(resp, list):
        # Some endpoints may return created items list.
        return len(resp), failed_indices, warnings

    if isinstance(resp, dict):
        successful = resp.get("successful") or {}
        failed = resp.get("failed") or {}

        created = len(successful) if isinstance(successful, dict) else 0
        if isinstance(failed, dict) and failed:
            # Keep message short; include up to 3 failures.
            samples: list[str] = []
            for k, v in list(failed.items()):
                try:
                    failed_indices.append(int(k))
                except ValueError:
                    pass
                if len(samples) >= 3:
                    continue
                if isinstance(v, dict):
                    code = v.get("code")
                    msg = v.get("message") or v.get("error") or v
                    samples.append(f"{k}: code={code} message={msg}")
                else:
                    samples.append(f"{k}: {v}")
            warnings.append(f"zotero_create_failed planned={planned} created={created} samples={samples}")
        # If Zotero returns dict but without successful/failed, fall back.
        if created == 0 and planned > 0 and not failed:
            warnings.append("zotero_create_response_unrecognized")
            return planned, failed_indices, warnings
        return created, failed_indices, warnings

    warnings.append("zotero_create_response_unrecognized")
    return planned, failed_indices, warnings


def collect_existing_tags(zotero: ZoteroClient, pdf_key: str) -> set[str]:
    # Collect all tag strings from existing annotations (既存注釈のタグ文字列を収集)
    out: set[str] = set()
    for ann in zotero.iter_annotations(parent_key=pdf_key, limit_per_page=100):
        for t in zotero.extract_tag_names(ann):
            out.add(t)
    return out


_SOURCE_SNIPPET_CHARS = 10


def _build_source_snippet(text: str, *, chars: int) -> str:
    s = " ".join((text or "").split()).strip()
    if not s:
        return ""
    if len(s) <= (chars * 2 + 10):
        return s
    head = s[:chars].rstrip()
    tail = s[-chars:].lstrip()
    return f"{head} … {tail}"


def _maybe_append_source_snippet(*, translated: str, source: str, enabled: bool, chars: int) -> str:
    # Backward-compatible wrapper: we now always include the snippet when translation is enabled.
    snippet = _build_source_snippet(source, chars=chars)
    if not snippet:
        return translated
    return f"{translated}\n\nSRC: {snippet}"


def _detect_annotation_body_field(data: dict[str, Any]) -> str:
    # Prefer annotationComment for annotation items; fall back to note body when needed.
    if "annotationComment" in data:
        return "annotationComment"
    if "note" in data:
        return "note"
    return "annotationComment"


def _apply_translated_annotation_update(
    *,
    zotero: ZoteroClient,
    write_enabled: bool,
    item_key: str,
    annotation_key: str,
    body_field: str,
    annotation_data: dict[str, Any],
    version: Any,
    translated_text: str,
    pending_tag: str,
    translated_tag: str,
) -> tuple[int, str | None, str | None]:
    if not write_enabled:
        return (
            0,
            f"stage=update read_only_no_update item_key={item_key} annotation_key={annotation_key} field={body_field}",
            None,
        )

    patch = dict(annotation_data)
    patch.setdefault("key", annotation_key)
    patch.setdefault("itemType", "annotation")
    patch[body_field] = translated_text
    current_tags = [
        t["tag"]
        for t in (annotation_data.get("tags") or [])
        if isinstance(t, dict) and isinstance(t.get("tag"), str) and t["tag"].strip()
    ]
    next_tags = zotero.merge_tags(
        current=current_tags,
        add=[translated_tag],
        remove=[pending_tag],
    )
    patch["tags"] = [{"tag": t} for t in next_tags]

    try:
        zotero.update_item(
            item_key=annotation_key,
            data=patch,
            version=version if isinstance(version, int) else None,
        )
        return 1, None, None
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        return (
            0,
            None,
            f"stage=update item_key={item_key} annotation_key={annotation_key} reason=http_error: {exc}",
        )
    except Exception as exc:
        return (
            0,
            None,
            f"stage=update item_key={item_key} annotation_key={annotation_key} reason=unexpected_error: {exc}",
        )


_PARA_HASH_RE = re.compile(r"^[0-9a-f]{40}$")


def _split_para_tags(*, tags: list[str], dedup_prefix: str) -> tuple[list[str], list[str]]:
    valid: list[str] = []
    invalid: list[str] = []
    for tag in tags:
        if not isinstance(tag, str) or not tag.startswith(dedup_prefix):
            continue
        hash_part = tag[len(dedup_prefix) :].strip()
        if _PARA_HASH_RE.fullmatch(hash_part):
            valid.append(tag)
        else:
            invalid.append(tag)
    return valid, invalid


def build_annotation_payload(
    *,
    paragraph: Paragraph,
    comment_text: str,
    pdf_key: str,
    dedup_tags: list[str],
    extra_tags: Sequence[str] | None = None,
    annotation_mode: AnnotationMode,
    page_sizes: dict[int, tuple[float, float]] | None = None,
) -> dict[str, Any]:
    # Build Zotero annotation payload (Zotero注釈ペイロード生成)
    tag_names = [
        tag
        for tag in [*dedup_tags, *(extra_tags or ())]
        if isinstance(tag, str) and tag.strip()
    ]
    if annotation_mode == "note":
        note_pos = build_note_position(paragraph, page_sizes=page_sizes)
        return {
            "itemType": "annotation",
            "parentItem": pdf_key,
            "annotationType": "note",
            "annotationComment": comment_text,
            "annotationPosition": json.dumps(note_pos.annotation_position),
            "annotationPageLabel": str(note_pos.page_index + 1),
            "annotationSortIndex": note_pos.annotation_sort_index,
            "tags": [{"tag": t} for t in tag_names],
        }

    # highlight: small fixed rectangle, but still requires pageLabel/sortIndex in Zotero 7.
    note_pos = build_note_position(paragraph, page_sizes=page_sizes)
    annotation_position = dict(note_pos.annotation_position)

    return {
        "itemType": "annotation",
        "parentItem": pdf_key,
        "annotationType": "highlight",
        "annotationComment": comment_text,
        "annotationPosition": json.dumps(annotation_position),
        "annotationPageLabel": str(note_pos.page_index + 1),
        "annotationSortIndex": note_pos.annotation_sort_index,
        "tags": [{"tag": t} for t in tag_names],
    }


# ---------------------------------------------------------------------------
# dev annotate / dev translate helpers
# ---------------------------------------------------------------------------


@dataclass
class DevAnnotateResult:
    status: Literal["duplicate", "read_only", "created", "error"]
    item_key: str = ""
    pdf_key: str = ""
    paragraph_index: int = 0
    page: int | None = None
    paragraph_hash: str = ""
    title: str = ""
    dedup_tag: str = ""
    payload: dict[str, Any] | None = None
    error_stage: str | None = None
    error_detail: str | None = None


def _fetch_paragraphs_for_dev(
    *,
    zotero: ZoteroClient,
    settings: Any,
    item_key: str,
) -> tuple[str, str, bytes, list[Paragraph]] | DevAnnotateResult:
    """item → PDF → paragraphs を取得して返す。失敗時は DevAnnotateResult(error) を返す。"""

    def err(stage: str, detail: str) -> DevAnnotateResult:
        return DevAnnotateResult(status="error", item_key=item_key, error_stage=stage, error_detail=detail)

    try:
        item = zotero.get_item(item_key)
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else "unknown"
        return err("Zotero item lookup failed", f"item_key={item_key} status={status_code}")
    except httpx.HTTPError as exc:
        return err("Zotero connection failed", f"item_key={item_key} detail={exc}")

    item_title = (item.get("data") or {}).get("title") or ""

    try:
        children = zotero.list_children(item_key)
    except httpx.HTTPError as exc:
        return err("Zotero connection failed", f"children fetch failed item_key={item_key} detail={exc}")

    pdf = zotero.pick_pdf_attachment(children)
    if not pdf:
        return err("PDF attachment missing", f"item_key={item_key}")
    pdf_key = pdf.get("key") or ""

    try:
        pdf_bytes = zotero.download_attachment(zotero.build_file_url(pdf_key))
    except httpx.HTTPError as exc:
        return err("Zotero connection failed", f"pdf download failed pdf_key={pdf_key} detail={exc}")

    try:
        paragraphs = extract_paragraphs_from_pdf_bytes(pdf_bytes, settings=settings)
    except (ValueError, RuntimeError, httpx.HTTPError) as exc:
        return err("Paragraph extraction failed", str(exc))

    if not paragraphs:
        return err("No paragraphs extracted", f"item_key={item_key} pdf_key={pdf_key} paragraphs=0")

    return item_title, pdf_key, pdf_bytes, paragraphs


def run_dev_annotate(
    *,
    zotero: ZoteroClient,
    settings: Any,
    item_key: str,
    paragraph_index: int,
    read_only: bool,
    translate: bool,
    annotation_mode: str | None,
    translator: Translator | None = None,
    source_lang: str | None = None,
    target_lang: str | None = None,
) -> DevAnnotateResult:
    """1段落だけ注釈するビジネスロジック（dev annotate コマンド用）。"""

    def err(stage: str, detail: str) -> DevAnnotateResult:
        return DevAnnotateResult(status="error", item_key=item_key, error_stage=stage, error_detail=detail)

    fetched = _fetch_paragraphs_for_dev(zotero=zotero, settings=settings, item_key=item_key)
    if isinstance(fetched, DevAnnotateResult):
        return fetched
    item_title, pdf_key, pdf_bytes, paragraphs = fetched

    if paragraph_index >= len(paragraphs):
        return err(
            "Paragraph index out of range",
            f"item_key={item_key} paragraph_index={paragraph_index} paragraphs={len(paragraphs)}",
        )

    p = paragraphs[paragraph_index]
    dedup_tags = [f"{settings.dedup_tag_prefix}{h}" for h in (p.dedup_hashes or [p.hash])]

    source_text = p.text
    comment_text = source_text
    if translate and translator is not None:
        try:
            comment_text = translator.translate(
                _build_paragraph_translation_input(
                    paragraphs, paragraph_index,
                    source_lang=source_lang or "",
                    target_lang=target_lang or "",
                )
            ).text
            comment_text = _maybe_append_source_snippet(
                translated=comment_text, source=source_text, enabled=True, chars=_SOURCE_SNIPPET_CHARS,
            )
        except TranslationError as exc:
            return err("Translation failed", f"kind={exc.kind} provider={exc.provider} status={exc.status_code} detail={exc}")

    try:
        existing = list(zotero.iter_annotations(parent_key=pdf_key, limit_per_page=100))
    except httpx.HTTPError as exc:
        return err("Zotero connection failed", f"annotations fetch failed pdf_key={pdf_key} detail={exc}")

    existing_tags: set[str] = set()
    for ann in existing:
        for t in zotero.extract_tag_names(ann):
            existing_tags.add(t)
    if any(t in existing_tags for t in dedup_tags):
        return DevAnnotateResult(
            status="duplicate", item_key=item_key, pdf_key=pdf_key,
            paragraph_index=paragraph_index, page=p.page, paragraph_hash=p.hash,
            title=item_title, dedup_tag=dedup_tags[0],
        )

    mode = (annotation_mode or settings.annotation_mode).strip()
    page_sizes = get_pdf_page_sizes(pdf_bytes)
    payload = build_annotation_payload(
        paragraph=p, comment_text=comment_text, pdf_key=pdf_key,
        dedup_tags=dedup_tags, annotation_mode=mode,  # type: ignore[arg-type]
        page_sizes=page_sizes,
    )

    if read_only:
        return DevAnnotateResult(
            status="read_only", item_key=item_key, pdf_key=pdf_key,
            paragraph_index=paragraph_index, page=p.page, paragraph_hash=p.hash,
            title=item_title, dedup_tag=dedup_tags[0], payload=payload,
        )

    try:
        zotero.create_annotations([payload])
    except httpx.HTTPError as exc:
        return err("Annotation creation failed", f"pdf_key={pdf_key} paragraph_index={paragraph_index} detail={exc}")

    return DevAnnotateResult(
        status="created", item_key=item_key, pdf_key=pdf_key,
        paragraph_index=paragraph_index, page=p.page, paragraph_hash=p.hash,
        title=item_title, dedup_tag=dedup_tags[0],
    )


@dataclass
class DevTranslateResult:
    status: Literal["ok", "error"]
    item_key: str = ""
    pdf_key: str = ""
    paragraph_index: int = 0
    page: int | None = None
    provider: str = ""
    target_lang: str = ""
    title: str = ""
    source_text: str = ""
    translated_text: str = ""
    error_stage: str | None = None
    error_detail: str | None = None


def run_dev_translate(
    *,
    zotero: ZoteroClient,
    settings: Any,
    translator: Translator,
    item_key: str,
    paragraph_index: int,
    source_lang: str,
    target_lang: str,
) -> DevTranslateResult:
    """1段落だけ翻訳するビジネスロジック（dev translate コマンド用）。"""

    def err(stage: str, detail: str) -> DevTranslateResult:
        return DevTranslateResult(status="error", item_key=item_key, error_stage=stage, error_detail=detail)

    fetched = _fetch_paragraphs_for_dev(zotero=zotero, settings=settings, item_key=item_key)
    if isinstance(fetched, DevAnnotateResult):
        return DevTranslateResult(
            status="error", item_key=item_key,
            error_stage=fetched.error_stage, error_detail=fetched.error_detail,
        )
    item_title, pdf_key, _pdf_bytes, paragraphs = fetched

    if paragraph_index >= len(paragraphs):
        return err(
            "Paragraph index out of range",
            f"item_key={item_key} paragraph_index={paragraph_index} paragraphs={len(paragraphs)}",
        )

    p = paragraphs[paragraph_index]

    try:
        result = translator.translate(
            _build_paragraph_translation_input(
                paragraphs, paragraph_index,
                source_lang=source_lang,
                target_lang=target_lang,
            )
        )
    except TranslationError as exc:
        return err("Translation failed", f"kind={exc.kind} provider={exc.provider} status={exc.status_code} detail={exc}")

    return DevTranslateResult(
        status="ok", item_key=item_key, pdf_key=pdf_key,
        paragraph_index=paragraph_index, page=p.page,
        provider=result.provider, target_lang=target_lang,
        title=item_title, source_text=p.text, translated_text=result.text,
    )
