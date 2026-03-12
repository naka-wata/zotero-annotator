# Zotero Annotator (PyMuPDF Beta)

Zotero の PDF から段落を抽出し、翻訳付きノート注釈を自動作成する CLI です。  
この beta は **PyMuPDF 固定**で動作します（GROBID は使いません）。

## What it does

- `to-translate` タグ付き論文（または `--item-key` 指定）を処理
- PDF から段落を抽出（PyMuPDF）
- 翻訳（`deepl` / `chatgpt` / `local_llm`）
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

## Notes

- `TRANSLATOR_PROVIDER=openai` は `chatgpt` の後方互換 alias として扱われます。
- 翻訳 prompt は [src/zotero_annotator/services/translators/prompts.py](src/zotero_annotator/services/translators/prompts.py) で管理しています。
- `.env` の詳細は [docs/configuration.md](docs/configuration.md) を参照してください。
- 代表コマンドと使い分けは [docs/cli.md](docs/cli.md) を参照してください。
