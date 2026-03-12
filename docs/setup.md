# セットアップ

このドキュメントは初回セットアップ専用です。`.env` の各項目の説明は [設定](configuration.md)、実行コマンドの全体像は [CLI リファレンス](cli.md) を参照してください。利用可能なキー名と例示値・既定値は [../.env.example](../.env.example) を正本として扱います。

## 前提

- Python `3.11+`
- `uv`
- Zotero API の認証情報
- 利用する翻訳プロバイダーの認証情報、または起動済みのローカル LLM

`TRANSLATOR_PROVIDER=local_llm` を使う場合のサーバー起動手順は [ローカル LLM セットアップ](local-llm.md) を参照してください。

## 初回セットアップ

```bash
uv venv
UV_LINK_MODE=copy uv sync --no-editable
source .venv/bin/activate
cp .env.example .env
```

## `.env` を設定する

`.env` はリポジトリ直下に置きます。推奨手順は `.env.example` をコピーして編集する方法です。

1. [../.env.example](../.env.example) を元に `.env` を作成する
2. 共通の必須項目を埋める
3. 選んだプロバイダーの必須項目を埋める
4. 必要なら任意項目を調整する

項目ごとの説明は [設定](configuration.md) にまとめています。

## 動作確認

設定後は仮想環境を有効化した状態で読み取り専用コマンドを 1 つ実行すると確認しやすいです。

```bash
zotero-annotator search --max-items 1
```

新しい shell を開いた後は毎回 `source .venv/bin/activate` を実行してください。
