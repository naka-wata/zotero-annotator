# CLI Specification

このファイルは `zotero-annotator` の現行CLI仕様をまとめたものです。
実装と一致するコマンドのみ記載しています。

## 実行前提（開発環境）

`UV_LINK_MODE=copy` は `uv` 実行時のリンク方式を指定する環境変数です（CLI実行自体には不要）。

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

メイン処理を実行します（段落抽出→注釈作成、必要なら翻訳）。

- `--tag TEXT`: 対象タグの上書き
- `--item-key KEY`: 対象item-key（複数指定可）
- `--max-items INT`: 1回で処理する論文数（既定: `10`）
- `--read-only/--write`: 書き込み有無（既定: `--read-only`）
- `--translate/--no-translate`: 翻訳して注釈コメントにする（既定: `--translate`）
- `--delete-broken`: 処理前に「壊れ注釈」を削除する（明示実行）
- `--keep-broken`: `.env` 側の自動削除設定を無効化（上書き）

補足:

- 翻訳は `.env` の `TRANSLATOR_PROVIDER` / `TARGET_LANG` / `SOURCE_LANG` を使用（`--no-translate` の場合は DeepL などのAPIは呼ばない）
- `--item-key` を指定した場合は、そのitem-key群だけを処理
- `--tag` と `--item-key` は同時指定不可
- 1論文あたりの段落上限は `.env` の `RUN_MAX_PARAGRAPHS_PER_ITEM` で設定
- `.env` の `RUN_DELETE_BROKEN_ANNOTATIONS=1` を設定すると、`run --write` 前に自動で「壊れ注釈」を削除（既定: `0`）
- `.env` の `RUN_REPAIR_BROKEN_ANNOTATIONS=1` を設定すると、`run --write` 前に `para:<hash>` で紐づけ可能な壊れ注釈を自動修復（既定: `1`）
- `.env` の `PARA_MERGE_SPLITS=1` を設定すると、数式付近などで分断された段落を保守的に結合（既定: `0`）
- `.env` の `PARA_FORMULA_PLACEHOLDER` で `<formula>` を置換する文字列を指定（既定: `[MATH]`）
- `.env` の `PARA_MATH_NEWLINES=1` で、`[MATH] (n)` を前後改行して読みやすくする（既定: `0`）
- `.env` の `PARA_MIN_MEDIAN_COORD_H` を設定すると、座標の文字高さ（h）の中央値が小さい段落（図中の軸ラベル等）を除外（既定: `0`=無効、`auto`=自動推定）
- `.env` の `PARA_MIN_MEDIAN_COORD_H_AUTO_RATIO` は `auto` 時の比率（閾値= q75×ratio, 既定: `0.7`）
- `.env` の `PARA_CONNECTOR_MAX_CHARS` 以下の接続語-only段落（例: `where`）は、`PARA_MIN_CHARS` 判定の前に前後へ吸収してからフィルタ
- `.env` の `PARA_SKIP_ALGORITHMS=1` で、擬似コード（例: `Algorithm 1 ...`）のブロックを注釈対象から除外（既定: `0`）
- `.env` の `PARA_STRIP_PLOT_AXIS_PREFIX=1` で、`Figure N:` の直前に混入した「図中の軸ラベル等の数値列」を除去（既定: `0`）
- `.env` の `PARA_SKIP_CAPTIONS=1` で、図表キャプション段落（例: `Figure 4: ...`, `Table 1: ...`）を注釈対象から除外（既定: `0`）
- `.env` の `ANNOTATION_MODE` で、Zoteroに作成する注釈タイプを切替（`note` / `highlight`、既定: `note`）
- 「壊れ注釈」= `annotationSortIndex` / `annotationPageLabel` / `annotationPosition` のいずれかが欠けている注釈（Zotero 7 の `NOT NULL constraint failed: itemAnnotations.sortIndex` 対策）

例:

```bash
zotero-annotator run --read-only --tag to-translate --max-items 1
zotero-annotator run --write --tag to-translate --max-items 1
zotero-annotator run --read-only --item-key ZSE2H5HV --item-key ABCD1234
zotero-annotator run --write --no-translate --item-key ZSE2H5HV --max-items 1
zotero-annotator run --write --delete-broken --item-key ZSE2H5HV --max-items 1
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
- `--debug-coord-h`: 座標hフィルタの閾値（auto時は推定値）と、各段落の `median_coord_h` を表示

出力項目:

- `index`（0始まり）
- `hash`
- `page`
- `text`
- `coords`
- `median_coord_h`（`--debug-coord-h` 指定時のみ）

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
- `--translate/--no-translate`: 注釈前に翻訳する（既定: `--no-translate`）

動作:

- `--read-only`: 送信予定payloadを表示（Zoteroには書き込まない）
- `--write`: annotationを1件だけ作成
- 既存注釈に `para:<hash>` タグがある場合は重複スキップ

例:

```bash
zotero-annotator dev annotate --item-key ZSE2H5HV --paragraph-index 0 --read-only
zotero-annotator dev annotate --item-key ZSE2H5HV --paragraph-index 0 --write
zotero-annotator dev annotate --item-key ZSE2H5HV --paragraph-index 0 --write --translate
```

### `zotero-annotator dev translate`

指定段落1件だけを翻訳して、原文と翻訳文を表示します（書き込みなし）。

- `--item-key KEY`: 対象アイテムキー（必須）
- `--paragraph-index INT`: 0始まり段落インデックス（既定: `0`）

例:

```bash
zotero-annotator dev translate --item-key ZSE2H5HV --paragraph-index 0
```

### `zotero-annotator dev audit-annotations`

抽出した段落（`para:<hash>`）と、Zotero上の注釈を突き合わせて監査します。

- `--item-key KEY`: 対象アイテムキー（必須）
- `--max-problem-rows INT`: 問題例の表示上限（既定: `10`）

例:

```bash
zotero-annotator dev audit-annotations --item-key ZSE2H5HV
```

### `zotero-annotator dev repair-annotations`

既存注釈の必須フィールド（`annotationSortIndex`/`annotationPosition`/`annotationPageLabel`）が欠けている場合に、GROBIDの段落座標から再計算して埋め直します。

- `--item-key KEY`: 対象アイテムキー（必須）
- `--read-only/--write`: 書き込み有無（既定: `--read-only`）

例:

```bash
zotero-annotator dev repair-annotations --item-key ZSE2H5HV --read-only
zotero-annotator dev repair-annotations --item-key ZSE2H5HV --write
```

### `zotero-annotator dev delete-broken-annotations`

必須フィールド欠落の「壊れ注釈」を削除します（`run` の自動削除と同じ判定）。

- `--item-key KEY`: 対象アイテムキー（必須）
- `--read-only/--write`: 書き込み有無（既定: `--read-only`）

例:

```bash
zotero-annotator dev delete-broken-annotations --item-key ZSE2H5HV --read-only
zotero-annotator dev delete-broken-annotations --item-key ZSE2H5HV --write
```

## 注意点

- `TRANSLATOR_PROVIDER=openai` は未実装です（現状は `deepl` のみ）。
- `dev` サブコマンドは検証用途を優先した設計です。
