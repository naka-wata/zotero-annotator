from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Sequence, Set

import httpx

from zotero_annotator.clients.grobid import GrobidClient
from zotero_annotator.clients.zotero import ZoteroClient
from zotero_annotator.config import CoreSettings
from zotero_annotator.services.annotation_position import build_note_position
from zotero_annotator.services.paragraphs import Paragraph
from zotero_annotator.services.paragraph_extractor import extract_paragraphs_from_pdf_bytes
from zotero_annotator.services.pdf_pages import get_pdf_page_sizes
from zotero_annotator.services.translators.base import TranslationError, Translator


AnnotationMode = Literal["note", "highlight"]


@dataclass
class ItemResult:
    item_key: str
    title: str
    pdf_key: Optional[str]

    paragraphs_total: int
    paragraphs_skipped_duplicate: int
    paragraphs_processed: int

    annotations_planned: int
    annotations_created: int

    skipped_reason: Optional[str] = None
    warnings: List[str] = field(default_factory=list)


def run_no_translation(
    settings: CoreSettings,
    *,
    dry_run: bool,
    max_items: int,
    max_paragraphs_per_item: int,
    annotation_mode: AnnotationMode = "note",
    override_tag: Optional[str] = None,
    item_keys: Optional[Sequence[str]] = None,
    translator: Optional[Translator] = None,
    source_lang: str = "",
    target_lang: str = "",
    delete_broken_annotations: bool = False,
) -> List[ItemResult]:
    """
    No-translation pipeline (翻訳なしパイプライン).

    - Fetch items by tag from Zotero (タグ付きアイテム取得)
    - Download PDF attachment (PDF添付の取得)
    - Parse paragraphs via GROBID TEI (GROBID TEIから段落抽出)
    - Create note/highlight annotations with para:<hash> tag (注釈作成＋重複防止タグ)
    """
    zotero = ZoteroClient(
        base_url=settings.zotero_base_url,
        api_key=settings.z_api_key,
        scope=settings.z_scope,
        library_id=settings.z_id,
    )
    grobid = GrobidClient(
        base_url=settings.grobid_url,
        timeout_seconds=settings.grobid_timeout_seconds,
    )

    results: List[ItemResult] = []
    try:
        if item_keys:
            # Keep item-key order and skip duplicated keys (指定順を維持し重複キーを除外)
            seen: Set[str] = set()
            ordered_keys = [k for k in item_keys if k and not (k in seen or seen.add(k))]
            for index, item_key in enumerate(ordered_keys):
                if index >= max_items:
                    break
                try:
                    item = zotero.get_item(item_key)
                except httpx.HTTPError:
                    results.append(
                        ItemResult(
                            item_key=item_key,
                            title=item_key,
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
                results.append(
                    process_item_no_translation(
                        settings,
                        zotero=zotero,
                        grobid=grobid,
                        item=item,
                        dry_run=dry_run,
                        max_paragraphs=max_paragraphs_per_item,
                        annotation_mode=annotation_mode,
                        translator=translator,
                        source_lang=source_lang,
                        target_lang=target_lang,
                        delete_broken_annotations=delete_broken_annotations,
                    )
                )
        else:
            tag = override_tag or settings.z_target_tag
            for index, item in enumerate(zotero.iter_items_by_tag(tag=tag, limit_per_page=100)):
                if index >= max_items:
                    break
                results.append(
                    process_item_no_translation(
                        settings,
                        zotero=zotero,
                        grobid=grobid,
                        item=item,
                        dry_run=dry_run,
                        max_paragraphs=max_paragraphs_per_item,
                        annotation_mode=annotation_mode,
                        translator=translator,
                        source_lang=source_lang,
                        target_lang=target_lang,
                        delete_broken_annotations=delete_broken_annotations,
                    )
                )
    finally:
        grobid.close()
        zotero.close()

    return results


def process_item_no_translation(
    settings: CoreSettings,
    *,
    zotero: ZoteroClient,
    grobid: GrobidClient,
    item: Dict[str, Any],
    dry_run: bool,
    max_paragraphs: int,
    annotation_mode: AnnotationMode,
    translator: Optional[Translator],
    source_lang: str,
    target_lang: str,
    delete_broken_annotations: bool,
) -> ItemResult:
    item_key = item.get("key") or ""
    title = (item.get("data") or {}).get("title") or ""
    warnings: List[str] = []

    try:
        children = zotero.list_children(item_key)
    except httpx.HTTPError as exc:
        return ItemResult(
            item_key=item_key,
            title=title or item_key,
            pdf_key=None,
            paragraphs_total=0,
            paragraphs_skipped_duplicate=0,
            paragraphs_processed=0,
            annotations_planned=0,
            annotations_created=0,
            skipped_reason=f"children_fetch_failed: {exc}",
        )

    pdf = zotero.pick_pdf_attachment(children)
    if not pdf:
        return ItemResult(
            item_key=item_key,
            title=title,
            pdf_key=None,
            paragraphs_total=0,
            paragraphs_skipped_duplicate=0,
            paragraphs_processed=0,
            annotations_planned=0,
            annotations_created=0,
            skipped_reason="no_pdf_attachment",
        )

    pdf_key = pdf.get("key") or ""

    try:
        pdf_bytes = zotero.download_attachment(zotero.build_file_url(pdf_key))
    except httpx.HTTPError as exc:
        return ItemResult(
            item_key=item_key,
            title=title,
            pdf_key=pdf_key,
            paragraphs_total=0,
            paragraphs_skipped_duplicate=0,
            paragraphs_processed=0,
            annotations_planned=0,
            annotations_created=0,
            skipped_reason=f"pdf_download_failed: {exc}",
        )

    page_sizes = get_pdf_page_sizes(pdf_bytes)

    try:
        paragraphs = extract_paragraphs_from_pdf_bytes(
            pdf_bytes,
            settings=settings,
            grobid_client=grobid if settings.para_extractor == "grobid" else None,
        )
    except httpx.HTTPError as exc:
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
    except (ValueError, RuntimeError) as exc:
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

    # Self-healing step: repair/delete broken annotations before creating new ones.
    if not dry_run:
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
                    skipped_reason=f"list_annotations_failed_after_repair_delete: {exc}",
                )

    planned_payloads: List[Dict[str, Any]] = []
    planned_dedup_tags: Set[str] = set()
    dup = 0
    processed = 0

    for p in paragraphs[:max_paragraphs]:
        processed += 1
        dedup_tags = [f"{settings.dedup_tag_prefix}{h}" for h in (p.dedup_hashes or [p.hash])]
        if any(t in existing_tags for t in dedup_tags):
            dup += 1
            continue
        source_text = p.text
        comment_text = source_text
        if translator is not None:
            try:
                comment_text = translator.translate(source_text, source_lang=source_lang, target_lang=target_lang).text
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
        planned_payloads.append(
            build_annotation_payload(
                paragraph=p,
                comment_text=comment_text,
                pdf_key=pdf_key,
                dedup_tags=dedup_tags,
                annotation_mode=annotation_mode,
                page_sizes=page_sizes,
            )
        )
        planned_dedup_tags.update(dedup_tags)

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
    # If translation is disabled, do not change item tags at all.
    # (翻訳なしモードではアイテムタグを変更しない)
    if not dry_run and translator is not None:
        # If we intentionally limited processing, do not finalize (一部だけ処理するモードでは完了扱いにしない)
        if max_paragraphs >= len(paragraphs):
            required = {f"{settings.dedup_tag_prefix}{h}" for p in paragraphs for h in (p.dedup_hashes or [p.hash])}
            available = set(existing_tags) | set(planned_dedup_tags)
            all_done = required.issubset(available)
            if all_done:
                current = zotero.extract_tag_names(item)
                next_tags = zotero.merge_tags(
                    current=current,
                    add=[settings.z_done_tag],
                    remove=[settings.z_remove_tag],
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


def delete_broken_annotations_for_pdf(zotero: ZoteroClient, pdf_key: str) -> tuple[int, List[str]]:
    """
    Delete annotation items that are missing required fields in Zotero 7 DB:
    annotationSortIndex / annotationPageLabel / annotationPosition.

    (必須フィールド欠落の注釈を削除する)
    """
    warnings: List[str] = []
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
    paragraphs: List[Paragraph],
    dedup_prefix: str,
    page_sizes: Dict[int, tuple[float, float]] | None = None,
) -> tuple[int, List[str]]:
    """
    Repair broken annotations that have a para:<hash> tag matching current paragraphs.
    (paraタグで段落に紐づけできる壊れ注釈を修復する)
    """
    warnings: List[str] = []
    repaired = 0

    pos_by_tag: Dict[str, Dict[str, str]] = {}
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
    zotero: ZoteroClient, payloads: List[Dict[str, Any]], *, batch_size: int
) -> tuple[int, List[str]]:
    """
    Create annotations in smaller batches to reduce partial failure impact.
    Falls back to per-item create for failed indices if Zotero returns them.

    (一括作成を小分けにし、失敗分は可能なら1件ずつ再送する)
    """
    if batch_size < 1:
        batch_size = 1

    created_total = 0
    warnings: List[str] = []

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


def _summarize_zotero_create_response(resp: Any, *, planned: int) -> tuple[int, List[int], List[str]]:
    """
    Zotero batch create may return 200 with partial failures.
    This helper returns (created_count, failed_indices, warnings).

    (Zoteroの一括作成は成功/失敗が混在しうるためサマリ化する)
    """
    warnings: List[str] = []
    failed_indices: List[int] = []

    if isinstance(resp, list):
        # Some endpoints may return created items list.
        return len(resp), failed_indices, warnings

    if isinstance(resp, dict):
        successful = resp.get("successful") or {}
        failed = resp.get("failed") or {}

        created = len(successful) if isinstance(successful, dict) else 0
        if isinstance(failed, dict) and failed:
            # Keep message short; include up to 3 failures.
            samples = []
            for k, v in list(failed.items()):
                try:
                    failed_indices.append(int(k))
                except Exception:
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


def collect_existing_tags(zotero: ZoteroClient, pdf_key: str) -> Set[str]:
    # Collect all tag strings from existing annotations (既存注釈のタグ文字列を収集)
    out: Set[str] = set()
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


def build_annotation_payload(
    *,
    paragraph: Paragraph,
    comment_text: str,
    pdf_key: str,
    dedup_tags: List[str],
    annotation_mode: AnnotationMode,
    page_sizes: Dict[int, tuple[float, float]] | None = None,
) -> Dict[str, Any]:
    # Build Zotero annotation payload (Zotero注釈ペイロード生成)
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
            "tags": [{"tag": t} for t in dedup_tags] + [{"tag": "grobid-auto"}],
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
        "tags": [{"tag": t} for t in dedup_tags],
    }
