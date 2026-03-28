# 開発ガイド

このドキュメントは `zotero-annotator dev` の補助コマンドと、開発時に確認する実行時パラメータをまとめたものです。通常利用者向けの CLI は [CLI リファレンス](cli.md)、タグ運用は [運用フロー](workflows.md) を参照してください。

## 基本方針

- 通常運用では `run` / `base` / `translate` を使います。
- `dev` は抽出確認、単発再現、監査、修復、削除のための補助コマンドです。
- 修復系と削除系はまず `--read-only` で確認し、必要なときだけ `--write` を使います。

## `zotero-annotator dev`

### 抽出結果を確認する

- `dev paragraphs --item-key ABCD1234 --max-rows 30`
  - 現在の設定で抽出された段落を JSON で確認します。
  - `--out PATH` を付けるとプレビューをファイル出力します。
- `dev dump-xml --item-key ABCD1234`
  - PyMuPDF の段落抽出結果を XML 出力します。
  - `--out-pymupdf PATH` で出力先変更、`--drop-captions` で caption を除外できます。
- `dev dump-pymupdf-raw-text --item-key ABCD1234`
  - 段落化やフィルタより前の page-level raw text を JSON 出力します。
  - `--out PATH` で JSON 出力先、`--out-text PATH` でプレーンテキストも同時出力できます。
- `dev dump-pymupdf-dict --item-key ABCD1234`
  - `page.get_text("dict")` の生データを JSON 出力します。
  - `--include-binary` を付けると bytes を base64 で含めます。出力が大きくなります。
- `dev reconstruct-from-pymupdf-dict --in pymupdf.dict.ABCD1234.json`
  - 既存の `pymupdf.dict` ダンプから段落を再構築します。
  - このコマンドは offline で動き、Zotero API を使いません。

### 単発で注釈や翻訳を再現する

- `dev annotate --item-key ABCD1234 --paragraph-index 0 --read-only`
  - 1 段落だけ注釈 payload を確認します。
  - `--write` を付けると 1 件だけ注釈を作成します。
  - `--translate` で翻訳付きコメントに切り替えられます。
  - `--annotation-mode note|highlight` で出力モードを上書きできます。
  - 既存注釈に同じ `para:<hash>` があれば重複としてスキップします。
- `dev translate --item-key ABCD1234 --paragraph-index 0`
  - 1 段落だけ翻訳し、source と translated をその場で表示します。
  - 注釈は作成しません。

### 既存注釈を監査・修復する

- `dev audit-annotations --item-key ABCD1234`
  - 現在の抽出段落と既存注釈を突き合わせます。
  - `para:<hash>` の不足や、`annotationSortIndex` / `annotationPageLabel` / `annotationPosition` の欠落を確認するときに使います。
  - `--max-problem-rows N` で問題行の表示数を絞れます。
- `dev repair-annotations --item-key ABCD1234 --read-only`
  - `para:<hash>` を手がかりに、壊れた注釈の位置情報を再計算します。
  - 修復対象は `annotationSortIndex` / `annotationPageLabel` / `annotationPosition` の欠落注釈です。
  - `--write` で Zotero 上の注釈を更新します。

### 壊れた注釈を削除する

- `dev delete-broken-annotations --item-key ABCD1234 --read-only`
  - 必須フィールドが欠けた注釈だけを列挙します。
  - `--write` で該当注釈を削除します。
- `dev delete-all-annotations --item-key ABCD1234 --read-only`
  - 対象 item の PDF 注釈を全件確認します。
  - `--write` で対象 PDF 配下の注釈を全削除します。

## 実装メモ

- 翻訳プロンプトは [../src/zotero_annotator/services/translators/prompts.py](../src/zotero_annotator/services/translators/prompts.py) で管理しています。
