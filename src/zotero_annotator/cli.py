from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from zotero_annotator.clients.grobid import GrobidClient
from zotero_annotator.clients.zotero import ZoteroClient
from zotero_annotator.config import get_settings
from zotero_annotator.pipeline import AnnotationMode, run_no_translation
from zotero_annotator.services.paragraphs import extract_paragraphs


app = typer.Typer(add_completion=False)
dev_app = typer.Typer(help="Development helpers / 開発用コマンド")
app.add_typer(dev_app, name="dev")
console = Console()


# Search command to count items with a target tag (対象タグ付きアイテムの件数を数えるコマンド)
@app.command()
def search(
    tag: Optional[str] = typer.Option(None, "--tag", help="Target tag override / 対象タグを上書き"),
    limit_per_page: int = typer.Option(100, "--limit-per-page", help="Page size for listing / 1ページの取得件数"),
) -> None:
    """Count items tagged in Zotero (タグ付き論文の件数を数える)."""
    settings = get_settings()
    target_tag = tag or settings.z_target_tag

    zotero = ZoteroClient(
        base_url=settings.zotero_base_url,
        api_key=settings.z_api_key,
        scope=settings.z_scope,
        library_id=settings.z_id,
    )
    try:
        count = 0
        for _ in zotero.iter_items_by_tag(tag=target_tag, limit_per_page=limit_per_page):
            count += 1
        console.print(f"{target_tag}: {count} items")
    finally:
        zotero.close()


# Main run command for the annotation pipeline (アノテーション処理パイプラインの実行コマンド)
@app.command()
def run(
    tag: Optional[str] = typer.Option(None, "--tag", help="Target tag override / 対象タグを上書き"),
    max_items: int = typer.Option(10, "--max-items", help="Max papers per run / 1回の最大論文数"),
    read_only: bool = typer.Option(
        True, "--read-only/--write", help="Do not write to Zotero / Zoteroに書き込まない"
    ),
    no_translate: bool = typer.Option(
        False, "--no-translate", help="Disable translation (dev) / 翻訳なしで実行（開発用）"
    ),
    max_paragraphs_per_item: int = typer.Option(
        3, "--max-paragraphs-per-item", help="Max paragraphs per paper / 1論文あたりの最大段落数"
    ),
    annotation_mode: AnnotationMode = typer.Option(
        "note",
        "--annotation-mode",
        help="Annotation mode / 注釈モード",
    ),
) -> None:
    
    # Validate numeric options (数値オプションのバリデーション)
    if max_items < 1:
        raise typer.BadParameter("--max-items must be >= 1")
    if max_paragraphs_per_item < 1:
        raise typer.BadParameter("--max-paragraphs-per-item must be >= 1")

    # Load runtime settings from .env (.env から実行設定を読み込む)
    settings = get_settings()

    # Translation mode is not implemented yet (翻訳モードは未実装)
    if not no_translate:
        console.print("[yellow]Translation pipeline is not implemented yet.[/yellow] Use --no-translate for now.")
        raise typer.Exit(code=2)

    # Run no-translation pipeline (翻訳なしパイプラインを実行)
    results = run_no_translation(
        settings,
        dry_run=read_only,
        max_items=max_items,
        max_paragraphs_per_item=max_paragraphs_per_item,
        annotation_mode=annotation_mode,
        override_tag=tag,
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

    # Temporary scaffold output (暫定スキャフォールド出力)
    console.print(
        "[yellow]dev annotate is scaffolded but not fully implemented yet.[/yellow]\n"
        f"item_key={item_key} paragraph_index={paragraph_index} mode={'read-only' if read_only else 'write'}"
    )


# Dev command to list target papers quickly (対象論文を確認する開発用コマンド)
@dev_app.command("items")
def dev_items(
    tag: Optional[str] = typer.Option(None, "--tag", help="Target tag override / 対象タグを上書き"),
    max_items: int = typer.Option(20, "--max-items", help="Max items to display / 表示する最大件数"),
) -> None:
    # Validate numeric options (数値オプションのバリデーション)
    if max_items < 1:
        raise typer.BadParameter("--max-items must be >= 1")

    # Load settings and build client (設定読み込みとクライアント作成)
    settings = get_settings()
    target_tag = tag or settings.z_target_tag
    zotero = ZoteroClient(
        base_url=settings.zotero_base_url,
        api_key=settings.z_api_key,
        scope=settings.z_scope,
        library_id=settings.z_id,
    )
    try:
        # Iterate and print items (対象アイテムを走査して表示)
        count = 0
        for item in zotero.iter_items_by_tag(tag=target_tag, limit_per_page=100):
            count += 1
            if count > max_items:
                break
            key = item.get("key") or ""
            title = (item.get("data") or {}).get("title") or ""
            console.print(f"{count:>2}. {key}  {title}")
        console.print(f"[cyan]tag={target_tag} displayed={min(count, max_items)}[/cyan]")
    finally:
        # Ensure client is closed (クライアントを確実にクローズ)
        zotero.close()


# Dev command to fetch TEI via GROBID (GROBIDでTEIを取得する開発用コマンド)
@dev_app.command("grobid")
def dev_grobid(
    item_key: str = typer.Option(..., "--item-key", help="Target item key / 対象アイテムキー"),
    out: Optional[Path] = typer.Option(None, "--out", help="Output TEI path / TEI出力先"),
) -> None:
    # Load settings and create clients (設定読み込みとクライアント作成)
    settings = get_settings()
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
    settings = get_settings()
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
