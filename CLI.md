# CLI Specification (PyMuPDF Beta)

このドキュメントは現在の `zotero-annotator` CLI 実装に合わせた使い方メモです。  
beta 版は **PyMuPDF 固定**で動作し、GROBID コマンドはありません。

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

Local LLM の詳細セットアップは [LOCAL_LLM_SETUP.md](/Users/watarunakamura/Desktop/zotero-annotator/LOCAL_LLM_SETUP.md) を参照してください。

翻訳 prompt は [src/zotero_annotator/services/translators/prompts.py](/Users/watarunakamura/Desktop/zotero-annotator/src/zotero_annotator/services/translators/prompts.py) で管理し、provider ごとに prompt 文面を分岐させない方針です。

## コマンド一覧

- `zotero-annotator search`: 対象 item を確認する
- `zotero-annotator run`: 抽出から翻訳付き注釈作成まで一気に実行する
- `zotero-annotator base`: 翻訳なしで原文注釈を作成する
- `zotero-annotator translate`: 既存注釈だけを翻訳更新する
- `zotero-annotator dev ...`: 検証・監査・修復用の補助コマンド

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

抽出から翻訳付き注釈作成までを一度に実行するメインコマンドです。

- `--tag TEXT`: タグ指定実行
- `--item-key TEXT`（複数可）: item 指定実行
- `--max-items INTEGER`: 処理件数上限（既定 `10`）
- `--read-only/--write`: 書き込み有無（既定 `--write`）
- `--delete-broken`: 実行前に壊れ注釈を削除
- `--keep-broken`: 壊れ注釈削除を抑止

注意:

- `--tag` と `--item-key` は同時指定できません。
- `run` は常に翻訳ありです。翻訳なし運用は `base`、後段翻訳は `translate` を使います。
- 壊れ注釈は `annotationSortIndex` / `annotationPageLabel` / `annotationPosition` の欠落注釈を指します。

代表コマンド:

```bash
zotero-annotator run --write --item-key ABCD1234
zotero-annotator run --tag to-translate --max-items 5
```

## `zotero-annotator base`

翻訳なしで原文注釈を作成します。`base -> translate` の2段階運用の前段です。

- `--tag TEXT`: タグ指定実行
- `--item-key TEXT`（複数可）: item 指定実行
- `--max-items INTEGER`: 処理件数上限（既定 `10`）
- `--read-only/--write`: 書き込み有無（既定 `--write`）
- `--delete-broken`: 実行前に壊れ注釈を削除
- `--keep-broken`: 壊れ注釈削除を抑止

タグ遷移:

- `--write` かつ完了判定時のみ、`to-translate` を外して `base-done` を付けます。
- `--read-only` では item タグは変わりません。
- 新規 annotation には `para:<hash>` と `ANN_PENDING_TRANSLATION_TAG`（既定 `za:translate`）が付きます。

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
- 翻訳元は PyMuPDF の再抽出結果ではなく、Zotero 上の既存ノート本文です。
- 翻訳対象は `ANN_PENDING_TRANSLATION_TAG`（既定 `za:translate`）が付いた annotation のみです。
- `ANN_TRANSLATED_TAG`（既定 `za:translated`）が付いた annotation は再翻訳しません。
- `--write` かつ成功時のみ、`base-done` を外して `translated` を付けます。
- annotation 本文更新が成功した場合のみ、同じ更新で `ANN_PENDING_TRANSLATION_TAG` を外して `ANN_TRANSLATED_TAG` を付けます。

推奨フロー:

1. `zotero-annotator base --write ...` で原文注釈を作成
2. Zotero で必要な注釈だけ手修正
3. `zotero-annotator translate --write ...` で本文を翻訳更新

代表コマンド:

```bash
zotero-annotator translate --write --item-key ABCD1234
zotero-annotator translate --write
```

単一ノートを再翻訳したい場合:

1. Zotero で対象 annotation の `ANN_TRANSLATED_TAG`（既定 `za:translated`）を外す
2. 同じ annotation に `ANN_PENDING_TRANSLATION_TAG`（既定 `za:translate`）を付ける
3. `zotero-annotator translate --write --item-key ABCD1234` を実行する

## `zotero-annotator dev`

`dev` は検証・監査・修復用です。通常運用は `run` / `base` / `translate` を使い、必要なときだけ `dev` を使います。

代表サブコマンド:

- `dev dump-xml`: PyMuPDF 段落抽出結果を XML 出力
- `dev dump-pymupdf-raw-text`: 段落化前の raw text を JSON 出力
- `dev dump-pymupdf-dict`: `page.get_text("dict")` の生データを JSON 出力
- `dev reconstruct-from-pymupdf-dict`: 既存 JSON から段落を再構築
- `dev paragraphs`: 抽出段落の確認
- `dev annotate`: 1段落だけ注釈作成または dry-run
- `dev translate`: 1段落だけ翻訳結果を確認
- `dev audit-annotations`: 既存注釈との整合性監査
- `dev repair-annotations`: 壊れ注釈の修復
- `dev delete-broken-annotations`: 壊れ注釈だけ削除
- `dev delete-all-annotations`: 対象 item の PDF 注釈を全削除

代表コマンド:

```bash
zotero-annotator dev paragraphs --item-key ABCD1234 --max-rows 30
zotero-annotator dev annotate --item-key ABCD1234 --paragraph-index 0 --read-only
zotero-annotator dev audit-annotations --item-key ABCD1234
zotero-annotator dev repair-annotations --item-key ABCD1234 --write
```

## runtime パラメータ

`.env` で変更できる主な抽出パラメータ:

- `PARA_MIN_CHARS`, `PARA_MAX_CHARS`: 抽出する段落の文字数範囲
- `PARA_MIN_MEDIAN_COORD_H`, `PARA_MIN_MEDIAN_COORD_H_AUTO_RATIO`: 小さすぎる文字段落を除外する閾値
- `PARA_SKIP_ALGORITHMS`: アルゴリズム / 疑似コードの除外
- `PARA_SKIP_CAPTIONS`: 図表キャプションの除外
- `PARA_DROP_CITATIONS`: 文中引用番号の除去
- `PARA_DROP_FOOTNOTE_MARKERS`: 脚注マーカーの除去
- `PARA_SKIP_REFERENCES`: 参考文献セクションの除外
- `PARA_SKIP_TABLE_LIKE`: 表本文っぽい段落の除外

コード固定の主なパラメータ:

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
