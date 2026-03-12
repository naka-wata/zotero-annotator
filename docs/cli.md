# CLI Specification (PyMuPDF Beta)

このドキュメントは現在の `zotero-annotator` CLI 実装に合わせた使い方メモです。  
beta 版は **PyMuPDF 固定**で動作し、GROBID コマンドはありません。

通常運用の流れとタグ遷移は [workflows.md](workflows.md) を参照してください。通常運用の推奨ルートは `base -> translate` です。`dev` コマンドと開発向け補助情報は [development.md](development.md) にまとめています。

## 実行前提

```bash
uv venv
UV_LINK_MODE=copy uv sync --no-editable
source .venv/bin/activate
```

## 翻訳 provider 設定

`.env` で `TRANSLATOR_PROVIDER` を切り替えます。

- `TRANSLATOR_PROVIDER=deepl`: DeepL を使用
- `TRANSLATOR_PROVIDER=chatgpt`: OpenAI ChatGPT API を使用
- `TRANSLATOR_PROVIDER=local_llm`: Ollama など OpenAI 互換 local LLM を使用
- `TRANSLATOR_PROVIDER=openai`: `chatgpt` の後方互換 alias

必須 env:

- 共通: `TARGET_LANG`
- DeepL: `DEEPL_API_KEY`
- ChatGPT: `OPENAI_API_KEY`, `OPENAI_MODEL`
- Local LLM: `LOCAL_LLM_BASE_URL`, `LOCAL_LLM_MODEL`

任意 env:

- 共通: `SOURCE_LANG`
- DeepL: `DEEPL_API_URL`
- ChatGPT: `OPENAI_BASE_URL`
- Local LLM: `LOCAL_LLM_API_KEY`, `LOCAL_LLM_TEMPERATURE`, `LOCAL_LLM_TOP_P`

Local LLM の詳細セットアップは [local-llm.md](local-llm.md) を参照してください。

## コマンド一覧

- `zotero-annotator search`: 対象 item を確認する
- `zotero-annotator base`: 翻訳なしで原文注釈を作成する
- `zotero-annotator translate`: 既存注釈だけを翻訳更新する
- `zotero-annotator run`: 抽出から翻訳付き注釈作成まで一気に実行する

## `zotero-annotator search`

タグで Zotero item を一覧表示します。読み取り専用です。

- `search` は `Z_TARGET_TAG`（既定 `to-translate`）と `Z_BASE_DONE_TAG`（既定 `base-done`）を参照します。
- `--tag` 未指定: `Z_TARGET_TAG OR Z_BASE_DONE_TAG`
- `--tag` 指定: `Z_BASE_DONE_TAG OR (--tag で指定した全て)`
- `--max-items INTEGER`: 表示上限（既定 `20`）

代表コマンド:

```bash
zotero-annotator search
zotero-annotator search --tag A --tag B
zotero-annotator search --tag to-translate --max-items 5
```

## `zotero-annotator run`

抽出から翻訳付き注釈作成までを一度に実行する一括実行コマンドです。

- `--tag TEXT`: タグ指定実行
- `--item-key TEXT`（複数可）: item 指定実行
- `--max-items INTEGER`: 処理件数上限（既定 `10`）
- `--read-only/--write`: 書き込み有無（既定 `--write`）
- `--delete-broken`: 実行前に壊れ注釈を削除
- `--keep-broken`: 壊れ注釈削除を抑止

注意:

- `--tag` と `--item-key` は同時指定できません。
- 壊れ注釈は `annotationSortIndex` / `annotationPageLabel` / `annotationPosition` の欠落注釈を指します。
- 通常運用では `base -> translate` を推奨します。`run` は手修正を挟まない一括実行向けです。
- 運用フローの使い分けは [workflows.md](workflows.md) を参照してください。

代表コマンド:

```bash
zotero-annotator run --write --item-key ABCD1234
zotero-annotator run --tag to-translate --max-items 5
```

## `zotero-annotator base`

翻訳なしで原文注釈を作成します。

- `--tag TEXT`: タグ指定実行
- `--item-key TEXT`（複数可）: item 指定実行
- `--max-items INTEGER`: 処理件数上限（既定 `10`）
- `--read-only/--write`: 書き込み有無（既定 `--write`）
- `--delete-broken`: 実行前に壊れ注釈を削除
- `--keep-broken`: 壊れ注釈削除を抑止
- 通常運用の推奨ルートでは、このコマンドを先に実行します。
- タグ遷移と `base -> translate` の流れは [workflows.md](workflows.md) を参照してください。

代表コマンド:

```bash
zotero-annotator base --write --item-key ABCD1234
zotero-annotator base --tag to-translate --max-items 5
```

## `zotero-annotator translate`

`base` で作成済みの注釈本文を in-place で翻訳更新します。新規注釈は作りません。

- `--item-key TEXT`（複数可）: item 指定実行
- `--max-items INTEGER`: 処理件数上限（既定 `10`）
- `--read-only/--write`: 書き込み有無（既定 `--write`）

仕様:

- `translate` には `--tag` はありません。
- `--item-key` 未指定時は `Z_BASE_DONE_TAG`（既定 `base-done`）付き item を一括処理します。
- 通常運用の推奨ルートでは、`base` の後にこのコマンドを実行します。
- タグ遷移、対象 annotation の条件、再翻訳手順は [workflows.md](workflows.md) を参照してください。

代表コマンド:

```bash
zotero-annotator translate --write --item-key ABCD1234
zotero-annotator translate --write
```
