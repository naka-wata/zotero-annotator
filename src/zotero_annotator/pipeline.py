from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Set

from zotero_annotator.clients.grobid import GrobidClient
from zotero_annotator.clients.zotero import ZoteroClient
from zotero_annotator.config import CoreSettings
from zotero_annotator.services.paragraphs import Paragraph, extract_paragraphs


AnnotationMode = Literal["note", "highlight_fixed"]


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


def run_no_translation(
    settings: CoreSettings,
    *,
    dry_run: bool,
    max_items: int,
    max_paragraphs_per_item: int,
    annotation_mode: AnnotationMode = "note",
    override_tag: Optional[str] = None,
) -> List[ItemResult]:
    """
    No-translation pipeline (翻訳なしパイプライン).

    - Fetch items by tag from Zotero (タグ付きアイテム取得)
    - Download PDF attachment (PDF添付の取得)
    - Parse paragraphs via GROBID TEI (GROBID TEIから段落抽出)
    - Create note/highlight annotations with para:<hash> tag (注釈作成＋重複防止タグ)
    """
    tag = override_tag or settings.z_target_tag

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
) -> ItemResult:
    item_key = item.get("key") or ""
    title = (item.get("data") or {}).get("title") or ""

    children = zotero.list_children(item_key)
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

    pdf_bytes = zotero.download_attachment(zotero.build_file_url(pdf_key))
    tei_xml = grobid.process_fulltext(pdf_bytes, tei_coordinates="p")

    paragraphs = extract_paragraphs(
        tei_xml,
        min_chars=settings.para_min_chars,
        max_chars=settings.para_max_chars,
    )

    existing_tags = collect_existing_tags(zotero, pdf_key)

    planned_payloads: List[Dict[str, Any]] = []
    planned_dedup_tags: Set[str] = set()
    dup = 0
    processed = 0

    for p in paragraphs[:max_paragraphs]:
        processed += 1
        dedup_tag = f"{settings.dedup_tag_prefix}{p.hash}"
        if dedup_tag in existing_tags:
            dup += 1
            continue
        planned_payloads.append(
            build_annotation_payload(
                paragraph=p,
                pdf_key=pdf_key,
                dedup_tag=dedup_tag,
                annotation_mode=annotation_mode,
            )
        )
        planned_dedup_tags.add(dedup_tag)

    created = 0
    if planned_payloads and not dry_run:
        zotero.create_annotations(planned_payloads)
        created = len(planned_payloads)

    # Auto finalize tags only when all paragraphs are complete (全段落が完了した時だけタグを更新)
    if not dry_run:
        # If we intentionally limited processing, do not finalize (一部だけ処理するモードでは完了扱いにしない)
        if max_paragraphs >= len(paragraphs):
            required = {f"{settings.dedup_tag_prefix}{p.hash}" for p in paragraphs}
            available = set(existing_tags) | set(planned_dedup_tags)
            all_done = required.issubset(available)
            if all_done:
                current = zotero.extract_tag_names(item)
                next_tags = zotero.merge_tags(
                    current=current,
                    add=[settings.z_done_tag],
                    remove=[settings.z_remove_tag],
                )
                zotero.update_item_tags(item_key=item_key, tags=next_tags)

    return ItemResult(
        item_key=item_key,
        title=title,
        pdf_key=pdf_key,
        paragraphs_total=len(paragraphs),
        paragraphs_skipped_duplicate=dup,
        paragraphs_processed=processed,
        annotations_planned=len(planned_payloads),
        annotations_created=created,
    )


def collect_existing_tags(zotero: ZoteroClient, pdf_key: str) -> Set[str]:
    # Collect all tag strings from existing annotations (既存注釈のタグ文字列を収集)
    existing = zotero.list_annotations(parent_key=pdf_key)
    out: Set[str] = set()
    for ann in existing:
        for t in zotero.extract_tag_names(ann):
            out.add(t)
    return out


def build_annotation_payload(
    *,
    paragraph: Paragraph,
    pdf_key: str,
    dedup_tag: str,
    annotation_mode: AnnotationMode,
) -> Dict[str, Any]:
    # Build Zotero annotation payload (Zotero注釈ペイロード生成)
    if annotation_mode == "note":
        return {
            "itemType": "annotation",
            "parentItem": pdf_key,
            "annotationType": "note",
            "annotationComment": paragraph.text,
            "tags": [{"tag": dedup_tag}],
        }

    # highlight_fixed: used only to test if position-based annotations work (位置付き注釈の疎通確認用)
    page_index = max((paragraph.page or 1) - 1, 0)
    annotation_position = {
        "pageIndex": page_index,
        "rects": [[10, 10, 20, 20]],
        "rotation": 0,
    }

    return {
        "itemType": "annotation",
        "parentItem": pdf_key,
        "annotationType": "highlight",
        "annotationComment": paragraph.text,
        "annotationPosition": json.dumps(annotation_position),
        "annotationPageLabel": str(page_index + 1),
        "tags": [{"tag": dedup_tag}],
    }
