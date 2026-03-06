# CLI Specification (PyMuPDF Beta)

このドキュメントは現在の `zotero-annotator` CLI 実装に合わせた仕様です。  
beta 版は **PyMuPDF 固定**で動作し、GROBID コマンドはありません。

## 実行前提

```bash
uv venv
UV_LINK_MODE=copy uv sync --no-editable
source .venv/bin/activate
```

## コマンドの役割（run / base / translate）

- `run`: 常に翻訳ありで注釈を作成するメインコマンド
- `base`: 翻訳なしで原文注釈を作成する正規コマンド
- `translate`: 既存注釈を翻訳するコマンド

タグ遷移の考え方:

- `run` は常に翻訳ありで完結するコマンドです。`base` / `translate` の2段階運用とは役割が違います。
- `base` の `--write` 実行で完了判定になった item は、`to-translate` が外れて `base-done` が付きます。
- `base` の dry-run ではタグは変わりません。タグ遷移は write 時かつ完了判定時のみ発生します。
- `translate` の `--write` 実行が成功した item は、`base-done` が外れて `translated` が付きます。
- `translate` の dry-run や失敗時はタグは変わりません。タグ遷移は write 時かつ成功時のみ発生します。

## トップレベルコマンド

- `zotero-annotator search`
- `zotero-annotator run`
- `zotero-annotator base`
- `zotero-annotator translate`
- `zotero-annotator dev ...`

---

## `zotero-annotator search`

タグで Zotero アイテムを一覧表示します（読み取りのみ）。

- `--tag TEXT`: 対象タグ上書き（未指定時は `Z_TARGET_TAG`）
- `--max-items INTEGER`: 表示上限（既定 `20`）

例:

```bash
zotero-annotator search --tag to-translate --max-items 5
```

---

## `zotero-annotator run`

メイン処理（抽出→翻訳→注釈作成）を実行します。

- `--tag TEXT`: タグ指定実行
- `--item-key TEXT`（複数可）: item 指定実行
- `--max-items INTEGER`: 処理件数上限（既定 `10`）
- `--read-only/--write`: 書き込み有無（既定 `--write`）
- `--delete-broken`: 実行前に壊れ注釈を削除
- `--keep-broken`: 壊れ注釈削除を抑止（設定上書き）

注意:

- `--tag` と `--item-key` は同時指定不可
- 翻訳なし運用は `base` を使用
- `run` は常に翻訳ありで、`to-translate -> base-done -> translated` の段階運用とは別の役割です
- `TRANSLATOR_PROVIDER=openai` は未実装
- 壊れ注釈 = `annotationSortIndex` / `annotationPageLabel` / `annotationPosition` の欠落注釈

例:

```bash
zotero-annotator run --write --item-key ABCD1234
```

---

## `zotero-annotator base`

翻訳なしで原文注釈を作成します。

- `--tag TEXT`: タグ指定実行
- `--item-key TEXT`（複数可）: item 指定実行
- `--max-items INTEGER`: 処理件数上限（既定 `10`）
- `--read-only/--write`: 書き込み有無（既定 `--write`）
- `--delete-broken`: 実行前に壊れ注釈を削除
- `--keep-broken`: 壊れ注釈削除を抑止（設定上書き）

例:

```bash
zotero-annotator base --write --item-key ABCD1234
```

タグ遷移:

- `--write` かつ完了判定時のみ、`to-translate` を外して `base-done` を付けます。
- `--read-only` ではタグは変わりません。

---

## `zotero-annotator translate`

既存注釈の本文を in-place で翻訳更新します。

- `--item-key TEXT`（複数可）: item 指定実行
- `--max-items INTEGER`: 処理件数上限（既定 `10`）
- `--read-only/--write`: 書き込み有無（既定 `--write`）

仕様:

- `translate` には `--tag` はありません（対象分岐を増やさないため）。
- `--item-key` 未指定時は `Z_BASE_DONE_TAG`（既定 `base-done`）付き item を一括処理します。
- **新規注釈は作成せず、既存注釈の `annotationComment`（または `note` 本文）だけ更新します。**
- 翻訳元は PyMuPDF 再抽出テキストではなく、Zotero 上の既存ノート本文（手修正済み）を使います。
- `--write` かつ成功時のみ、`base-done` を外して `translated` を付けます。
- `--read-only` や失敗時はタグは変わりません。

例:

```bash
zotero-annotator base --write --item-key ABCD1234
zotero-annotator translate --write --item-key ABCD1234
zotero-annotator translate --write
```

推奨フロー（base -> edit -> translate）:

1. `zotero-annotator base --write ...` で原文注釈を作成
2. Zotero で必要な注釈だけ手修正
3. `zotero-annotator translate --write ...` で本文を翻訳更新

運用上のタグ遷移:

1. 開始時: `to-translate`
2. `base --write` が完了判定: `base-done`
3. `translate --write` が成功: `translated`

---

## `zotero-annotator dev` サブコマンド

### 1) 段落抽出・再構築デバッグ

#### `dev dump-xml`

PyMuPDF 段落抽出結果を XML 出力します。

- `--item-key TEXT`（必須）
- `--out-pymupdf PATH`（既定 `pymupdf.paragraphs.xml`）
- `--drop-captions`

```bash
zotero-annotator dev dump-xml --item-key ABCD1234
```

#### `dev dump-pymupdf-raw-text`

段落化前のページ raw text を JSON で出力します。

- `--item-key TEXT`（必須）
- `--out PATH`
- `--out-text PATH`

```bash
zotero-annotator dev dump-pymupdf-raw-text --item-key ABCD1234
```

#### `dev dump-pymupdf-dict`

`page.get_text("dict")` の生データを JSON 出力します。

- `--item-key TEXT`（必須）
- `--out PATH`（既定 `pymupdf.dict.<item_key>.json`）
- `--include-binary`

```bash
zotero-annotator dev dump-pymupdf-dict --item-key ABCD1234
```

#### `dev reconstruct-from-pymupdf-dict`

既存の `pymupdf.dict.*.json` から段落を再構築します（オフライン）。

- `--in PATH`（必須）
- `--out-xml PATH`（既定 `pymupdf.paragraphs.fromdict.xml`）
- `--out-json PATH`
- `--drop-captions`

```bash
zotero-annotator dev reconstruct-from-pymupdf-dict --in pymupdf.dict.ABCD1234.json --out-json out.json
```

#### `dev paragraphs`

抽出段落を一覧確認します。

- `--item-key TEXT`（必須）
- `--out PATH`
- `--max-rows INTEGER`（既定 `20`）

```bash
zotero-annotator dev paragraphs --item-key ABCD1234 --max-rows 30
```

### 2) 注釈作成/翻訳デバッグ

#### `dev annotate`

1段落だけ注釈作成（または dry-run）します。

- `--item-key TEXT`（必須）
- `--paragraph-index INTEGER`（既定 `0`）
- `--read-only/--write`（既定 `--write`）
- `--translate`（指定時のみ翻訳）
- `--annotation-mode TEXT`（`note` / `highlight` の上書き）

```bash
zotero-annotator dev annotate --item-key ABCD1234 --paragraph-index 0 --read-only
zotero-annotator dev annotate --item-key ABCD1234 --paragraph-index 0 --write --translate
```

#### `dev translate`

1段落だけ翻訳結果を表示します（書き込みなし）。

- `--item-key TEXT`（必須）
- `--paragraph-index INTEGER`（既定 `0`）

```bash
zotero-annotator dev translate --item-key ABCD1234 --paragraph-index 0
```

### 3) 既存注釈の監査・修復・削除

#### `dev audit-annotations`

抽出段落と既存注釈の整合性を監査します。

- `--item-key TEXT`（必須）
- `--max-problem-rows INTEGER`（既定 `10`）

```bash
zotero-annotator dev audit-annotations --item-key ABCD1234
```

#### `dev repair-annotations`

必須フィールド欠落注釈を修復します。

- `--item-key TEXT`（必須）
- `--read-only/--write`（既定 `--write`）

```bash
zotero-annotator dev repair-annotations --item-key ABCD1234 --write
```

#### `dev delete-broken-annotations`

壊れ注釈のみ削除します。

- `--item-key TEXT`（必須）
- `--read-only/--write`（既定 `--write`）

```bash
zotero-annotator dev delete-broken-annotations --item-key ABCD1234 --write
```

#### `dev delete-all-annotations`

対象 PDF 添付の注釈を全削除します。

- `--item-key TEXT`（必須）
- `--read-only/--write`（既定 `--write`）

```bash
zotero-annotator dev delete-all-annotations --item-key ABCD1234 --write
```

---

## beta 固定パラメータ（変更不可）

beta 版では以下をコード固定しています（`.env` 上書き不可）。

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
