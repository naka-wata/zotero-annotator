# Zotero Annotator (PyMuPDF Beta)

Zotero の PDF から段落を抽出し、翻訳付きノート注釈を自動作成する CLI です。  
この beta は **PyMuPDF 固定**で動作します（GROBID は使いません）。

## What it does

- `to-translate` タグ付き論文（または `--item-key` 指定）を処理
- PDF から段落を抽出（PyMuPDF）
- 翻訳（`deepl` / `chatgpt` / `local_llm`）
- Zotero 注釈ノートを作成し、`para:<hash>` タグで重複防止

## Command roles

- `zotero-annotator base`: 翻訳なしで原文注釈を作成
- `zotero-annotator translate`: 既存注釈を翻訳（新規作成なし）
- `zotero-annotator run`: 常に翻訳ありで注釈を作成

通常運用の推奨ルートは `base -> translate` です。`run` は手修正を挟まず一気に処理したいときの短縮ルートとして使います。

## Requirements

- Python `3.11+`
- `uv`
- Zotero API の認証情報
- 利用する翻訳 provider の認証情報、または起動済みの local LLM

## Setup

初回セットアップは [docs/setup.md](docs/setup.md) を参照してください。`.env` の各項目は [docs/configuration.md](docs/configuration.md) にまとめており、キー名と例示値・既定値は [.env.example](.env.example) を正本として扱います。

```bash
uv venv
UV_LINK_MODE=copy uv sync --no-editable
source .venv/bin/activate
cp .env.example .env
```

`.env` はリポジトリ直下に置き、[docs/configuration.md](docs/configuration.md) を見ながら編集してください。`TRANSLATOR_PROVIDER=local_llm` を使う場合の server 起動手順は [docs/local-llm.md](docs/local-llm.md) を参照してください。

## Quick start

```bash
zotero-annotator base --write --item-key ABCD1234
zotero-annotator translate --write --item-key ABCD1234
zotero-annotator run --write --item-key ABCD1234
```

## Docs

- 通常利用者向け CLI リファレンス: [docs/cli.md](docs/cli.md)
- 通常運用フローとタグ遷移: [docs/workflows.md](docs/workflows.md)
- `dev` コマンドと開発向け情報: [docs/development.md](docs/development.md)
- `.env` 設定: [docs/configuration.md](docs/configuration.md)
- 初回セットアップ: [docs/setup.md](docs/setup.md)
- Local LLM の起動手順: [docs/local-llm.md](docs/local-llm.md)

## Notes

- `TRANSLATOR_PROVIDER=openai` は `chatgpt` の後方互換 alias として扱われます。
- 詳しい運用手順は [docs/workflows.md](docs/workflows.md) を参照してください。
