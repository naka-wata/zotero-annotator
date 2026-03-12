# Zotero Annotator

Zotero の PDF を段落ごとに注釈化し、翻訳付きノートを自動で残す CLI です。研究メモ作成を、PDF と翻訳ツールの往復なしで進められます。


## Why researchers use it

- **研究メモを Zotero に集約**: 原文段落と翻訳を同じ注釈に残せます。
- **単発でもキュー処理でも使える**: `--item-key` で 1 本ずつ、タグ運用でまとめて処理できます。
- **再実行しやすい**: `run` と `base -> translate` を使い分けられ、`para:<hash>` で重複注釈も抑えます。

## Quick start

最短で試す手順です。

```bash
uv venv
UV_LINK_MODE=copy uv sync --no-editable
source .venv/bin/activate
cp .env.example .env
```

必須項目だけ `.env` に入れたら、まず 1 件試せます。セットアップと設定の詳細は [docs/setup.md](docs/setup.md) と [docs/configuration.md](docs/configuration.md) を参照してください。

```bash
zotero-annotator search --max-items 1
zotero-annotator run --write --item-key ABCD1234
```

通常運用では、原文注釈を確認してから翻訳する `base -> translate` ルートを推奨します。

```bash
zotero-annotator base --write --item-key ABCD1234
zotero-annotator translate --write --item-key ABCD1234
```

## Demo

1 本の論文 PDF から、段落抽出、翻訳、Zotero 注釈の作成までを CLI で通せます。

<!-- Insert screenshot or GIF here -->

## Docs

- 初回セットアップ: [docs/setup.md](docs/setup.md)
- CLI リファレンス: [docs/cli.md](docs/cli.md)
- 運用フローとタグ遷移: [docs/workflows.md](docs/workflows.md)
- `.env` 設定: [docs/configuration.md](docs/configuration.md)
- Local LLM の起動手順: [docs/local-llm.md](docs/local-llm.md)
- 開発向け情報: [docs/development.md](docs/development.md)
