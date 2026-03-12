# Setup

このドキュメントは初回セットアップ専用です。`.env` の各項目の説明は [configuration.md](configuration.md) を参照してください。利用可能なキー名と例示値・既定値は [../.env.example](../.env.example) を正本として扱います。

## Prerequisites

- Python `3.11+`
- `uv`
- Zotero API の認証情報
- 利用する翻訳 provider の認証情報、または起動済みの local LLM

`TRANSLATOR_PROVIDER=local_llm` を使う場合の server 起動手順は [local-llm.md](local-llm.md) を参照してください。

## First-time setup

```bash
uv venv
UV_LINK_MODE=copy uv sync --no-editable
source .venv/bin/activate
cp .env.example .env
```

## Configure `.env`

`.env` はリポジトリ直下に置きます。推奨手順は `.env.example` をコピーして編集する方法です。

1. [../.env.example](../.env.example) を元に `.env` を作成する
2. 共通の必須項目を埋める
3. 選んだ provider の必須項目を埋める
4. 必要なら任意項目を調整する

項目ごとの説明は [configuration.md](configuration.md) にまとめています。

## Verify

設定後は仮想環境を有効化した状態で読み取り専用コマンドを 1 つ実行すると確認しやすいです。

```bash
zotero-annotator search --max-items 1
```

新しい shell を開いた後は毎回 `source .venv/bin/activate` を実行してください。
