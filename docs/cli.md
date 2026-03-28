# CLI リファレンス

セットアップは [セットアップ](setup.md)、翻訳プロバイダーと `.env` の各項目は [設定](configuration.md) を参照してください。通常運用の流れとタグ遷移は [運用フロー](workflows.md) を参照してください。通常運用の推奨ルートは `base -> translate` です。`dev` コマンドと開発向け補助情報は [開発ガイド](development.md) にまとめています。

## 実行前提

初回のみ:

```bash
uv venv
UV_LINK_MODE=copy uv sync --no-editable
```

新しい shell を開くたびに:

```bash
source .venv/bin/activate
```

## コマンド一覧

- `zotero-annotator search`: 対象 item を確認する
- `zotero-annotator base`: 翻訳なしで原文注釈を作成する
- `zotero-annotator translate`: 既存注釈だけを翻訳更新する
- `zotero-annotator run`: 抽出から翻訳付き注釈作成まで一気に実行する

## `zotero-annotator search`

タグで Zotero item を一覧表示します。読み取り専用です。

- 通常運用のタグの意味と流れは [運用フロー](workflows.md) を参照してください。
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
- `--read-only`: Zotero へ書き込まず確認だけ行う
- `--delete-broken`: 実行前に壊れ注釈を削除
- `--keep-broken`: 壊れ注釈削除を抑止

注意:

- `--tag` と `--item-key` は同時指定できません。
- 壊れ注釈は `annotationSortIndex` / `annotationPageLabel` / `annotationPosition` の欠落注釈を指します。
- 通常運用では `base -> translate` を推奨します。`run` は手修正を挟まない一括実行向けです。
- タグ運用の詳細は [運用フロー](workflows.md) を参照してください。

代表コマンド:

```bash
zotero-annotator run --item-key ABCD1234
zotero-annotator run --tag to-translate --max-items 5
```

## `zotero-annotator base`

翻訳なしで原文注釈を作成します。

- `--tag TEXT`: タグ指定実行
- `--item-key TEXT`（複数可）: item 指定実行
- `--max-items INTEGER`: 処理件数上限（既定 `10`）
- `--read-only`: Zotero へ書き込まず確認だけ行う
- `--delete-broken`: 実行前に壊れ注釈を削除
- `--keep-broken`: 壊れ注釈削除を抑止
- `base` が作る注釈は段落抽出に依存する下書きです。`base` で作成した各アノテーションノートには CLI が `za:translate` を付けます。`translate` の前に Zotero 上で確認してください。
- 通常運用の推奨ルートでは、このコマンドを先に実行します。
- タグ遷移と `base -> translate` の流れは [運用フロー](workflows.md) を参照してください。

代表コマンド:

```bash
zotero-annotator base --item-key ABCD1234
zotero-annotator base --tag to-translate --max-items 5
```

## `zotero-annotator translate`

`base` で作成済みの注釈本文を in-place で翻訳更新します。新規注釈は作りません。

- `--item-key TEXT`（複数可）: item 指定実行
- `--max-items INTEGER`: 処理件数上限（既定 `10`）
- `--read-only`: Zotero へ書き込まず確認だけ行う

仕様:

- `translate` には `--tag` はありません。
- `--item-key` 未指定時は `Z_BASE_DONE_TAG`（既定 `base-done`）付き item を一括処理します。
- 翻訳対象は、`base` の後に `za:translate` が付いたアノテーションノートです。タグ運用の詳細は [運用フロー](workflows.md) を参照してください。
- 通常運用の推奨ルートでは、`base` の後にこのコマンドを実行します。
- タグ遷移、対象注釈の条件、再翻訳手順は [運用フロー](workflows.md) を参照してください。

代表コマンド:

```bash
zotero-annotator translate --item-key ABCD1234
zotero-annotator translate
```
