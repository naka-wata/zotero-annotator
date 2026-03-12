# Workflows

このドキュメントは通常運用の流れとタグ遷移をまとめたものです。CLI のオプション一覧は [cli.md](cli.md) を参照してください。

## どの流れを使うか

- `zotero-annotator base -> zotero-annotator translate`: 通常運用の推奨ルートです。原文注釈を先に確認でき、Zotero 上の手修正を翻訳結果に反映できます。
- `zotero-annotator run`: 手修正を挟まず、抽出から翻訳付き注釈作成までを 1 回で完了させたいときに使います。
- `zotero-annotator search`: 実行前に対象 item を確認したいときに使います。

`run` と `base -> translate` の違い:

- `base -> translate` は通常運用の基準ルートです。
- `run` は同じ実行の中で抽出と翻訳を行います。
- `base -> translate` は既存注釈本文を後段で翻訳します。`translate` の翻訳元は PyMuPDF の再抽出結果ではなく、Zotero 上の既存ノート本文です。
- `base -> translate` は `base` と `translate` の間でノート本文を手修正したい場合に向いています。

## 対象 item の選び方

- `search` は `Z_TARGET_TAG`（既定 `to-translate`）と `Z_BASE_DONE_TAG`（既定 `base-done`）を参照します。
- `search --tag` 未指定時の対象集合は `Z_TARGET_TAG OR Z_BASE_DONE_TAG` です。
- `search --tag` 指定時の対象集合は `Z_BASE_DONE_TAG OR (--tag で指定した全て)` です。
- `run` と `base` は `--tag` または `--item-key` で対象を指定できます。
- `translate` には `--tag` がありません。`--item-key` 未指定時は `Z_BASE_DONE_TAG` 付き item を処理します。

## `run` フロー

`run` は簡易ルートです。途中で原文注釈を見直したり手修正したりしない場合に使います。

1. 必要なら `zotero-annotator search` で対象 item を確認します。
2. `zotero-annotator run --write ...` を実行します。
3. PyMuPDF で段落抽出し、そのまま翻訳付き注釈を作成します。
4. 完了判定になった item は `Z_DONE_TAG`（既定 `translated`）が付き、`Z_REMOVE_TAG`（既定 `to-translate`）と `Z_BASE_DONE_TAG` が外れます。
5. `--read-only` では Zotero 書き込みもタグ更新も行いません。

代表コマンド:

```bash
zotero-annotator run --write --item-key ABCD1234
zotero-annotator run --tag to-translate --max-items 5
```

## `base -> translate` フロー

`base -> translate` は通常運用の推奨ルートです。

1. `zotero-annotator base --write ...` で原文ノート注釈を作成します。
2. `base --write` が完了判定になると、item から `Z_REMOVE_TAG`（既定 `to-translate`）が外れ、`Z_BASE_DONE_TAG`（既定 `base-done`）が付きます。
3. `base` が新規作成した annotation には `para:<hash>` と `ANN_PENDING_TRANSLATION_TAG`（既定 `za:translate`）が付きます。
4. 必要なら Zotero 上で注釈本文を手修正します。
5. `zotero-annotator translate --write ...` で既存注釈本文を in-place 更新します。`translate` は新規注釈を作りません。
6. `translate` は `ANN_PENDING_TRANSLATION_TAG` が付いた annotation だけを翻訳対象にします。`ANN_TRANSLATED_TAG`（既定 `za:translated`）が付いた annotation は再翻訳しません。
7. annotation 本文更新が成功した場合のみ、同じ更新で `ANN_PENDING_TRANSLATION_TAG` を外し、`ANN_TRANSLATED_TAG` を付けます。
8. `translate --write` の結果、item 内に pending annotation が残っていなければ、item から `Z_BASE_DONE_TAG` が外れ、`Z_DONE_TAG`（既定 `translated`）が付きます。
9. `--read-only` では item / annotation のタグ更新は行いません。

代表コマンド:

```bash
zotero-annotator base --write --item-key ABCD1234
zotero-annotator translate --write --item-key ABCD1234
zotero-annotator translate --write
```

## タグ遷移

item レベル:

| 実行 | 主な遷移 |
| --- | --- |
| `run --write` | `to-translate` などの通常対象から `translated` へ進めます。成功時は `to-translate` と `base-done` を外します。 |
| `base --write` | `to-translate` から `base-done` へ進めます。 |
| `translate --write` | `base-done` から `translated` へ進めます。 |

annotation レベル:

| 実行 | 主な遷移 |
| --- | --- |
| `base --write` | `para:<hash>` と `ANN_PENDING_TRANSLATION_TAG` を付けます。 |
| `translate --write` | `ANN_PENDING_TRANSLATION_TAG` を外し、`ANN_TRANSLATED_TAG` を付けます。 |

## 再翻訳

単一ノートを再翻訳したい場合:

1. Zotero で対象 annotation の `ANN_TRANSLATED_TAG`（既定 `za:translated`）を外します。
2. 同じ annotation に `ANN_PENDING_TRANSLATION_TAG`（既定 `za:translate`）を付けます。
3. `zotero-annotator translate --write --item-key ABCD1234` を再実行します。
