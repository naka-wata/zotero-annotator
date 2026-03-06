# Zotero Annotator (PyMuPDF Beta)

Zotero の PDF から段落を抽出し、翻訳付きノート注釈を自動作成する CLI です。  
この beta は **PyMuPDF 固定**で動作します（GROBID は使いません）。

## What it does

- `to-translate` タグ付き論文（または `--item-key` 指定）を処理
- PDF から段落を抽出（PyMuPDF）
- 翻訳（`deepl` のみ実装済み）
- Zotero 注釈ノートを作成し、`para:<hash>` タグで重複防止
- 完了後に対象タグを除去（通常フロー）

## Command roles

- `zotero-annotator run`: 常に翻訳ありで注釈を作成
- `zotero-annotator base`: 翻訳なしで原文注釈を作成
- `zotero-annotator translate`: 既存注釈を翻訳（新規作成なし）

タグ遷移の考え方:

- `run` は常に翻訳ありで完結するコマンドです。`base` / `translate` の段階運用とは役割が違います。
- `base` の `--write` 実行で完了判定になった item は、`to-translate` が外れて `base-done` が付きます。
- この切り替えは write 時かつ完了判定時のみで、dry-run では起きません。
- `translate` の `--write` 実行が成功した item は、`base-done` が外れて `translated` が付きます。
- この切り替えは write 時かつ成功時のみで、dry-run や失敗時には起きません。

## Requirements

- Python `3.11+`
- Zotero API: `Z_SCOPE`, `Z_ID`, `Z_API_KEY`
- 翻訳利用時: DeepL API (`DEEPL_API_KEY`)

## Setup

```bash
uv venv
UV_LINK_MODE=copy uv sync --no-editable
source .venv/bin/activate
cp .env.example .env
```

`.env` ファイルを手動で作る場合は、プロジェクト直下に `.env` を作成して次を記入してください。

```dotenv
Z_SCOPE=user
Z_ID=YOUR_ZOTERO_USER_OR_GROUP_ID
Z_API_KEY=YOUR_ZOTERO_API_KEY
TRANSLATOR_PROVIDER=deepl
TARGET_LANG=JA
DEEPL_API_KEY=YOUR_DEEPL_API_KEY
```

`.env` を編集して最低限以下を設定してください。

- `Z_SCOPE`
- `Z_ID`
- `Z_API_KEY`
- `TRANSLATOR_PROVIDER`（`deepl` 推奨）
- `TARGET_LANG`
- `DEEPL_API_KEY`（翻訳機能を使う場合）

## Quick start

```bash
zotero-annotator run --write --item-key ABCD1234
zotero-annotator base --write --item-key ABCD1234
zotero-annotator translate --write --item-key ABCD1234
```

## Translate workflow

`translate` は `base` で作成済みの注釈を後段で翻訳するためのコマンドです。

1. `base` で原文ノート注釈を作成
2. 必要なら Zotero 側で注釈内容を手修正
3. `translate` で既存注釈本文を in-place 更新

重要:

- `translate` には `--tag` がありません。対象選択を単純化し、タグ運用の分岐を減らすためです。
- `--item-key` を省略した場合は `Z_BASE_DONE_TAG`（既定: `base-done`）の item をまとめて処理します。
- **`translate` は新規注釈を作成せず、既存注釈の本文（`annotationComment` / `note`）だけを更新します。**
- 翻訳元は PyMuPDF の再抽出結果ではなく、Zotero 上の既存ノート本文（手修正済み）です。
- `base --write` が完了判定になると、`to-translate` が外れて `base-done` が付きます。
- `translate --write` が成功すると、`base-done` が外れて `translated` が付きます。

例:

```bash
zotero-annotator base --write --item-key ABCD1234
zotero-annotator translate --write --item-key ABCD1234
zotero-annotator translate --write
```

運用上のタグ遷移:

1. 開始時: `to-translate`
2. `base --write` 完了後: `base-done`
3. `translate --write` 成功後: `translated`

## Fixed beta behavior

beta の安定運用のため、以下はコード内固定値です（`.env` で変更不可）。

- `PARA_CONNECTOR_MAX_CHARS=20`
- `PARA_MATH_NEWLINES=1`
- `PARA_SKIP_ALGORITHMS=1`
- `PARA_SKIP_CAPTIONS=1`
- `PARA_STRIP_PLOT_AXIS_PREFIX=1`
- `PARA_MIN_MEDIAN_COORD_H=auto`
- `PARA_MIN_MEDIAN_COORD_H_AUTO_RATIO=0.8`
- `PARA_MERGE_SPLITS=1`
- `PARA_FORMULA_PLACEHOLDER=[MATH]`
- `RUN_MAX_PARAGRAPHS_PER_ITEM=100`
- `RUN_REPAIR_BROKEN_ANNOTATIONS=1`
- `RUN_DELETE_BROKEN_ANNOTATIONS=1`
- `ANNOTATION_MODE=note`
- `LOG_LEVEL=INFO`

## Notes

- `TRANSLATOR_PROVIDER=openai` は現時点で未実装です。
- 詳細コマンドは `CLI.md` を参照してください。
