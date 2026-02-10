# CLI Specification

このファイルは `zotero-annotator` の現行CLI仕様をまとめたものです。
実装と一致するコマンドのみ記載しています。

## 実行前提（開発環境）

```bash
UV_LINK_MODE=copy uv sync --no-editable
```

## コマンド一覧

### `zotero-annotator search`

対象タグの Zotero アイテム一覧を表示します（書き込みなし）。

- `--tag TEXT`: 対象タグの上書き（未指定時は `.env` の `Z_TARGET_TAG`）
- `--max-items INT`: 表示件数上限（既定: `20`）

表示項目:

- `item-key`
- `title`
- `tags`

例:

```bash
zotero-annotator search --tag to-translate --max-items 5
```

### `zotero-annotator run`

メイン処理を実行します（現状は no-translation パイプライン固定）。

- `--tag TEXT`: 対象タグの上書き
- `--item-key KEY`: 対象item-key（複数指定可）
- `--max-items INT`: 1回で処理する論文数（既定: `10`）
- `--read-only/--write`: 書き込み有無（既定: `--read-only`）

補足:

- `--item-key` を指定した場合は、そのitem-key群だけを処理
- `--tag` と `--item-key` は同時指定不可
- 1論文あたりの段落上限は `.env` の `RUN_MAX_PARAGRAPHS_PER_ITEM` で設定

例:

```bash
zotero-annotator run --read-only --tag to-translate --max-items 1
zotero-annotator run --write --tag to-translate --max-items 1
zotero-annotator run --read-only --item-key ZSE2H5HV --item-key ABCD1234
```

### `zotero-annotator dev grobid`

指定アイテムのPDFを取得し、GROBIDでTEIを生成します。

- `--item-key KEY`: 対象アイテムキー（必須）
- `--out PATH`: TEI保存先（未指定時は先頭のみコンソール表示）

例:

```bash
zotero-annotator dev grobid --item-key ZSE2H5HV --out tei.xml
```

### `zotero-annotator dev paragraphs`

TEIから段落抽出結果を確認します。

- `--item-key KEY` または `--tei PATH` のどちらか一方を指定（同時指定不可）
- `--out PATH`: JSON保存先（未指定時はコンソール表示）
- `--max-rows INT`: 表示件数上限（既定: `20`）

出力項目:

- `index`（0始まり）
- `hash`
- `page`
- `text`
- `coords`

例:

```bash
zotero-annotator dev paragraphs --item-key ZSE2H5HV --max-rows 10
zotero-annotator dev paragraphs --tei tei.xml --out paragraphs.json --max-rows 20
```

### `zotero-annotator dev annotate`

位置検証用に、指定段落1件の annotation payload を確認または作成します。

- `--item-key KEY`: 対象アイテムキー（必須）
- `--paragraph-index INT`: 0始まり段落インデックス（既定: `0`）
- `--read-only/--write`: 書き込み有無（既定: `--read-only`）

動作:

- `--read-only`: 送信予定payloadを表示（Zoteroには書き込まない）
- `--write`: annotationを1件だけ作成
- 既存注釈に `para:<hash>` タグがある場合は重複スキップ

例:

```bash
zotero-annotator dev annotate --item-key ZSE2H5HV --paragraph-index 0 --read-only
zotero-annotator dev annotate --item-key ZSE2H5HV --paragraph-index 0 --write
```

## 注意点

- `run` の翻訳ありフローは未実装です。
- `dev` サブコマンドは検証用途を優先した設計です。
