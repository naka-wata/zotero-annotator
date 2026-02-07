# Zotero Annotator (Gemini + GROBID) ✨

Automatically analyzes academic PDFs in Zotero and adds translated paragraph annotations as note annotations.  
Zotero内の学術PDFを自動解析し、段落翻訳を「注釈ノート」として追加します。

## Overview / 概要

- Detect items tagged with `to-translate` in Zotero.  
  Zotero内の `to-translate` タグ付き論文を検出します。
- Extract paragraph text from PDFs using GROBID.  
  GROBIDでPDFから段落テキストを抽出します。
- Translate each paragraph with Gemini.  
  Geminiで段落ごとに翻訳します。
- Create note annotations with `para:<hash>` tags to prevent duplicates.  
  重複防止のため `para:<hash>` タグ付き注釈ノートを作成します。
- Remove the target tag once all paragraphs are processed.  
  全段落の処理後、対象タグを削除します。

## Requirements / 必要環境

- Python 3.11+
- Zotero API key
- GROBID server (Docker recommended)
- Gemini API key
- Python 3.11+
- Zotero APIキー
- GROBIDサーバー（Docker推奨）
- Gemini APIキー

## Setup / セットアップ

1. Create and populate `.env` (see `.env.example`).  
   `.env` を作成し、設定を記入します（`.env.example` を参照）。
2. Install (uv):  
   uvでインストールします。

```bash
uv venv .venv
source .venv/bin/activate
uv pip install -e .
```

3. Start GROBID (Docker):  
   GROBIDを起動します（Docker）。

```bash
docker compose up -d grobid
```

## Environment Variables / 環境変数

Key configuration lives in `.env`. The defaults in `.env.example` cover:  
設定は `.env` にまとめます。`.env.example` のデフォルトは以下を含みます。

- Zotero: `Z_SCOPE`, `Z_ID`, `Z_API_KEY`
- Tags: `Z_TARGET_TAG`, `Z_DONE_TAG`, `Z_REMOVE_TAG`, `Z_IN_PROGRESS_TAG`
- GROBID: `GROBID_URL`, `GROBID_TIMEOUT_SECONDS`
- Gemini: `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_CONCURRENCY`, `GEMINI_TIMEOUT_SECONDS`
- Pipeline: `DEDUP_TAG_PREFIX`, `PARA_MIN_CHARS`, `PARA_MAX_CHARS`, `TARGET_LANG`
- Logging: `LOG_LEVEL`

## Usage / 使い方

Preview without writing annotations:  
注釈を作成せずに確認する場合:

```bash
zotero-annotator run --read-only
```

Process a small batch:  
少数だけ実行する場合:

```bash
zotero-annotator run --max-items 5
```

## Output Behavior / 出力

- Each paragraph becomes a note annotation on the PDF.  
  各段落はPDF内の注釈ノートになります。
- Each annotation is tagged with `para:<hash>` for deduplication.  
  注釈には `para:<hash>` が付与され、重複を防ぎます。
- When all paragraphs are finished, the target tag is removed.  
  全段落完了後、対象タグを削除します。
- The CLI prints `"{title} の翻訳完了"` per paper.  
  各論文ごとに `"{title} の翻訳完了"` を表示します。

## Project Structure / 構成

```
zotero-annotator/
├── pyproject.toml
├── src/
│   └── zotero_annotator/
├── docker-compose.yml
├── .env.example
└── README.md
```

## Security / セキュリティ

- Do not commit `.env`.  
  `.env` はコミットしないでください。
- Revoke and regenerate API keys if exposed.  
  APIキーが漏洩した場合は再発行してください。
