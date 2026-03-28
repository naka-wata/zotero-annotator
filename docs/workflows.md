# 運用フロー

このドキュメントは通常運用の流れとタグ運用をまとめたものです。CLI のオプション一覧は [CLI リファレンス](cli.md)、タグ名の変更は [設定](configuration.md) を参照してください。

## どの流れを使うか

- `zotero-annotator base -> zotero-annotator translate`: 通常運用の推奨ルートです。`base` が作る下書きを Zotero 上で確認・手修正してから翻訳を反映できます。
- `zotero-annotator run`: 手修正を挟まず、抽出から翻訳付き注釈作成までを 1 回で終えたいときに使います。
- `zotero-annotator search`: 実行前に `to-translate` / `base-done` の item を確認したいときに使います。

## タグ運用の前提

- 処理したい Zotero item にユーザーが `to-translate` を付けて開始します。
- `base` が作成する注釈は、段落抽出に依存する下書きです。本文や分割に誤りがありえます。
- そのため `translate` の前に、作成済み注釈を一度 Zotero 上で確認し、必要なら本文を手修正してください。

## item タグ

| タグ | だれが付けるか | 用途 |
| --- | --- | --- |
| `to-translate` | ユーザー | 通常運用の開始対象にする |
| `base-done` | CLI | `base` 完了後、`translate` 待ちにする |
| `translated` | CLI | 翻訳完了済み item を示す |

## annotation タグ

| タグ | だれが付けるか | 用途 |
| --- | --- | --- |
| `za:translate` | CLI / ユーザー | 未翻訳 annotation。通常は `base` で新しく作成した各アノテーションノートに CLI が付けます。再翻訳したいときや手修正後に翻訳したいときはユーザーが使います。 |
| `za:translated` | CLI / ユーザー | 翻訳済み annotation。再翻訳したいときはユーザーが外します。 |

## タグの流れ

通常フローのタグ遷移は次のとおりです。

| 対象 | 流れ |
| --- | --- |
| item | `to-translate -> base-done -> translated` |
| annotation | `za:translate -> za:translated` |

1. `base` で、原文注釈の下書きを作成します。
2. `base` が完了すると、CLI はその item を `to-translate` から `base-done` に進めます。
3. 同時に CLI は、今作成した各アノテーションノートへ `za:translate` を付けます。`translate` はこのタグが付いたアノテーションノートだけを翻訳対象にします。
4. Zotero 上で `za:translate` が付いたアノテーションノートを一度確認し、必要なら本文を修正します。
5. `translate` は `za:translate` が付いたアノテーションノートを翻訳し、完了したものを `za:translated` に進めます。
6. 対象アノテーションノートの翻訳がすべて終わると、item は `base-done` から `translated` に進みます。

## `base` の直後に見るポイント

- Zotero item には `base-done` が付きます。
- `base` が作成した各アノテーションノートには `za:translate` が付きます。
- この時点のアノテーションノートはまだ未翻訳です。
- 段落抽出のずれや分割ミスがありうるので、`translate` の前に Zotero 上で内容を確認します。

## 再翻訳

1. Zotero で対象 annotation の `za:translated` を外します。
2. 同じ annotation に `za:translate` を付けます。
3. `zotero-annotator translate --item-key ABCD1234` を再実行します。
