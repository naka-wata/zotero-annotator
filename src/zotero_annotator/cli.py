from __future__ import annotations

import base64
import json
from hashlib import sha1
import statistics
from pathlib import Path
from typing import List, Optional, Tuple

import httpx
import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from zotero_annotator.clients.zotero import ZoteroClient
from zotero_annotator.config import get_core_settings, get_translation_runtime
from zotero_annotator.pipeline import (
    _build_paragraph_translation_input,
    build_annotation_payload,
    run_no_translation,
    run_translate_existing_notes,
)
from zotero_annotator.services.annotation_position import build_note_position
from zotero_annotator.services.paragraph_extractor import extract_paragraphs_from_pdf_bytes
from zotero_annotator.services.pdf_pages import get_pdf_page_sizes
from zotero_annotator.services.pymupdf_paragraphs import ExtractionConfig as PyMuPDFExtractionConfig
from zotero_annotator.services.pymupdf_paragraphs import (
    extract_paragraphs_from_pymupdf_dict,
    extract_paragraphs_pymupdf_bytes,
    paragraphs_to_xml,
)
from zotero_annotator.services.translators.base import TranslationError
from zotero_annotator.services.translators.factory import build_translator


app = typer.Typer(add_completion=False)
dev_app = typer.Typer(help="Development helpers / 開発用コマンド")
app.add_typer(dev_app, name="dev")
console = Console()

_SOURCE_SNIPPET_CHARS = 10
_SEARCH_TABLE_TRUNCATE_CHARS = 80


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



def _truncate_for_table(value: str, *, max_chars: int) -> str:
    text = " ".join((value or "").split()).strip()
    if not text:
        return "-"
    if len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 1].rstrip()}…"


def _search_sort_key(item_key: str, matched_tags_by_item_key: dict[str, list[str]], *, base_done_tag: str) -> tuple[int, str]:
    matched_tags = matched_tags_by_item_key.get(item_key, [])
    has_base_done = base_done_tag in matched_tags
    return (0 if has_base_done else 1, item_key)


# Search command to list target papers quickly (対象論文を確認する検索コマンド)
@app.command()
def search(
    tag: Optional[List[str]] = typer.Option(
        None,
        "--tag",
        help="Target tag to OR with base tag (repeatable) / 対象タグをOR追加（複数指定可）",
    ),
    max_items: int = typer.Option(20, "--max-items", help="Max items to display / 表示する最大件数"),
) -> None:
    """List items tagged in Zotero (タグ付き論文の一覧を表示する)."""
    if max_items < 1:
        raise typer.BadParameter("--max-items must be >= 1")

    settings = get_core_settings()
    tags_to_search: list[str] = []

    def append_tag_once(value: str) -> None:
        if value and value not in tags_to_search:
            tags_to_search.append(value)

    if tag:
        append_tag_once(settings.z_base_done_tag)
        for specified_tag in tag:
            append_tag_once(specified_tag)
    else:
        append_tag_once(settings.z_target_tag)
        append_tag_once(settings.z_base_done_tag)

    zotero = ZoteroClient(
        base_url=settings.zotero_base_url,
        api_key=settings.z_api_key,
        scope=settings.z_scope,
        library_id=settings.z_id,
    )
    try:
        matched_tags_by_item_key: dict[str, list[str]] = {}
        items_by_key: dict[str, dict] = {}
        for target_tag in tags_to_search:
            for item in zotero.iter_items_by_tag(tag=target_tag, limit_per_page=100):
                key = item.get("key") or ""
                if not key:
                    continue
                matched_tags = matched_tags_by_item_key.setdefault(key, [])
                if target_tag not in matched_tags:
                    matched_tags.append(target_tag)
                if key not in items_by_key:
                    items_by_key[key] = item

        table = Table(show_header=True, header_style="bold")
        table.add_column("#", justify="right", style="dim", no_wrap=True)
        table.add_column("matched_tags", style="magenta")
        table.add_column("item-key", style="cyan", no_wrap=True)
        table.add_column("title", style="green")
        table.add_column("tags", style="yellow")

        sorted_items = sorted(
            items_by_key.items(),
            key=lambda pair: _search_sort_key(
                pair[0],
                matched_tags_by_item_key,
                base_done_tag=settings.z_base_done_tag,
            ),
        )
        displayed_items = sorted_items[:max_items]

        for count, (key, item) in enumerate(displayed_items, start=1):
            title = (item.get("data") or {}).get("title") or ""
            tags = zotero.extract_tag_names(item)
            tags_text = ", ".join(tags) if tags else "-"
            matched_tags_text = ", ".join(matched_tags_by_item_key.get(key, [])) or "-"
            table.add_row(
                str(count),
                matched_tags_text,
                key,
                _truncate_for_table(title, max_chars=_SEARCH_TABLE_TRUNCATE_CHARS),
                _truncate_for_table(tags_text, max_chars=_SEARCH_TABLE_TRUNCATE_CHARS),
            )

        console.print(table)
        tags_text = " OR ".join(tags_to_search)
        console.print(f"[cyan]tags={tags_text} displayed={len(displayed_items)}[/cyan]")
    finally:
        zotero.close()


# Main run command for the annotation pipeline (アノテーション処理パイプラインの実行コマンド)
def _validate_run_options(
    *,
    tag: Optional[str],
    item_keys: Optional[List[str]],
    max_items: int,
    delete_broken: bool,
    keep_broken: bool,
) -> None:
    # Validate numeric options (数値オプションのバリデーション)
    if max_items < 1:
        raise typer.BadParameter("--max-items must be >= 1")
    if tag and item_keys:
        raise typer.BadParameter("Specify either --tag or --item-key (repeatable), not both")
    if delete_broken and keep_broken:
        raise typer.BadParameter("Specify at most one of --delete-broken or --keep-broken")


def _build_translation_runtime(*, translate: bool) -> Tuple[Optional[object], str, str]:
    if not translate:
        return None, "", ""

    translation_runtime = get_translation_runtime()
    translator = build_translator()
    return translator, translation_runtime.source_lang, translation_runtime.target_lang


def _render_run_results(*, results: list[object], translate: bool) -> None:
    # Print per-item summary (論文ごとの実行結果を表示)
    for r in results:
        if r.skipped_reason:
            console.print(f"[yellow]SKIP[/yellow] {r.title} ({r.skipped_reason})")
            continue
        console.print(
            f"[green]DONE[/green] {r.title} planned={r.annotations_planned} created={r.annotations_created} dup={r.paragraphs_skipped_duplicate}"
        )
        console.print(f"{r.title} の処理完了" if not translate else f"{r.title} の翻訳完了")
        for w in (r.warnings or []):
            console.print(f"[yellow]WARN[/yellow] {r.title} ({w})")


def _run_annotations_command(
    *,
    tag: Optional[str],
    item_keys: Optional[List[str]],
    max_items: int,
    read_only: bool,
    translate: bool,
    delete_broken: bool,
    keep_broken: bool,
) -> None:
    def fail(stage: str, detail: str) -> None:
        console.print(f"[red]ERROR[/red] {stage}: {detail}")
        raise typer.Exit(code=1)

    _validate_run_options(
        tag=tag,
        item_keys=item_keys,
        max_items=max_items,
        delete_broken=delete_broken,
        keep_broken=keep_broken,
    )

    # Load runtime settings (.env から設定を読み込む)
    try:
        settings = get_core_settings()
        if settings.run_max_paragraphs_per_item < 1:
            raise typer.BadParameter("RUN_MAX_PARAGRAPHS_PER_ITEM must be >= 1")
        translator, source_lang, target_lang = _build_translation_runtime(translate=translate)
    except ValidationError as exc:
        fail("Invalid .env / environment variables", str(exc))
        return
    except RuntimeError as exc:
        fail("Translator provider error", str(exc))
        return

    do_delete_broken = delete_broken or (not keep_broken and settings.run_delete_broken_annotations)

    # Run no-translation pipeline (翻訳なしパイプラインを実行)
    try:
        results = run_no_translation(
            settings,
            dry_run=read_only,
            max_items=max_items,
            max_paragraphs_per_item=settings.run_max_paragraphs_per_item,
            annotation_mode=settings.annotation_mode,
            override_tag=tag,
            item_keys=item_keys,
            translator=translator,
            source_lang=source_lang,
            target_lang=target_lang,
            delete_broken_annotations=do_delete_broken,
        )
    except Exception as exc:
        fail("Pipeline crashed", str(exc))
        return

    _render_run_results(results=results, translate=translate)


@app.command()
def run(
    tag: Optional[str] = typer.Option(None, "--tag", help="Target tag override / 対象タグを上書き"),
    item_keys: Optional[List[str]] = typer.Option(
        None,
        "--item-key",
        help="Target item key (repeatable) / 対象item-key（複数指定可）",
    ),
    max_items: int = typer.Option(10, "--max-items", help="Max papers per run / 1回の最大論文数"),
    read_only: bool = typer.Option(
        False, "--read-only/--write", help="Do not write to Zotero / Zoteroに書き込まない"
    ),
    delete_broken: bool = typer.Option(
        False,
        "--delete-broken",
        help="Delete broken annotations before processing / 処理前に壊れ注釈を削除する",
    ),
    keep_broken: bool = typer.Option(
        False,
        "--keep-broken",
        help="Do not delete broken annotations (override env) / 壊れ注釈を削除しない",
    ),
) -> None:
    """Run translation + annotation pipeline (翻訳込みで注釈を作成する)."""
    _run_annotations_command(
        tag=tag,
        item_keys=item_keys,
        max_items=max_items,
        read_only=read_only,
        translate=True,
        delete_broken=delete_broken,
        keep_broken=keep_broken,
    )


@app.command()
def base(
    tag: Optional[str] = typer.Option(None, "--tag", help="Target tag override / 対象タグを上書き"),
    item_keys: Optional[List[str]] = typer.Option(
        None,
        "--item-key",
        help="Target item key (repeatable) / 対象item-key（複数指定可）",
    ),
    max_items: int = typer.Option(10, "--max-items", help="Max papers per run / 1回の最大論文数"),
    read_only: bool = typer.Option(
        False, "--read-only/--write", help="Do not write to Zotero / Zoteroに書き込まない"
    ),
    delete_broken: bool = typer.Option(
        False,
        "--delete-broken",
        help="Delete broken annotations before processing / 処理前に壊れ注釈を削除する",
    ),
    keep_broken: bool = typer.Option(
        False,
        "--keep-broken",
        help="Do not delete broken annotations (override env) / 壊れ注釈を削除しない",
    ),
) -> None:
    """Write base annotations without translation (翻訳なしで原文アノテーションを書き込む)."""
    _run_annotations_command(
        tag=tag,
        item_keys=item_keys,
        max_items=max_items,
        read_only=read_only,
        translate=False,
        delete_broken=delete_broken,
        keep_broken=keep_broken,
    )


@app.command()
def translate(
    item_keys: Optional[List[str]] = typer.Option(
        None,
        "--item-key",
        help="Target item key (repeatable) / 対象item-key（複数指定可）",
    ),
    max_items: int = typer.Option(10, "--max-items", help="Max papers per run / 1回の最大論文数"),
    read_only: bool = typer.Option(
        False, "--read-only/--write", help="Do not write to Zotero / Zoteroに書き込まない"
    ),
) -> None:
    """Translate existing annotation note bodies in-place (既存注釈本文をin-place翻訳更新する)."""
    if max_items < 1:
        raise typer.BadParameter("--max-items must be >= 1")

    def fail(stage: str, detail: str) -> None:
        console.print(f"[red]ERROR[/red] {stage}: {detail}")
        raise typer.Exit(code=1)

    try:
        settings = get_core_settings()
        translation_runtime = get_translation_runtime()
        translator = build_translator()
        source_lang = translation_runtime.source_lang
        target_lang = translation_runtime.target_lang
    except ValidationError as exc:
        fail("Invalid .env / environment variables", str(exc))
        return
    except RuntimeError as exc:
        fail("Translator provider error", str(exc))
        return

    try:
        override_tag = None if item_keys else settings.z_base_done_tag
        results = run_translate_existing_notes(
            settings,
            dry_run=read_only,
            max_items=max_items,
            translator=translator,
            source_lang=source_lang,
            target_lang=target_lang,
            override_tag=override_tag,
            item_keys=item_keys,
        )
    except Exception as exc:
        fail("Pipeline crashed", str(exc))
        return

    console.print(
        f"[cyan]translate[/cyan] mode={'read-only' if read_only else 'write'} items={len(results)}"
    )
    for r in results:
        if r.skipped_reason:
            console.print(f"[yellow]SKIP[/yellow] {r.title} ({r.skipped_reason})")
            continue
        console.print(
            f"[green]DONE[/green] {r.title} total={r.annotations_total} targeted={r.annotations_targeted} "
            f"processed={r.annotations_processed} updated={r.annotations_updated}"
        )
        if read_only:
            console.print(
                f"[cyan]READ-ONLY[/cyan] {r.title} planned_updates={r.annotations_processed} updated=0"
            )
        for w in (r.warnings or []):
            console.print(f"[yellow]WARN[/yellow] {r.title} ({w})")



# Dev command to annotate exactly one paragraph for position testing (位置検証のため1段落だけ注釈する開発用コマンド)
@dev_app.command("annotate")
def dev_annotate(
    item_key: str = typer.Option(..., "--item-key", help="Target item key / 対象アイテムキー"),
    paragraph_index: int = typer.Option(0, "--paragraph-index", help="0-based paragraph index / 0始まり段落インデックス"),
    read_only: bool = typer.Option(
        False, "--read-only/--write", help="Do not write to Zotero / Zoteroに書き込まない"
    ),
    translate: bool = typer.Option(
        False,
        "--translate/--no-translate",
        help="Translate before annotating / 注釈前に翻訳する",
    ),
    annotation_mode: Optional[str] = typer.Option(
        None,
        "--annotation-mode",
        help="Override output mode (note/highlight) / 出力モード上書き",
    ),
) -> None:
    
    """Annotate one paragraph for position checks (位置検証用に1段落だけ注釈)."""
    # Validate paragraph index (段落インデックスのバリデーション)
    if paragraph_index < 0:
        raise typer.BadParameter("--paragraph-index must be >= 0")

    # Print a staged error and exit with non-zero code (段階別エラーを表示して終了)
    def fail(stage: str, detail: str) -> None:
        console.print(f"[red]ERROR[/red] {stage}: {detail}")
        raise typer.Exit(code=1)

    # Load settings and create clients (設定読み込みとクライアント作成)
    settings = get_core_settings()
    zotero = ZoteroClient(
        base_url=settings.zotero_base_url,
        api_key=settings.z_api_key,
        scope=settings.z_scope,
        library_id=settings.z_id,
    )
    try:
        # Check target item existence early (対象アイテムの存在を先に確認)
        try:
            item = zotero.get_item(item_key)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            fail("Zotero item lookup failed", f"item_key={item_key} status={status}")
        except httpx.HTTPError as exc:
            fail("Zotero connection failed", f"item_key={item_key} detail={exc}")

        item_title = (item.get("data") or {}).get("title") or ""

        # Resolve PDF attachment from the target item (対象アイテムからPDF添付を解決)
        try:
            children = zotero.list_children(item_key)
        except httpx.HTTPError as exc:
            fail("Zotero connection failed", f"children fetch failed item_key={item_key} detail={exc}")

        pdf = zotero.pick_pdf_attachment(children)
        if not pdf:
            fail("PDF attachment missing", f"item_key={item_key}")
        pdf_key = pdf.get("key") or ""

        # Download PDF and extract paragraphs via PyMuPDF (PDF取得→PyMuPDFで段落抽出)
        try:
            pdf_bytes = zotero.download_attachment(zotero.build_file_url(pdf_key))
        except httpx.HTTPError as exc:
            fail("Zotero connection failed", f"pdf download failed pdf_key={pdf_key} detail={exc}")

        page_sizes = get_pdf_page_sizes(pdf_bytes)

        try:
            paragraphs = extract_paragraphs_from_pdf_bytes(pdf_bytes, settings=settings)
        except (ValueError, RuntimeError, httpx.HTTPError) as exc:
            fail("Paragraph extraction failed", str(exc))

        if not paragraphs:
            fail("No paragraphs extracted", f"item_key={item_key} pdf_key={pdf_key} paragraphs=0")

        # Validate selected paragraph index (指定段落インデックスの妥当性確認)
        if paragraph_index >= len(paragraphs):
            fail(
                "Paragraph index out of range",
                f"item_key={item_key} paragraph_index={paragraph_index} paragraphs={len(paragraphs)}",
            )
        p = paragraphs[paragraph_index]
        dedup_tags = [f"{settings.dedup_tag_prefix}{h}" for h in (p.dedup_hashes or [p.hash])]

        # Optional: translate paragraph text for annotation comment (必要なら段落本文を翻訳して注釈コメントにする)
        source_text = p.text
        comment_text = source_text
        if translate:
            translation_runtime = get_translation_runtime()
            translator = build_translator()
            source_lang = translation_runtime.source_lang
            target_lang = translation_runtime.target_lang
            try:
                comment_text = translator.translate(
                    _build_paragraph_translation_input(
                        paragraphs,
                        paragraph_index,
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
                fail("Translation failed", f"kind={exc.kind} provider={exc.provider} status={exc.status_code} detail={exc}")

        # Check duplication by para:<hash> tag (para:<hash> で重複判定)
        try:
            existing = list(zotero.iter_annotations(parent_key=pdf_key, limit_per_page=100))
        except httpx.HTTPError as exc:
            fail("Zotero connection failed", f"annotations fetch failed pdf_key={pdf_key} detail={exc}")

        existing_tags = set()
        for ann in existing:
            for t in zotero.extract_tag_names(ann):
                existing_tags.add(t)
        if any(t in existing_tags for t in dedup_tags):
            console.print(f"[yellow]SKIP[/yellow] duplicate paragraph tag found: {dedup_tags[0]}")
            console.print(
                f"[bold white]item_key[/bold white]=[cyan]{item_key}[/cyan] "
                f"[bold white]pdf_key[/bold white]=[cyan]{pdf_key}[/cyan] "
                f"[bold white]paragraph_index[/bold white]=[green]{paragraph_index}[/green] "
                f"[bold white]page[/bold white]=[green]{p.page}[/green] "
                f"[bold white]hash[/bold white]=[magenta]{p.hash}[/magenta]",
                highlight=False,
            )
            return

        mode = (annotation_mode or settings.annotation_mode).strip()
        if mode not in ("note", "highlight"):
            raise typer.BadParameter("--annotation-mode must be one of: note, highlight")

        payload = build_annotation_payload(
            paragraph=p,
            comment_text=comment_text,
            pdf_key=pdf_key,
            dedup_tags=dedup_tags,
            annotation_mode=mode,  # type: ignore[arg-type]
            page_sizes=page_sizes,
        )

        # Read-only prints payload; write creates one annotation (read-onlyは表示のみ、writeは1件作成)
        if read_only:
            console.print("[cyan]READ-ONLY: planned single annotation payload[/cyan]")
            console.print(
                f"[bold white]item_key[/bold white]=[cyan]{item_key}[/cyan] "
                f"[bold white]pdf_key[/bold white]=[cyan]{pdf_key}[/cyan] "
                f"[bold white]paragraph_index[/bold white]=[green]{paragraph_index}[/green] "
                f"[bold white]page[/bold white]=[green]{p.page}[/green] "
                f"[bold white]hash[/bold white]=[magenta]{p.hash}[/magenta] "
                f"[bold white]title[/bold white]=[yellow]{item_title}[/yellow]",
                highlight=False,
            )
            console.print_json(json.dumps(payload, ensure_ascii=False))
            return

        try:
            zotero.create_annotations([payload])
        except httpx.HTTPError as exc:
            fail("Annotation creation failed", f"pdf_key={pdf_key} paragraph_index={paragraph_index} detail={exc}")

        console.print("[green]DONE[/green] 1 annotation created")
        console.print(
            f"[bold white]item_key[/bold white]=[cyan]{item_key}[/cyan] "
            f"[bold white]pdf_key[/bold white]=[cyan]{pdf_key}[/cyan] "
            f"[bold white]paragraph_index[/bold white]=[green]{paragraph_index}[/green] "
            f"[bold white]page[/bold white]=[green]{p.page}[/green] "
            f"[bold white]hash[/bold white]=[magenta]{p.hash}[/magenta] "
            f"[bold white]tag[/bold white]=[yellow]{dedup_tags[0]}[/yellow]",
            highlight=False,
        )
    finally:
        # Ensure clients are closed (クライアントを確実にクローズ)
        zotero.close()


# Dev command to translate exactly one paragraph (1段落だけ翻訳して確認する開発用コマンド)
@dev_app.command("translate")
def dev_translate(
    item_key: str = typer.Option(..., "--item-key", help="Target item key / 対象アイテムキー"),
    paragraph_index: int = typer.Option(0, "--paragraph-index", help="0-based paragraph index / 0始まり段落インデックス"),
) -> None:
    """Translate one paragraph (1段落だけ翻訳して表示)."""
    # Validate paragraph index (段落インデックスのバリデーション)
    if paragraph_index < 0:
        raise typer.BadParameter("--paragraph-index must be >= 0")

    # Print a staged error and exit with non-zero code (段階別エラーを表示して終了)
    def fail(stage: str, detail: str) -> None:
        console.print(f"[red]ERROR[/red] {stage}: {detail}")
        raise typer.Exit(code=1)

    # Load settings and create clients (設定読み込みとクライアント作成)
    settings = get_core_settings()
    translation_runtime = get_translation_runtime()
    translator = build_translator()
    source_lang = translation_runtime.source_lang
    target_lang = translation_runtime.target_lang

    zotero = ZoteroClient(
        base_url=settings.zotero_base_url,
        api_key=settings.z_api_key,
        scope=settings.z_scope,
        library_id=settings.z_id,
    )
    try:
        # Check target item existence early (対象アイテムの存在を先に確認)
        try:
            item = zotero.get_item(item_key)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            fail("Zotero item lookup failed", f"item_key={item_key} status={status}")
        except httpx.HTTPError as exc:
            fail("Zotero connection failed", f"item_key={item_key} detail={exc}")

        item_title = (item.get("data") or {}).get("title") or ""

        # Resolve PDF attachment from the target item (対象アイテムからPDF添付を解決)
        try:
            children = zotero.list_children(item_key)
        except httpx.HTTPError as exc:
            fail("Zotero connection failed", f"children fetch failed item_key={item_key} detail={exc}")

        pdf = zotero.pick_pdf_attachment(children)
        if not pdf:
            fail("PDF attachment missing", f"item_key={item_key}")
        pdf_key = pdf.get("key") or ""

        # Download PDF and extract paragraphs via PyMuPDF (PDF取得→PyMuPDFで段落抽出)
        try:
            pdf_bytes = zotero.download_attachment(zotero.build_file_url(pdf_key))
        except httpx.HTTPError as exc:
            fail("Zotero connection failed", f"pdf download failed pdf_key={pdf_key} detail={exc}")

        try:
            paragraphs = extract_paragraphs_from_pdf_bytes(pdf_bytes, settings=settings)
        except (ValueError, RuntimeError, httpx.HTTPError) as exc:
            fail("Paragraph extraction failed", str(exc))
        if not paragraphs:
            fail("No paragraphs extracted", f"item_key={item_key} pdf_key={pdf_key} paragraphs=0")
        if paragraph_index >= len(paragraphs):
            fail(
                "Paragraph index out of range",
                f"item_key={item_key} paragraph_index={paragraph_index} paragraphs={len(paragraphs)}",
            )

        p = paragraphs[paragraph_index]

        # Translate and print (翻訳して表示)
        try:
            result = translator.translate(
                _build_paragraph_translation_input(
                    paragraphs,
                    paragraph_index,
                    source_lang=source_lang,
                    target_lang=target_lang,
                )
            )
        except TranslationError as exc:
            fail("Translation failed", f"kind={exc.kind} provider={exc.provider} status={exc.status_code} detail={exc}")
        console.print(
            f"[bold white]item_key[/bold white]=[cyan]{item_key}[/cyan] "
            f"[bold white]pdf_key[/bold white]=[cyan]{pdf_key}[/cyan] "
            f"[bold white]paragraph_index[/bold white]=[green]{paragraph_index}[/green] "
            f"[bold white]page[/bold white]=[green]{p.page}[/green] "
            f"[bold white]provider[/bold white]=[yellow]{result.provider}[/yellow] "
            f"[bold white]target_lang[/bold white]=[yellow]{target_lang}[/yellow] "
            f"[bold white]title[/bold white]=[green]{item_title}[/green]",
            highlight=False,
        )
        console.print("[bold cyan]SOURCE[/bold cyan]")
        console.print(p.text)
        console.print("\n[bold magenta]TRANSLATED[/bold magenta]")
        console.print(result.text)
    finally:
        # Ensure clients are closed (クライアントを確実にクローズ)
        zotero.close()


@dev_app.command("dump-xml")
def dev_dump_xml(
    item_key: str = typer.Option(..., "--item-key", help="Target item key / 対象アイテムキー"),
    out_pymupdf: Path = typer.Option(
        Path("pymupdf.paragraphs.xml"),
        "--out-pymupdf",
        help="Output PyMuPDF paragraphs XML path / PyMuPDF段落XML出力先",
    ),
    drop_captions: bool = typer.Option(
        False, "--drop-captions", help="Drop figure/table captions in PyMuPDF output / PyMuPDF側でキャプション除外"
    ),
) -> None:
    """
    Dump PyMuPDF extracted paragraphs XML from the same PDF attachment.
    """

    def fail(stage: str, detail: str) -> None:
        console.print(f"[red]ERROR[/red] {stage}: {detail}")
        raise typer.Exit(code=1)

    settings = get_core_settings()
    zotero = ZoteroClient(
        base_url=settings.zotero_base_url,
        api_key=settings.z_api_key,
        scope=settings.z_scope,
        library_id=settings.z_id,
    )
    try:
        try:
            item = zotero.get_item(item_key)
        except httpx.HTTPError as exc:
            fail("Zotero connection failed", f"item lookup failed item_key={item_key} detail={exc}")

        item_title = (item.get("data") or {}).get("title") or ""

        try:
            children = zotero.list_children(item_key)
        except httpx.HTTPError as exc:
            fail("Zotero connection failed", f"children fetch failed item_key={item_key} detail={exc}")

        pdf = zotero.pick_pdf_attachment(children)
        if not pdf:
            fail("PDF attachment missing", f"item_key={item_key}")
        pdf_key = pdf.get("key") or ""

        try:
            pdf_bytes = zotero.download_attachment(zotero.build_file_url(pdf_key))
        except httpx.HTTPError as exc:
            fail("Zotero connection failed", f"pdf download failed pdf_key={pdf_key} detail={exc}")

        # PyMuPDF paragraphs XML (tool-internal XML; not TEI)
        # NOTE: PyMuPDF backend now marks captions as `is_caption` instead of dropping at extraction time.
        cfg = PyMuPDFExtractionConfig()
        paras = extract_paragraphs_pymupdf_bytes(pdf_bytes, config=cfg)
        if drop_captions:
            paras = [p for p in paras if not p.get("is_caption")]
        out_pymupdf.write_text(paragraphs_to_xml(paras), encoding="utf-8")

        console.print(
            f"[green]Wrote[/green] pymupdf={out_pymupdf} "
            f"item_key={item_key} pdf_key={pdf_key} title={item_title}",
            highlight=False,
        )
    finally:
        zotero.close()


@dev_app.command("dump-pymupdf-raw-text")
def dev_dump_pymupdf_raw_text(
    item_key: str = typer.Option(..., "--item-key", help="Target item key / 対象アイテムキー"),
    out: Optional[Path] = typer.Option(
        None,
        "--out",
        help="Output JSON path / 出力JSONパス（省略時は pymupdf.raw.<item_key>.json）",
    ),
    out_text: Optional[Path] = typer.Option(
        None,
        "--out-text",
        help="Optional output plain text path / 追加でプレーンテキストも出力したい場合のパス",
    ),
) -> None:
    """
    Dump PyMuPDF page-level raw text WITHOUT paragraphization/filters.

    This is intended to debug whether missing content happens before or after
    our paragraph detection pipeline.
    """

    def fail(stage: str, detail: str) -> None:
        console.print(f"[red]ERROR[/red] {stage}: {detail}")
        raise typer.Exit(code=1)

    try:
        import fitz  # type: ignore
    except Exception as exc:
        fail("PyMuPDF import failed", f"detail={exc}")
        return

    settings = get_core_settings()
    zotero = ZoteroClient(
        base_url=settings.zotero_base_url,
        api_key=settings.z_api_key,
        scope=settings.z_scope,
        library_id=settings.z_id,
    )
    try:
        try:
            item = zotero.get_item(item_key)
        except httpx.HTTPError as exc:
            fail("Zotero connection failed", f"item lookup failed item_key={item_key} detail={exc}")

        item_title = (item.get("data") or {}).get("title") or ""

        try:
            children = zotero.list_children(item_key)
        except httpx.HTTPError as exc:
            fail("Zotero connection failed", f"children fetch failed item_key={item_key} detail={exc}")

        pdf = zotero.pick_pdf_attachment(children)
        if not pdf:
            fail("PDF attachment missing", f"item_key={item_key}")
        pdf_key = pdf.get("key") or ""

        try:
            pdf_bytes = zotero.download_attachment(zotero.build_file_url(pdf_key))
        except httpx.HTTPError as exc:
            fail("Zotero connection failed", f"pdf download failed pdf_key={pdf_key} detail={exc}")

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            pages = []
            total_chars = 0
            for page_index in range(doc.page_count):
                page = doc.load_page(page_index)
                text = page.get_text("text") or ""
                # Replace C0 control characters (except TAB/LF/CR) to keep output portable.
                text = "".join(
                    ch if (ord(ch) >= 0x20 or ord(ch) in (0x09, 0x0A, 0x0D)) else " " for ch in text
                )
                chars = len(text)
                total_chars += chars
                pages.append({"page": page_index + 1, "chars": chars, "text": text})
        finally:
            doc.close()

        payload = {
            "item_key": item_key,
            "pdf_key": pdf_key,
            "title": item_title,
            "page_count": len(pages),
            "total_chars": total_chars,
            "pages": pages,
        }

        out_path = out or Path(f"pymupdf.raw.{item_key}.json")
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        if out_text:
            chunks = []
            for p in pages:
                chunks.append(f"=== PAGE {p['page']} (chars={p['chars']}) ===\n")
                chunks.append(p["text"])
                if not str(p["text"]).endswith("\n"):
                    chunks.append("\n")
                chunks.append("\n")
            out_text.write_text("".join(chunks), encoding="utf-8")

        console.print(
            f"[green]Wrote[/green] {out_path}"
            + (f" and {out_text}" if out_text else "")
            + f" item_key={item_key} pdf_key={pdf_key} title={item_title} total_chars={total_chars}",
            highlight=False,
        )
    finally:
        zotero.close()


@dev_app.command("dump-pymupdf-dict")
def dev_dump_pymupdf_dict(
    item_key: str = typer.Option(..., "--item-key", help="Target item key / 対象アイテムキー"),
    out: Optional[Path] = typer.Option(
        None,
        "--out",
        help="Output JSON path / 出力JSONパス（省略時は pymupdf.dict.<item_key>.json）",
    ),
    include_binary: bool = typer.Option(
        False,
        "--include-binary",
        help="Include binary blobs (base64) in JSON / バイナリ(bytes)もbase64でJSONに含める（巨大化注意）",
    ),
) -> None:
    """
    Dump PyMuPDF page.get_text(\"dict\") outputs WITHOUT any processing.

    This is the closest to \"throw PDF into PyMuPDF and dump the raw result\" while still
    fetching the PDF from Zotero by item-key.
    """

    def fail(stage: str, detail: str) -> None:
        console.print(f"[red]ERROR[/red] {stage}: {detail}")
        raise typer.Exit(code=1)

    try:
        import fitz  # type: ignore
    except Exception as exc:
        fail("PyMuPDF import failed", f"detail={exc}")
        return

    settings = get_core_settings()
    zotero = ZoteroClient(
        base_url=settings.zotero_base_url,
        api_key=settings.z_api_key,
        scope=settings.z_scope,
        library_id=settings.z_id,
    )
    try:
        try:
            item = zotero.get_item(item_key)
        except httpx.HTTPError as exc:
            fail("Zotero connection failed", f"item lookup failed item_key={item_key} detail={exc}")

        item_title = (item.get("data") or {}).get("title") or ""

        try:
            children = zotero.list_children(item_key)
        except httpx.HTTPError as exc:
            fail("Zotero connection failed", f"children fetch failed item_key={item_key} detail={exc}")

        pdf = zotero.pick_pdf_attachment(children)
        if not pdf:
            fail("PDF attachment missing", f"item_key={item_key}")
        pdf_key = pdf.get("key") or ""

        try:
            pdf_bytes = zotero.download_attachment(zotero.build_file_url(pdf_key))
        except httpx.HTTPError as exc:
            fail("Zotero connection failed", f"pdf download failed pdf_key={pdf_key} detail={exc}")

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            pages = []
            for page_index in range(doc.page_count):
                page = doc.load_page(page_index)
                pages.append(
                    {
                        "page": page_index + 1,
                        "width": float(page.rect.width),
                        "height": float(page.rect.height),
                        "dict": page.get_text("dict"),
                    }
                )
        finally:
            doc.close()

        payload = {
            "item_key": item_key,
            "pdf_key": pdf_key,
            "title": item_title,
            "page_count": len(pages),
            "pages": pages,
        }

        out_path = out or Path(f"pymupdf.dict.{item_key}.json")
        def _json_default(o: object) -> object:
            # PyMuPDF dict can include image bytes; JSON can't encode bytes.
            if isinstance(o, (bytes, bytearray)):
                b = bytes(o)
                h = sha1(b).hexdigest()
                if include_binary:
                    return {
                        "__type__": "bytes",
                        "encoding": "base64",
                        "len": len(b),
                        "sha1": h,
                        "data": base64.b64encode(b).decode("ascii"),
                    }
                return {"__type__": "bytes", "len": len(b), "sha1": h}
            # Fallback: string representation
            return str(o)

        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
            encoding="utf-8",
        )

        console.print(
            f"[green]Wrote[/green] {out_path} item_key={item_key} pdf_key={pdf_key} title={item_title} pages={len(pages)}",
            highlight=False,
        )
    finally:
        zotero.close()


@dev_app.command("reconstruct-from-pymupdf-dict")
def dev_reconstruct_from_pymupdf_dict(
    in_path: Path = typer.Option(..., "--in", help="Input pymupdf.dict JSON path / pymupdf.dict JSON入力パス"),
    out_xml: Path = typer.Option(
        Path("pymupdf.paragraphs.fromdict.xml"),
        "--out-xml",
        help="Output paragraphs XML path / 段落XML出力先",
    ),
    out_json: Optional[Path] = typer.Option(
        None,
        "--out-json",
        help="Optional output paragraphs JSON path / 段落JSON出力先（任意）",
    ),
    drop_captions: bool = typer.Option(
        False,
        "--drop-captions",
        help="Drop figure/table captions / キャプション（Figure/Table）を除外",
    ),
) -> None:
    """
    Reconstruct paragraphs from a dumped `page.get_text('dict')` JSON.

    This is offline and does not require Zotero/API access.
    """
    payload = json.loads(in_path.read_text(encoding="utf-8"))
    paras = extract_paragraphs_from_pymupdf_dict(payload, config=PyMuPDFExtractionConfig())
    if drop_captions:
        paras = [p for p in paras if not p.get("is_caption")]

    out_xml.write_text(paragraphs_to_xml(paras), encoding="utf-8")
    if out_json:
        out_json.write_text(json.dumps(paras, ensure_ascii=False, indent=2), encoding="utf-8")

    console.print(f"[green]Wrote[/green] {out_xml}" + (f" and {out_json}" if out_json else ""), highlight=False)


# Dev command to inspect extracted paragraphs (段落抽出結果を確認する開発用コマンド)
@dev_app.command("paragraphs")
def dev_paragraphs(
    item_key: str = typer.Option(..., "--item-key", help="Target item key / 対象アイテムキー"),
    out: Optional[Path] = typer.Option(None, "--out", help="Output JSON path / JSON出力先"),
    max_rows: int = typer.Option(20, "--max-rows", help="Max rows to print / 表示する最大件数"),
) -> None:
    """Inspect extracted paragraphs from item PDF (PyMuPDF backend)."""
    if max_rows < 1:
        raise typer.BadParameter("--max-rows must be >= 1")

    def fail(stage: str, detail: str) -> None:
        console.print(f"[red]ERROR[/red] {stage}: {detail}")
        raise typer.Exit(code=1)

    settings = get_core_settings()
    zotero = ZoteroClient(
        base_url=settings.zotero_base_url,
        api_key=settings.z_api_key,
        scope=settings.z_scope,
        library_id=settings.z_id,
    )
    try:
        try:
            children = zotero.list_children(item_key)
        except httpx.HTTPError as exc:
            fail("Zotero connection failed", f"children fetch failed item_key={item_key} detail={exc}")
        pdf = zotero.pick_pdf_attachment(children)
        if not pdf:
            raise typer.BadParameter("No PDF attachment found for --item-key")
        pdf_key = pdf.get("key") or ""
        try:
            pdf_bytes = zotero.download_attachment(zotero.build_file_url(pdf_key))
        except httpx.HTTPError as exc:
            fail("Zotero connection failed", f"pdf download failed pdf_key={pdf_key} detail={exc}")
        try:
            rows = extract_paragraphs_from_pdf_bytes(pdf_bytes, settings=settings)
        except (ValueError, RuntimeError, httpx.HTTPError) as exc:
            fail("Paragraph extraction failed", str(exc))
    finally:
        zotero.close()

    console.print(f"[cyan]paragraphs={len(rows)}[/cyan]")

    # Build preview payload (プレビュー用ペイロードを生成)
    preview = rows[:max_rows]
    payload = []
    for i, p in enumerate(preview):
        row = {
            "index": i,
            "hash": p.hash,
            "dedup_hashes": p.dedup_hashes,
            "page": p.page,
            "text": p.text,
            "coords": [c.__dict__ for c in p.coords],
        }
        payload.append(row)

    # Output JSON to file or console (JSONをファイル出力またはコンソール表示)
    if out:
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        console.print(f"[green]Wrote[/green] {out}")
    else:
        console.print_json(json.dumps(payload, ensure_ascii=False))


@dev_app.command("repair-annotations")
def dev_repair_annotations(
    item_key: str = typer.Option(..., "--item-key", help="Target item key / 対象アイテムキー"),
    read_only: bool = typer.Option(
        False, "--read-only/--write", help="Do not write to Zotero / Zoteroに書き込まない"
    ),
) -> None:
    """
    Repair existing annotation items that are missing required fields like
    annotationSortIndex/annotationPosition/annotationPageLabel.

    (必須フィールドが欠けている注釈を修復する)
    """

    def fail(stage: str, detail: str) -> None:
        console.print(f"[red]ERROR[/red] {stage}: {detail}")
        raise typer.Exit(code=1)

    settings = get_core_settings()
    zotero = ZoteroClient(
        base_url=settings.zotero_base_url,
        api_key=settings.z_api_key,
        scope=settings.z_scope,
        library_id=settings.z_id,
    )
    try:
        try:
            item = zotero.get_item(item_key)
        except httpx.HTTPError as exc:
            fail("Zotero connection failed", f"item lookup failed item_key={item_key} detail={exc}")

        item_title = (item.get("data") or {}).get("title") or ""

        try:
            children = zotero.list_children(item_key)
        except httpx.HTTPError as exc:
            fail("Zotero connection failed", f"children fetch failed item_key={item_key} detail={exc}")

        pdf = zotero.pick_pdf_attachment(children)
        if not pdf:
            fail("PDF attachment missing", f"item_key={item_key}")
        pdf_key = pdf.get("key") or ""

        try:
            pdf_bytes = zotero.download_attachment(zotero.build_file_url(pdf_key))
        except httpx.HTTPError as exc:
            fail("Zotero connection failed", f"pdf download failed pdf_key={pdf_key} detail={exc}")
        page_sizes = get_pdf_page_sizes(pdf_bytes)

        try:
            paragraphs = extract_paragraphs_from_pdf_bytes(pdf_bytes, settings=settings)
        except (ValueError, RuntimeError, httpx.HTTPError) as exc:
            fail("Paragraph extraction failed", str(exc))

        # Map para:<hash> -> computed position fields
        pos_by_tag = {}
        for p in paragraphs:
            note_pos = build_note_position(p, page_sizes=page_sizes)
            patch = {
                "annotationPosition": json.dumps(note_pos.annotation_position),
                "annotationPageLabel": str(note_pos.page_index + 1),
                "annotationSortIndex": note_pos.annotation_sort_index,
            }
            for h in (p.dedup_hashes or [p.hash]):
                pos_by_tag[f"{settings.dedup_tag_prefix}{h}"] = patch

        try:
            anns = list(zotero.iter_annotations(parent_key=pdf_key, limit_per_page=100))
        except httpx.HTTPError as exc:
            fail("Zotero connection failed", f"annotations fetch failed pdf_key={pdf_key} detail={exc}")

        planned = 0
        repaired = 0
        unmatched = 0
        missing_tag = 0
        for ann in anns:
            ann_key = ann.get("key") or ""
            data = dict(ann.get("data") or {})
            tags = zotero.extract_tag_names(ann)
            dedup_tags = [t for t in tags if t.startswith(settings.dedup_tag_prefix)]
            if not dedup_tags:
                missing_tag += 1
                continue

            # Only repair ones missing required fields
            sort_index = data.get("annotationSortIndex")
            page_label = data.get("annotationPageLabel")
            position = data.get("annotationPosition")
            has_sort_index = isinstance(sort_index, str) and bool(sort_index.strip())
            has_page_label = isinstance(page_label, str) and bool(page_label.strip())
            has_position = (isinstance(position, str) and bool(position.strip())) or isinstance(position, dict)
            needs = not (has_sort_index and has_page_label and has_position)
            if not needs:
                continue

            ref_tag = next((t for t in dedup_tags if t in pos_by_tag), None)
            if not ref_tag:
                unmatched += 1
                continue

            planned += 1
            patch = pos_by_tag[ref_tag]
            data.setdefault("key", ann_key)
            data.setdefault("itemType", "annotation")
            data.setdefault("annotationType", "note")
            data.update(patch)

            version = ann.get("version")
            if read_only:
                console.print(
                    f"[cyan]READ-ONLY[/cyan] repair annotation_key={ann_key} tag={ref_tag} title={item_title}",
                    highlight=False,
                )
                continue

            try:
                zotero.update_item(item_key=ann_key, data=data, version=version)
                repaired += 1
            except httpx.HTTPError as exc:
                console.print(
                    f"[yellow]WARN[/yellow] repair failed annotation_key={ann_key} detail={exc}",
                    highlight=False,
                )

        console.print(
            f"[green]DONE[/green] item_key={item_key} pdf_key={pdf_key} title={item_title} planned={planned} repaired={repaired} unmatched={unmatched} no_para_tag={missing_tag}",
            highlight=False,
        )
    finally:
        zotero.close()


@dev_app.command("delete-broken-annotations")
def dev_delete_broken_annotations(
    item_key: str = typer.Option(..., "--item-key", help="Target item key / 対象アイテムキー"),
    read_only: bool = typer.Option(
        False, "--read-only/--write", help="Do not write to Zotero / Zoteroに書き込まない"
    ),
) -> None:
    """Delete broken annotations missing required fields (壊れた注釈を削除する)."""

    def fail(stage: str, detail: str) -> None:
        console.print(f"[red]ERROR[/red] {stage}: {detail}")
        raise typer.Exit(code=1)

    settings = get_core_settings()
    zotero = ZoteroClient(
        base_url=settings.zotero_base_url,
        api_key=settings.z_api_key,
        scope=settings.z_scope,
        library_id=settings.z_id,
    )
    try:
        try:
            children = zotero.list_children(item_key)
        except httpx.HTTPError as exc:
            fail("Zotero connection failed", f"children fetch failed item_key={item_key} detail={exc}")

        pdf = zotero.pick_pdf_attachment(children)
        if not pdf:
            fail("PDF attachment missing", f"item_key={item_key}")
        pdf_key = pdf.get("key") or ""

        broken = []
        for ann in zotero.iter_annotations(parent_key=pdf_key, limit_per_page=100):
            ann_key = ann.get("key") or ""
            data = ann.get("data") or {}
            sort_index = data.get("annotationSortIndex")
            page_label = data.get("annotationPageLabel")
            position = data.get("annotationPosition")

            has_sort_index = isinstance(sort_index, str) and bool(sort_index.strip())
            has_page_label = isinstance(page_label, str) and bool(page_label.strip())
            has_position = (isinstance(position, str) and bool(position.strip())) or isinstance(position, dict)
            if has_sort_index and has_page_label and has_position:
                continue
            broken.append(ann)

        if read_only:
            console.print(
                f"[cyan]READ-ONLY[/cyan] item_key={item_key} pdf_key={pdf_key} broken={len(broken)}",
                highlight=False,
            )
            for ann in broken[:10]:
                console.print(f"- annotation_key={ann.get('key')}", highlight=False)
            return

        deleted = 0
        for ann in broken:
            ann_key = ann.get("key") or ""
            version = ann.get("version")
            try:
                zotero.delete_item(item_key=ann_key, version=version if isinstance(version, int) else None)
                deleted += 1
            except httpx.HTTPError as exc:
                console.print(f"[yellow]WARN[/yellow] delete failed annotation_key={ann_key} detail={exc}", highlight=False)

        console.print(
            f"[green]DONE[/green] item_key={item_key} pdf_key={pdf_key} broken={len(broken)} deleted={deleted}",
            highlight=False,
        )
    finally:
        zotero.close()


@dev_app.command("delete-all-annotations")
def dev_delete_all_annotations(
    item_key: str = typer.Option(
        ...,
        "--item-key",
        help="Target item key whose PDF annotations will be deleted / PDF注釈を全削除する対象item-key",
    ),
    read_only: bool = typer.Option(
        False,
        "--read-only/--write",
        help="Preview matching annotations without deleting / --writeでZotero上の対象PDF注釈を全削除",
    ),
) -> None:
    """Delete all PDF annotations for the target item (対象itemのPDF注釈を全削除する)."""

    def fail(stage: str, detail: str) -> None:
        console.print(f"[red]ERROR[/red] {stage}: {detail}")
        raise typer.Exit(code=1)

    settings = get_core_settings()
    zotero = ZoteroClient(
        base_url=settings.zotero_base_url,
        api_key=settings.z_api_key,
        scope=settings.z_scope,
        library_id=settings.z_id,
    )
    try:
        try:
            children = zotero.list_children(item_key)
        except httpx.HTTPError as exc:
            fail("Zotero connection failed", f"children fetch failed item_key={item_key} detail={exc}")

        pdf = zotero.pick_pdf_attachment(children)
        if not pdf:
            fail("PDF attachment missing", f"item_key={item_key}")
        pdf_key = pdf.get("key") or ""

        anns = list(zotero.iter_annotations(parent_key=pdf_key, limit_per_page=100))
        total = len(anns)
        if read_only:
            console.print(
                f"[cyan]READ-ONLY[/cyan] item_key={item_key} pdf_key={pdf_key} annotations={total}",
                highlight=False,
            )
            for ann in anns[:10]:
                console.print(f"- annotation_key={ann.get('key')}", highlight=False)
            return

        deleted = 0
        for ann in anns:
            ann_key = ann.get("key") or ""
            version = ann.get("version")
            try:
                zotero.delete_item(item_key=ann_key, version=version if isinstance(version, int) else None)
                deleted += 1
            except httpx.HTTPError as exc:
                console.print(f"[yellow]WARN[/yellow] delete failed annotation_key={ann_key} detail={exc}", highlight=False)

        console.print(
            f"[green]DONE[/green] item_key={item_key} pdf_key={pdf_key} annotations={total} deleted={deleted}",
            highlight=False,
        )
    finally:
        zotero.close()


@dev_app.command("audit-annotations")
def dev_audit_annotations(
    item_key: str = typer.Option(..., "--item-key", help="Target item key / 対象アイテムキー"),
    max_problem_rows: int = typer.Option(10, "--max-problem-rows", help="Max problem rows to print / 問題行の最大表示数"),
) -> None:
    """Audit extracted paragraphs vs existing Zotero annotations (段落と注釈の突き合わせ監査)."""

    if max_problem_rows < 0:
        raise typer.BadParameter("--max-problem-rows must be >= 0")

    def fail(stage: str, detail: str) -> None:
        console.print(f"[red]ERROR[/red] {stage}: {detail}")
        raise typer.Exit(code=1)

    settings = get_core_settings()
    zotero = ZoteroClient(
        base_url=settings.zotero_base_url,
        api_key=settings.z_api_key,
        scope=settings.z_scope,
        library_id=settings.z_id,
    )
    try:
        try:
            item = zotero.get_item(item_key)
        except httpx.HTTPError as exc:
            fail("Zotero connection failed", f"item lookup failed item_key={item_key} detail={exc}")

        item_title = (item.get("data") or {}).get("title") or ""

        try:
            children = zotero.list_children(item_key)
        except httpx.HTTPError as exc:
            fail("Zotero connection failed", f"children fetch failed item_key={item_key} detail={exc}")

        pdf = zotero.pick_pdf_attachment(children)
        if not pdf:
            fail("PDF attachment missing", f"item_key={item_key}")
        pdf_key = pdf.get("key") or ""

        try:
            pdf_bytes = zotero.download_attachment(zotero.build_file_url(pdf_key))
        except httpx.HTTPError as exc:
            fail("Zotero connection failed", f"pdf download failed pdf_key={pdf_key} detail={exc}")

        paras_filtered = extract_paragraphs_from_pdf_bytes(pdf_bytes, settings=settings)

        settings_all = settings.model_copy(
            update={
                "para_min_chars": 0,
                "para_max_chars": max(settings.para_max_chars, 20000),
            }
        )
        paras_all = extract_paragraphs_from_pdf_bytes(pdf_bytes, settings=settings_all)

        required_filtered = {
            f"{settings.dedup_tag_prefix}{h}"
            for p in paras_filtered
            for h in (p.dedup_hashes or [p.hash])
        }
        required_all = {
            f"{settings.dedup_tag_prefix}{h}"
            for p in paras_all
            for h in (p.dedup_hashes or [p.hash])
        }

        try:
            anns = list(zotero.iter_annotations(parent_key=pdf_key, limit_per_page=100))
        except httpx.HTTPError as exc:
            fail("Zotero connection failed", f"annotations fetch failed pdf_key={pdf_key} detail={exc}")

        ann_dedup_tags = set()
        missing_sort = []
        missing_page = []
        missing_pos = []
        invalid_pos = []

        for ann in anns:
            data = ann.get("data") or {}
            tags = zotero.extract_tag_names(ann)
            for t in tags:
                if isinstance(t, str) and t.startswith(settings.dedup_tag_prefix):
                    ann_dedup_tags.add(t)

            ann_key = ann.get("key") or ""
            sort_index = data.get("annotationSortIndex")
            page_label = data.get("annotationPageLabel")
            position = data.get("annotationPosition")

            if not (isinstance(sort_index, str) and sort_index.strip()):
                missing_sort.append(ann_key)
            if not (isinstance(page_label, str) and page_label.strip()):
                missing_page.append(ann_key)

            if isinstance(position, dict):
                pass
            elif isinstance(position, str) and position.strip():
                try:
                    json.loads(position)
                except Exception:
                    invalid_pos.append(ann_key)
            else:
                missing_pos.append(ann_key)

        missing_filtered = sorted(required_filtered - ann_dedup_tags)
        missing_all = sorted(required_all - ann_dedup_tags)

        console.print(
            f"[bold cyan]AUDIT[/bold cyan] item_key={item_key} pdf_key={pdf_key} title={item_title}",
            highlight=False,
        )
        console.print(
            f"[cyan]paragraphs[/cyan] filtered={len(paras_filtered)} all={len(paras_all)} "
            f"[cyan]annotations[/cyan] total={len(anns)} dedup_tags={len(ann_dedup_tags)}",
            highlight=False,
        )
        console.print(
            f"[cyan]missing dedup tags[/cyan] filtered={len(missing_filtered)} all={len(missing_all)}",
            highlight=False,
        )
        console.print(
            f"[cyan]invalid fields[/cyan] missing_sortIndex={len(missing_sort)} missing_pageLabel={len(missing_page)} "
            f"missing_position={len(missing_pos)} invalid_position_json={len(invalid_pos)}",
            highlight=False,
        )

        if max_problem_rows and missing_filtered:
            console.print("[yellow]Missing (filtered) examples[/yellow]")
            for t in missing_filtered[:max_problem_rows]:
                console.print(f"- {t}", highlight=False)
        if max_problem_rows and missing_sort:
            console.print("[yellow]Missing annotationSortIndex examples[/yellow]")
            for k in missing_sort[:max_problem_rows]:
                console.print(f"- annotation_key={k}", highlight=False)
        if max_problem_rows and invalid_pos:
            console.print("[yellow]Invalid annotationPosition JSON examples[/yellow]")
            for k in invalid_pos[:max_problem_rows]:
                console.print(f"- annotation_key={k}", highlight=False)
    finally:
        zotero.close()
