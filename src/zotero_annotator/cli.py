from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

import httpx
import typer
from rich.console import Console

from zotero_annotator.clients.grobid import GrobidClient
from zotero_annotator.clients.zotero import ZoteroClient
from zotero_annotator.config import get_core_settings
from zotero_annotator.pipeline import run_no_translation
from zotero_annotator.services.annotation_position import build_note_position
from zotero_annotator.services.paragraphs import extract_paragraphs


app = typer.Typer(add_completion=False)
dev_app = typer.Typer(help="Development helpers / 開発用コマンド")
app.add_typer(dev_app, name="dev")
console = Console()


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
) -> None:
    
    # Validate numeric options (数値オプションのバリデーション)
    if max_items < 1:
        raise typer.BadParameter("--max-items must be >= 1")
    if tag and item_keys:
        raise typer.BadParameter("Specify either --tag or --item-key (repeatable), not both")

    # Load runtime settings for no-translation mode (.env から翻訳なし実行設定を読み込む)
    settings = get_core_settings()
    if settings.run_max_paragraphs_per_item < 1:
        raise typer.BadParameter("RUN_MAX_PARAGRAPHS_PER_ITEM must be >= 1")

    # Run no-translation pipeline (翻訳なしパイプラインを実行)
    results = run_no_translation(
        settings,
        dry_run=read_only,
        max_items=max_items,
        max_paragraphs_per_item=settings.run_max_paragraphs_per_item,
        annotation_mode="note",
        override_tag=tag,
        item_keys=item_keys,
    )

    # Print per-item summary (論文ごとの実行結果を表示)
    for r in results:
        if r.skipped_reason:
            console.print(f"[yellow]SKIP[/yellow] {r.title} ({r.skipped_reason})")
            continue
        console.print(
            f"[green]DONE[/green] {r.title} planned={r.annotations_planned} created={r.annotations_created} dup={r.paragraphs_skipped_duplicate}"
        )
        console.print(f"{r.title} の翻訳完了")



# Dev command to annotate exactly one paragraph for position testing (位置検証のため1段落だけ注釈する開発用コマンド)
@dev_app.command("annotate")
def dev_annotate(
    item_key: str = typer.Option(..., "--item-key", help="Target item key / 対象アイテムキー"),
    paragraph_index: int = typer.Option(0, "--paragraph-index", help="0-based paragraph index / 0始まり段落インデックス"),
    read_only: bool = typer.Option(
        True, "--read-only/--write", help="Do not write to Zotero / Zoteroに書き込まない"
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

        paragraphs = extract_paragraphs(
            tei_xml,
            min_chars=settings.para_min_chars,
            max_chars=settings.para_max_chars,
        )

        if not paragraphs:
            fail("No paragraphs extracted", f"item_key={item_key} pdf_key={pdf_key} paragraphs=0")

        # Validate selected paragraph index (指定段落インデックスの妥当性確認)
        if paragraph_index >= len(paragraphs):
            fail(
                "Paragraph index out of range",
                f"item_key={item_key} paragraph_index={paragraph_index} paragraphs={len(paragraphs)}",
            )
        p = paragraphs[paragraph_index]
        dedup_tag = f"{settings.dedup_tag_prefix}{p.hash}"

        # Check duplication by para:<hash> tag (para:<hash> で重複判定)
        try:
            existing = zotero.list_annotations(parent_key=pdf_key)
        except httpx.HTTPError as exc:
            fail("Zotero connection failed", f"annotations fetch failed pdf_key={pdf_key} detail={exc}")

        existing_tags = set()
        for ann in existing:
            for t in zotero.extract_tag_names(ann):
                existing_tags.add(t)
        if dedup_tag in existing_tags:
            console.print(f"[yellow]SKIP[/yellow] duplicate paragraph tag found: {dedup_tag}")
            console.print(
                f"[bold white]item_key[/bold white]=[cyan]{item_key}[/cyan] "
                f"[bold white]pdf_key[/bold white]=[cyan]{pdf_key}[/cyan] "
                f"[bold white]paragraph_index[/bold white]=[green]{paragraph_index}[/green] "
                f"[bold white]page[/bold white]=[green]{p.page}[/green] "
                f"[bold white]hash[/bold white]=[magenta]{p.hash}[/magenta]",
                highlight=False,
            )
            return

        # Build note annotation position (note用の位置情報を生成: 左の小矩形12x12)
        note_pos = build_note_position(p)

        payload = {
            "itemType": "annotation",
            "parentItem": pdf_key,
            "annotationType": "note",
            "annotationComment": p.text,
            "annotationPosition": json.dumps(note_pos.annotation_position),
            "annotationPageLabel": str(note_pos.page_index + 1),
            "annotationSortIndex": note_pos.annotation_sort_index,
            "tags": [{"tag": dedup_tag}, {"tag": "grobid-auto"}],
        }

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
            f"[bold white]tag[/bold white]=[yellow]{dedup_tag}[/yellow]",
            highlight=False,
        )
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
        children = zotero.list_children(item_key)
        pdf = zotero.pick_pdf_attachment(children)
        if not pdf:
            raise typer.BadParameter("No PDF attachment found for --item-key")

        # Download PDF and request TEI from GROBID (PDFをダウンロードしてGROBIDでTEI化)
        pdf_key = pdf.get("key") or ""
        pdf_bytes = zotero.download_attachment(zotero.build_file_url(pdf_key))
        tei_xml = grobid.process_fulltext(pdf_bytes, tei_coordinates="p")

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
) -> None:
    # Validate inputs (入力オプションのバリデーション)
    if max_rows < 1:
        raise typer.BadParameter("--max-rows must be >= 1")
    if bool(item_key) == bool(tei):
        raise typer.BadParameter("Specify exactly one of --item-key or --tei")

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
            children = zotero.list_children(item_key or "")
            pdf = zotero.pick_pdf_attachment(children)
            if not pdf:
                raise typer.BadParameter("No PDF attachment found for --item-key")
            pdf_key = pdf.get("key") or ""
            pdf_bytes = zotero.download_attachment(zotero.build_file_url(pdf_key))
            tei_xml = grobid.process_fulltext(pdf_bytes, tei_coordinates="p")
        finally:
            grobid.close()
            zotero.close()

    # Extract and summarize paragraphs (段落抽出とサマリ表示)
    rows = extract_paragraphs(
        tei_xml,
        min_chars=settings.para_min_chars,
        max_chars=settings.para_max_chars,
    )
    console.print(f"[cyan]paragraphs={len(rows)}[/cyan]")

    # Build preview payload (プレビュー用ペイロードを生成)
    preview = rows[:max_rows]
    payload = [
        {
            "index": i,
            "hash": p.hash,
            "page": p.page,
            "text": p.text,
            "coords": [c.__dict__ for c in p.coords],
        }
        for i, p in enumerate(preview)
    ]

    # Output JSON to file or console (JSONをファイル出力またはコンソール表示)
    if out:
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        console.print(f"[green]Wrote[/green] {out}")
    else:
        console.print_json(json.dumps(payload, ensure_ascii=False))
