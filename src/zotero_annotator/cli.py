from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import List, Optional

import httpx
import typer
from pydantic import ValidationError
from rich.console import Console

from zotero_annotator.clients.grobid import GrobidClient
from zotero_annotator.clients.zotero import ZoteroClient
from zotero_annotator.config import get_core_settings, get_translation_settings
from zotero_annotator.pipeline import build_annotation_payload, run_no_translation
from zotero_annotator.services.annotation_position import build_note_position
from zotero_annotator.services.paragraphs import estimate_coord_h_threshold, extract_paragraphs
from zotero_annotator.services.translators.factory import build_translator
from zotero_annotator.services.translators.base import TranslationError


app = typer.Typer(add_completion=False)
dev_app = typer.Typer(help="Development helpers / 開発用コマンド")
app.add_typer(dev_app, name="dev")
console = Console()

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


# Search command to list target papers quickly (対象論文を確認する検索コマンド)
@app.command()
def search(
    tag: Optional[str] = typer.Option(None, "--tag", help="Target tag override / 対象タグを上書き"),
    max_items: int = typer.Option(20, "--max-items", help="Max items to display / 表示する最大件数"),
) -> None:
    """List items tagged in Zotero (タグ付き論文の一覧を表示する)."""
    if max_items < 1:
        raise typer.BadParameter("--max-items must be >= 1")

    settings = get_core_settings()
    target_tag = tag or settings.z_target_tag

    zotero = ZoteroClient(
        base_url=settings.zotero_base_url,
        api_key=settings.z_api_key,
        scope=settings.z_scope,
        library_id=settings.z_id,
    )
    try:
        count = 0
        for item in zotero.iter_items_by_tag(tag=target_tag, limit_per_page=100):
            count += 1
            if count > max_items:
                break
            key = item.get("key") or ""
            title = (item.get("data") or {}).get("title") or ""
            tags = zotero.extract_tag_names(item)
            tags_text = ", ".join(tags) if tags else "-"
            console.print(
                f"{count:>2}. [bold cyan]item-key[/bold cyan] : [cyan]{key}[/cyan]  "
                f"[bold green]title[/bold green] : [green]{title}[/green]  "
                f"[bold yellow]tags[/bold yellow] : [yellow]{tags_text}[/yellow]"
            )
        console.print(f"[cyan]tag={target_tag} displayed={min(count, max_items)}[/cyan]")
    finally:
        zotero.close()


# Main run command for the annotation pipeline (アノテーション処理パイプラインの実行コマンド)
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
        True, "--read-only/--write", help="Do not write to Zotero / Zoteroに書き込まない"
    ),
    translate: bool = typer.Option(
        True,
        "--translate/--no-translate",
        help="Translate before annotating / 注釈前に翻訳する",
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
    # Validate numeric options (数値オプションのバリデーション)
    if max_items < 1:
        raise typer.BadParameter("--max-items must be >= 1")
    if tag and item_keys:
        raise typer.BadParameter("Specify either --tag or --item-key (repeatable), not both")
    if delete_broken and keep_broken:
        raise typer.BadParameter("Specify at most one of --delete-broken or --keep-broken")

    def fail(stage: str, detail: str) -> None:
        console.print(f"[red]ERROR[/red] {stage}: {detail}")
        raise typer.Exit(code=1)

    # Load runtime settings (.env から設定を読み込む)
    try:
        settings = get_core_settings()
        if settings.run_max_paragraphs_per_item < 1:
            raise typer.BadParameter("RUN_MAX_PARAGRAPHS_PER_ITEM must be >= 1")
        tsettings = get_translation_settings() if translate else None
        translator = build_translator() if translate else None
    except ValidationError as exc:
        fail("Invalid .env / environment variables", str(exc))
        return
    except RuntimeError as exc:
        fail("Translator provider error", str(exc))
        return

    source_lang = ((tsettings.source_lang or "").strip() if tsettings else "")
    target_lang = (tsettings.target_lang if tsettings else "")
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



# Dev command to annotate exactly one paragraph for position testing (位置検証のため1段落だけ注釈する開発用コマンド)
@dev_app.command("annotate")
def dev_annotate(
    item_key: str = typer.Option(..., "--item-key", help="Target item key / 対象アイテムキー"),
    paragraph_index: int = typer.Option(0, "--paragraph-index", help="0-based paragraph index / 0始まり段落インデックス"),
    read_only: bool = typer.Option(
        True, "--read-only/--write", help="Do not write to Zotero / Zoteroに書き込まない"
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
    grobid = GrobidClient(
        base_url=settings.grobid_url,
        timeout_seconds=settings.grobid_timeout_seconds,
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

        # Download PDF and extract paragraphs via GROBID (PDF取得→GROBIDで段落抽出)
        try:
            pdf_bytes = zotero.download_attachment(zotero.build_file_url(pdf_key))
        except httpx.HTTPError as exc:
            fail("Zotero connection failed", f"pdf download failed pdf_key={pdf_key} detail={exc}")

        try:
            tei_xml = grobid.process_fulltext(pdf_bytes, tei_coordinates="p")
        except httpx.HTTPError as exc:
            fail("GROBID failed", f"pdf_key={pdf_key} detail={exc}")

        try:
            paragraphs = extract_paragraphs(
                tei_xml,
                # Repair should be as inclusive as possible to match legacy tags.
                # (修復は取りこぼしを減らすため最小文字数を0にする)
                min_chars=0,
                max_chars=max(settings.para_max_chars, 20000),
                merge_splits=settings.para_merge_splits,
                formula_placeholder=settings.para_formula_placeholder,
                min_median_coord_h=settings.para_min_median_coord_h,
                min_median_coord_h_auto_ratio=settings.para_min_median_coord_h_auto_ratio,
                connector_max_chars=settings.para_connector_max_chars,
                math_newlines=settings.para_math_newlines,
                skip_algorithms=settings.para_skip_algorithms,
                strip_plot_axis_prefix=settings.para_strip_plot_axis_prefix,
                skip_captions=settings.para_skip_captions,
            )
        except ValueError as exc:
            fail("TEI parse failed", str(exc))

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
            tsettings = get_translation_settings()
            translator = build_translator()
            source_lang = (tsettings.source_lang or "").strip()
            target_lang = tsettings.target_lang
            try:
                comment_text = translator.translate(source_text, source_lang=source_lang, target_lang=target_lang).text
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
        grobid.close()
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
    tsettings = get_translation_settings()
    translator = build_translator()
    source_lang = (tsettings.source_lang or "").strip()
    target_lang = tsettings.target_lang

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

        # Download PDF and extract paragraphs via GROBID (PDF取得→GROBIDで段落抽出)
        try:
            pdf_bytes = zotero.download_attachment(zotero.build_file_url(pdf_key))
        except httpx.HTTPError as exc:
            fail("Zotero connection failed", f"pdf download failed pdf_key={pdf_key} detail={exc}")

        try:
            tei_xml = grobid.process_fulltext(pdf_bytes, tei_coordinates="p")
        except httpx.HTTPError as exc:
            fail("GROBID failed", f"pdf_key={pdf_key} detail={exc}")

        try:
            paragraphs = extract_paragraphs(
                tei_xml,
                min_chars=settings.para_min_chars,
                max_chars=settings.para_max_chars,
                merge_splits=settings.para_merge_splits,
                formula_placeholder=settings.para_formula_placeholder,
                min_median_coord_h=settings.para_min_median_coord_h,
                min_median_coord_h_auto_ratio=settings.para_min_median_coord_h_auto_ratio,
                connector_max_chars=settings.para_connector_max_chars,
                math_newlines=settings.para_math_newlines,
                skip_algorithms=settings.para_skip_algorithms,
                strip_plot_axis_prefix=settings.para_strip_plot_axis_prefix,
                skip_captions=settings.para_skip_captions,
            )
        except ValueError as exc:
            fail("TEI parse failed", str(exc))
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
            result = translator.translate(p.text, source_lang=source_lang, target_lang=target_lang)
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
        grobid.close()
        zotero.close()

# Dev command to fetch TEI via GROBID (GROBIDでTEIを取得する開発用コマンド)
@dev_app.command("grobid")
def dev_grobid(
    item_key: str = typer.Option(..., "--item-key", help="Target item key / 対象アイテムキー"),
    out: Optional[Path] = typer.Option(None, "--out", help="Output TEI path / TEI出力先"),
) -> None:
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
    grobid = GrobidClient(
        base_url=settings.grobid_url,
        timeout_seconds=settings.grobid_timeout_seconds,
    )
    try:
        # Resolve PDF attachment from target item (対象アイテムのPDF添付を解決)
        try:
            children = zotero.list_children(item_key)
        except httpx.HTTPError as exc:
            fail("Zotero connection failed", f"children fetch failed item_key={item_key} detail={exc}")
        pdf = zotero.pick_pdf_attachment(children)
        if not pdf:
            raise typer.BadParameter("No PDF attachment found for --item-key")

        # Download PDF and request TEI from GROBID (PDFをダウンロードしてGROBIDでTEI化)
        pdf_key = pdf.get("key") or ""
        try:
            pdf_bytes = zotero.download_attachment(zotero.build_file_url(pdf_key))
        except httpx.HTTPError as exc:
            fail("Zotero connection failed", f"pdf download failed pdf_key={pdf_key} detail={exc}")

        try:
            tei_xml = grobid.process_fulltext(pdf_bytes, tei_coordinates="p")
        except httpx.HTTPError as exc:
            fail("GROBID failed", f"pdf_key={pdf_key} detail={exc}")

        # Output TEI to file or console preview (TEIをファイル出力またはプレビュー表示)
        if out:
            out.write_text(tei_xml, encoding="utf-8")
            console.print(f"[green]Wrote[/green] {out}")
        else:
            preview = tei_xml[:1200]
            console.print(preview)
            if len(tei_xml) > len(preview):
                console.print("[cyan]...(truncated)[/cyan]")
    finally:
        # Ensure clients are closed (クライアントを確実にクローズ)
        grobid.close()
        zotero.close()


# Dev command to inspect extracted paragraphs (段落抽出結果を確認する開発用コマンド)
@dev_app.command("paragraphs")
def dev_paragraphs(
    item_key: Optional[str] = typer.Option(None, "--item-key", help="Target item key / 対象アイテムキー"),
    tei: Optional[Path] = typer.Option(None, "--tei", help="Input TEI file path / TEI入力ファイル"),
    out: Optional[Path] = typer.Option(None, "--out", help="Output JSON path / JSON出力先"),
    max_rows: int = typer.Option(20, "--max-rows", help="Max rows to print / 表示する最大件数"),
    debug_coord_h: bool = typer.Option(
        False, "--debug-coord-h", help="Show coord-h threshold and per-paragraph median(h)"
    ),
) -> None:
    # Validate inputs (入力オプションのバリデーション)
    if max_rows < 1:
        raise typer.BadParameter("--max-rows must be >= 1")
    if bool(item_key) == bool(tei):
        raise typer.BadParameter("Specify exactly one of --item-key or --tei")

    def fail(stage: str, detail: str) -> None:
        console.print(f"[red]ERROR[/red] {stage}: {detail}")
        raise typer.Exit(code=1)

    # Load settings (設定を読み込む)
    settings = get_core_settings()
    tei_xml: str

    # Load TEI from file or fetch from Zotero+GROBID (TEIをファイル入力またはZotero+GROBIDから取得)
    if tei:
        tei_xml = tei.read_text(encoding="utf-8")
    else:
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
        try:
            try:
                children = zotero.list_children(item_key or "")
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
                tei_xml = grobid.process_fulltext(pdf_bytes, tei_coordinates="p")
            except httpx.HTTPError as exc:
                fail("GROBID failed", f"pdf_key={pdf_key} detail={exc}")
        finally:
            grobid.close()
            zotero.close()

    # Extract and summarize paragraphs (段落抽出とサマリ表示)
    try:
        if debug_coord_h:
            coord_h = estimate_coord_h_threshold(
                tei_xml,
                min_chars=settings.para_min_chars,
                formula_placeholder=settings.para_formula_placeholder,
                min_median_coord_h=settings.para_min_median_coord_h,
                min_median_coord_h_auto_ratio=settings.para_min_median_coord_h_auto_ratio,
            )
            console.print(
                f"[cyan]coord_h_threshold={coord_h.threshold:.3f}[/cyan] method={coord_h.method} samples={coord_h.samples} q75={coord_h.q75} ratio={coord_h.ratio}",
                highlight=False,
            )

            rows_all = extract_paragraphs(
                tei_xml,
                min_chars=settings.para_min_chars,
                max_chars=settings.para_max_chars,
                merge_splits=settings.para_merge_splits,
                formula_placeholder=settings.para_formula_placeholder,
                min_median_coord_h=0.0,
                min_median_coord_h_auto_ratio=settings.para_min_median_coord_h_auto_ratio,
                connector_max_chars=settings.para_connector_max_chars,
                math_newlines=settings.para_math_newlines,
                skip_algorithms=settings.para_skip_algorithms,
                strip_plot_axis_prefix=settings.para_strip_plot_axis_prefix,
                skip_captions=settings.para_skip_captions,
            )
        else:
            rows_all = []

        rows = extract_paragraphs(
            tei_xml,
            min_chars=settings.para_min_chars,
            max_chars=settings.para_max_chars,
            merge_splits=settings.para_merge_splits,
            formula_placeholder=settings.para_formula_placeholder,
            min_median_coord_h=settings.para_min_median_coord_h,
            min_median_coord_h_auto_ratio=settings.para_min_median_coord_h_auto_ratio,
            connector_max_chars=settings.para_connector_max_chars,
            math_newlines=settings.para_math_newlines,
            skip_algorithms=settings.para_skip_algorithms,
            strip_plot_axis_prefix=settings.para_strip_plot_axis_prefix,
            skip_captions=settings.para_skip_captions,
        )
    except ValueError as exc:
        fail("TEI parse failed", str(exc))

    if debug_coord_h:
        console.print(
            f"[cyan]paragraphs={len(rows)}[/cyan] (unfiltered={len(rows_all)} removed_by_coord_h={max(0, len(rows_all)-len(rows))})",
            highlight=False,
        )
    else:
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
        if debug_coord_h and p.coords:
            hs = [c.h for c in p.coords]
            row["median_coord_h"] = float(statistics.median(hs)) if hs else None
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
        True, "--read-only/--write", help="Do not write to Zotero / Zoteroに書き込まない"
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
    grobid = GrobidClient(
        base_url=settings.grobid_url,
        timeout_seconds=settings.grobid_timeout_seconds,
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

        try:
            tei_xml = grobid.process_fulltext(pdf_bytes, tei_coordinates="p")
        except httpx.HTTPError as exc:
            fail("GROBID failed", f"pdf_key={pdf_key} detail={exc}")

        try:
            paragraphs = extract_paragraphs(
                tei_xml,
                min_chars=settings.para_min_chars,
                max_chars=settings.para_max_chars,
                merge_splits=settings.para_merge_splits,
                formula_placeholder=settings.para_formula_placeholder,
                min_median_coord_h=settings.para_min_median_coord_h,
                min_median_coord_h_auto_ratio=settings.para_min_median_coord_h_auto_ratio,
                connector_max_chars=settings.para_connector_max_chars,
                math_newlines=settings.para_math_newlines,
                skip_algorithms=settings.para_skip_algorithms,
                strip_plot_axis_prefix=settings.para_strip_plot_axis_prefix,
                skip_captions=settings.para_skip_captions,
            )
        except ValueError as exc:
            fail("TEI parse failed", str(exc))

        # Map para:<hash> -> computed position fields
        pos_by_tag = {}
        for p in paragraphs:
            note_pos = build_note_position(p)
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
        grobid.close()
        zotero.close()


@dev_app.command("delete-broken-annotations")
def dev_delete_broken_annotations(
    item_key: str = typer.Option(..., "--item-key", help="Target item key / 対象アイテムキー"),
    read_only: bool = typer.Option(
        True, "--read-only/--write", help="Do not write to Zotero / Zoteroに書き込まない"
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
    grobid = GrobidClient(
        base_url=settings.grobid_url,
        timeout_seconds=settings.grobid_timeout_seconds,
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

        try:
            tei_xml = grobid.process_fulltext(pdf_bytes, tei_coordinates="p")
        except httpx.HTTPError as exc:
            fail("GROBID failed", f"pdf_key={pdf_key} detail={exc}")

        try:
            paras_filtered = extract_paragraphs(
                tei_xml,
                min_chars=settings.para_min_chars,
                max_chars=settings.para_max_chars,
                merge_splits=settings.para_merge_splits,
                formula_placeholder=settings.para_formula_placeholder,
                min_median_coord_h=settings.para_min_median_coord_h,
                min_median_coord_h_auto_ratio=settings.para_min_median_coord_h_auto_ratio,
                connector_max_chars=settings.para_connector_max_chars,
                math_newlines=settings.para_math_newlines,
                skip_algorithms=settings.para_skip_algorithms,
                strip_plot_axis_prefix=settings.para_strip_plot_axis_prefix,
                skip_captions=settings.para_skip_captions,
            )
            paras_all = extract_paragraphs(
                tei_xml,
                min_chars=0,
                max_chars=max(settings.para_max_chars, 20000),
                merge_splits=settings.para_merge_splits,
                formula_placeholder=settings.para_formula_placeholder,
                min_median_coord_h=settings.para_min_median_coord_h,
                min_median_coord_h_auto_ratio=settings.para_min_median_coord_h_auto_ratio,
                connector_max_chars=settings.para_connector_max_chars,
                math_newlines=settings.para_math_newlines,
                skip_algorithms=settings.para_skip_algorithms,
                strip_plot_axis_prefix=settings.para_strip_plot_axis_prefix,
            )
        except ValueError as exc:
            fail("TEI parse failed", str(exc))

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
        grobid.close()
        zotero.close()
