# Zotero Annotator (PyMuPDF Beta)

Zotero の PDF から段落を抽出し、翻訳付きノート注釈を自動作成する CLI です。  
この beta は **PyMuPDF 固定**で動作します（GROBID は使いません）。

## What it does

- `to-translate` タグ付き論文（または `--item-key` 指定）を処理
- PDF から段落を抽出（PyMuPDF）
- 翻訳（`deepl` / `chatgpt`）
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
- 翻訳利用時:
  - DeepL: `DEEPL_API_KEY`
  - ChatGPT API: `OPENAI_API_KEY`, `OPENAI_MODEL`

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
- `TRANSLATOR_PROVIDER`（`deepl` または `chatgpt`。`openai` も後方互換 alias として利用可）
- `TARGET_LANG`

翻訳 provider ごとの設定:

- DeepL の必須 env: `DEEPL_API_KEY`
- DeepL の任意 env: `DEEPL_API_URL`
- ChatGPT の必須 env: `OPENAI_API_KEY`, `OPENAI_MODEL`
- ChatGPT の任意 env: `OPENAI_BASE_URL`
- 共通の任意 env: `SOURCE_LANG`（未設定時は provider 側の自動判定）

例:

```dotenv
# DeepL
TRANSLATOR_PROVIDER=deepl
DEEPL_API_KEY=YOUR_DEEPL_API_KEY

# ChatGPT API
TRANSLATOR_PROVIDER=chatgpt
OPENAI_API_KEY=YOUR_OPENAI_API_KEY
OPENAI_MODEL=gpt-4o-mini
# Optional:
# OPENAI_BASE_URL=https://api.openai.com/v1
```

翻訳 prompt は [src/zotero_annotator/services/translators/prompts.py](/Users/watarunakamura/Desktop/zotero-annotator/src/zotero_annotator/services/translators/prompts.py) で管理しています。ChatGPT 系 backend でも local LLM 系 backend でも、ここで「翻訳文だけ返す」方針を共有する前提です。

注釈タグ関連の既定値:

- `ANN_PENDING_TRANSLATION_TAG=za:translate`: base で作成した未翻訳注釈を示す annotation-level タグ
- `ANN_TRANSLATED_TAG=za:translated`: translate 済み注釈を示す annotation-level タグ

## Quick start

```bash
zotero-annotator run --write --item-key ABCD1234
zotero-annotator base --write --item-key ABCD1234
zotero-annotator translate --write --item-key ABCD1234
```

## Search behavior

`zotero-annotator search` は `Z_TARGET_TAG`（既定 `to-translate`）と `Z_BASE_DONE_TAG`（既定 `base-done`）を参照して対象 item を一覧表示します。

- 対象タグ集合のルール:
  - `--tag` 未指定: `Z_TARGET_TAG OR Z_BASE_DONE_TAG`
  - `--tag` 指定: `Z_BASE_DONE_TAG OR (--tag で指定した全て)`

例:

```bash
zotero-annotator search
zotero-annotator search --tag A
zotero-annotator search --tag A --tag B
```

## Translate workflow

`translate` は `base` で作成済みの注釈を後段で翻訳するためのコマンドです。

1. `base` で原文ノート注釈を作成
2. 必要なら Zotero 側で注釈内容を手修正
3. `translate` で既存注釈本文を in-place 更新

注釈タグの状態遷移:

1. `base --write` が新規ノート注釈を作成すると、各 annotation に `para:<hash>` と `ANN_PENDING_TRANSLATION_TAG`（既定 `za:translate`）が付きます。
2. `translate` は `ANN_PENDING_TRANSLATION_TAG` が付いた annotation だけを翻訳対象にします。`para:<hash>` は互換性・重複管理用で、対象選別には使いません。
3. `translate --write` で本文更新が成功した annotation は、同じ更新で `ANN_PENDING_TRANSLATION_TAG` を外し、`ANN_TRANSLATED_TAG`（既定 `za:translated`）を付けます。

重要:

- `translate` には `--tag` がありません。対象選択を単純化し、タグ運用の分岐を減らすためです。
- `--item-key` を省略した場合は `Z_BASE_DONE_TAG`（既定: `base-done`）の item をまとめて処理します。
- **`translate` は新規注釈を作成せず、既存注釈の本文（`annotationComment` / `note`）だけを更新します。**
- 翻訳元は PyMuPDF の再抽出結果ではなく、Zotero 上の既存ノート本文（手修正済み）です。
- `ANN_TRANSLATED_TAG` が付いた annotation は、pending が残っていても再翻訳しません。
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

単一ノートを再翻訳したい場合:

1. Zotero で対象 annotation の `ANN_TRANSLATED_TAG`（既定 `za:translated`）を外す
2. 同じ annotation に `ANN_PENDING_TRANSLATION_TAG`（既定 `za:translate`）を付け直す
3. `zotero-annotator translate --write --item-key ABCD1234` を再実行する

## Runtime parameters

`.env` で変更できる主な抽出パラメータ:

- `PARA_MIN_CHARS`, `PARA_MAX_CHARS`: 抽出する段落の文字数範囲
- `PARA_MIN_MEDIAN_COORD_H`, `PARA_MIN_MEDIAN_COORD_H_AUTO_RATIO`: 小さすぎる文字段落を除外する閾値
- `PARA_SKIP_ALGORITHMS`: アルゴリズム / 疑似コードの除外
- `PARA_SKIP_CAPTIONS`: 図表キャプションの除外
- `PARA_DROP_CITATIONS`: 文中引用番号の除去
- `PARA_DROP_FOOTNOTE_MARKERS`: 脚注マーカーの除去
- `PARA_SKIP_REFERENCES`: 参考文献セクションの除外
- `PARA_SKIP_TABLE_LIKE`: 表本文っぽい段落の除外

現時点でコード固定の主なパラメータ:

- `PARA_CONNECTOR_MAX_CHARS=20`
- `PARA_MATH_NEWLINES=1`
- `PARA_STRIP_PLOT_AXIS_PREFIX=1`
- `PARA_MERGE_SPLITS=1`
- `PARA_FORMULA_PLACEHOLDER=[MATH]`
- `RUN_MAX_PARAGRAPHS_PER_ITEM=100`
- `RUN_REPAIR_BROKEN_ANNOTATIONS=1`
- `RUN_DELETE_BROKEN_ANNOTATIONS=1`
- `LOG_LEVEL=INFO`
- `ANNOTATION_MODE=note`（通常コマンド。`dev annotate --annotation-mode` では上書き可）

## Notes

- `TRANSLATOR_PROVIDER=openai` は `chatgpt` の後方互換 alias として扱われます。
- 詳細コマンドは `CLI.md` を参照してください。
