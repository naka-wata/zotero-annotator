# Zotero Annotator

Zotero の PDF を段落ごとに注釈化し、翻訳付きノートを自動で残す CLI です。研究メモ作成を、PDF と翻訳ツールの往復なしで進められます。


## 特徴

- **研究メモを Zotero に集約**: 原文段落と翻訳を同じ注釈に残せます。
- **単発でもキュー処理でも使える**: `--item-key` で 1 本ずつ、タグ運用でまとめて処理できます。
- **再実行しやすい**: `run` と `base -> translate` を使い分けられ、`para:<hash>` で重複注釈も抑えます。

## クイックスタート

最短で試す手順です。

```bash
uv venv
UV_LINK_MODE=copy uv sync --no-editable
source .venv/bin/activate
cp .env.example .env
```

必須項目だけ `.env` に入れたら、まず 1 件試せます。セットアップは [セットアップ](docs/setup.md)、`.env` の項目説明は [設定](docs/configuration.md)、通常運用の流れは [運用フロー](docs/workflows.md) を参照してください。

```bash
zotero-annotator search --max-items 1
zotero-annotator run --write --item-key ABCD1234
```

通常運用では、原文注釈を確認してから翻訳する `base -> translate` ルートを推奨します。各コマンドの詳細は [CLI リファレンス](docs/cli.md) にまとめています。

```bash
zotero-annotator base --write --item-key ABCD1234
zotero-annotator translate --write --item-key ABCD1234
```

## デモ

1 本の論文 PDF から、段落抽出、翻訳、Zotero 注釈の作成までを CLI で通せます。

<!-- Insert screenshot or GIF here -->

## ドキュメント

迷ったら `セットアップ -> 設定 -> CLI リファレンス / 運用フロー` の順で見れば十分です。

- セットアップ: [セットアップ](docs/setup.md)
- 設定: [設定](docs/configuration.md)
- CLI リファレンス: [CLI リファレンス](docs/cli.md)
- 運用フロー: [運用フロー](docs/workflows.md)
- ローカル LLM セットアップ: [ローカル LLM セットアップ](docs/local-llm.md)
- 開発ガイド: [開発ガイド](docs/development.md)

## Third-party licensing note

- 本リポジトリのソースコード自体は `LICENSE` に記載のとおり MIT License で提供します。
- ただし、依存ライブラリにはそれぞれ別のライセンスが適用されます。
- 特に `pymupdf` は公式情報上、AGPL または Artifex の商用ライセンスで提供されています。
- そのため、本リポジトリのコードを MIT で公開することと、依存ライブラリを含む形でアプリやサービスを配布・提供できるかは別問題です。
- 配布または公開前に、各依存ライブラリのライセンス条件、著作権表示、NOTICE 要件を確認してください。
- 必要に応じて法務確認または商用ライセンスの検討を行ってください。
