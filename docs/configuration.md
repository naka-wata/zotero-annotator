# 設定

このドキュメントは `.env` の項目説明をまとめたものです。初回セットアップは [セットアップ](setup.md)、CLI の使い方は [CLI リファレンス](cli.md)、タグ運用の意味は [運用フロー](workflows.md) を参照してください。利用可能なキー名と例示値・既定値は [../.env.example](../.env.example) を正本として扱います。設定を追加・変更する場合は、まず `.env.example` を更新してください。

## 基本ルール

- `.env` はリポジトリ直下に置きます
- 推奨手順は `cp .env.example .env` です
- 実装は `.env` を自動で読み込みます
- 使っていないプロバイダーの項目は `.env.example` のプレースホルダーのままで構いません
- `TRANSLATOR_PROVIDER=openai` は `chatgpt` の後方互換エイリアスとして扱われます

## 共通の必須設定

以下はプロバイダーに関係なく必要です。

| Key | Purpose |
| --- | --- |
| `Z_SCOPE` | Zotero の対象種別です。`user` または `group` を指定します。 |
| `Z_ID` | Zotero の user ID または group ID です。 |
| `Z_API_KEY` | Zotero API key です。 |
| `TRANSLATOR_PROVIDER` | 翻訳プロバイダーを選びます。`deepl` / `chatgpt` / `local_llm` を使います。 |
| `TARGET_LANG` | 翻訳先言語です。 |

共通の任意項目:

| Key | Purpose |
| --- | --- |
| `SOURCE_LANG` | 翻訳元言語を固定したい場合に指定します。未設定時はプロバイダー側の自動判定を使います。 |

## プロバイダー別設定

### DeepL

必須:

| Key | Purpose |
| --- | --- |
| `DEEPL_API_KEY` | DeepL API key です。 |

任意:

| Key | Purpose |
| --- | --- |
| `DEEPL_API_URL` | DeepL エンドポイントを切り替えます。Pro を使う場合は `.env.example` のコメントにある URL に変更します。 |

最小例:

```dotenv
TRANSLATOR_PROVIDER=deepl
TARGET_LANG=JA
DEEPL_API_KEY=your_deepl_api_key_here
```

### OpenAI / ChatGPT API

必須:

| Key | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | OpenAI API key です。 |
| `OPENAI_MODEL` | 使用するモデル名です。 |

任意:

| Key | Purpose |
| --- | --- |
| `OPENAI_BASE_URL` | OpenAI 互換エンドポイントを使う場合に切り替えます。公式 API のままなら `.env.example` の既定値を使います。 |

最小例:

```dotenv
TRANSLATOR_PROVIDER=chatgpt
TARGET_LANG=JA
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-4o-mini
```

### ローカル LLM

必須:

| Key | Purpose |
| --- | --- |
| `LOCAL_LLM_BASE_URL` | OpenAI 互換エンドポイントの base URL です。Ollama を使う場合は `/v1` 付き URL を指定します。 |
| `LOCAL_LLM_MODEL` | 利用するローカルモデル名です。 |

任意:

| Key | Purpose |
| --- | --- |
| `LOCAL_LLM_TEMPERATURE` | 生成温度です。 |
| `LOCAL_LLM_TOP_P` | `top_p` です。 |

最小例:

```dotenv
TRANSLATOR_PROVIDER=local_llm
TARGET_LANG=JA
LOCAL_LLM_BASE_URL=http://localhost:11434/v1
LOCAL_LLM_MODEL=qwen2.5:7b-instruct
```

Ollama の起動手順やモデル例は [ローカル LLM セットアップ](local-llm.md) を参照してください。

## 任意のワークフロー設定

以下はタグ運用を調整したい場合だけ変更します。実際の既定値は [../.env.example](../.env.example) を参照してください。

| Key | Purpose |
| --- | --- |
| `Z_TARGET_TAG` | `search` / `run` / `base` が通常フローで参照する対象 item タグです。 |
| `Z_DONE_TAG` | `translate --write` 成功後に付ける item タグです。 |
| `Z_REMOVE_TAG` | `base --write` 完了時に外す item タグです。 |
| `Z_BASE_DONE_TAG` | `base --write` 完了後、または `translate` の入力集合として使う item タグです。 |
| `ANN_PENDING_TRANSLATION_TAG` | 未翻訳の注釈を示す注釈レベルのタグです。 |
| `ANN_TRANSLATED_TAG` | 翻訳済みの注釈を示す注釈レベルのタグです。 |

## 任意の抽出設定

以下は抽出対象の段落を調整したい場合に使います。実際の既定値は [../.env.example](../.env.example) を参照してください。

| Key | Purpose |
| --- | --- |
| `PARA_MIN_CHARS` | 抽出する段落の最小文字数です。 |
| `PARA_MAX_CHARS` | 抽出する段落の最大文字数です。 |
| `PARA_MIN_MEDIAN_COORD_H` | 小さすぎる文字段落を除外する閾値です。`auto` または数値を使います。`0` で無効化します。 |
| `PARA_MIN_MEDIAN_COORD_H_AUTO_RATIO` | `PARA_MIN_MEDIAN_COORD_H=auto` のときに使う係数です。 |
| `PARA_SKIP_ALGORITHMS` | アルゴリズム / 疑似コード風の段落を除外します。 |
| `PARA_SKIP_CAPTIONS` | 図表 caption を standalone 段落として除外します。 |
| `PARA_DROP_CITATIONS` | 文中引用番号を削除します。 |
| `PARA_DROP_FOOTNOTE_MARKERS` | 脚注マーカーを削除します。 |
| `PARA_SKIP_REFERENCES` | 参考文献セクションを除外します。 |
| `PARA_SKIP_TABLE_LIKE` | 表本文のような段落を除外します。 |

## コード固定の項目

以下は現在 `.env` では変更できません。

| Key | 固定値 | 備考 |
| --- | --- | --- |
| `PARA_CONNECTOR_MAX_CHARS` | `20` | |
| `PARA_MATH_NEWLINES` | `1` | |
| `PARA_STRIP_PLOT_AXIS_PREFIX` | `1` | |
| `PARA_MERGE_SPLITS` | `1` | |
| `PARA_FORMULA_PLACEHOLDER` | `[MATH]` | |
| `RUN_MAX_PARAGRAPHS_PER_ITEM` | `100` | |
| `RUN_REPAIR_BROKEN_ANNOTATIONS` | `1` | |
| `RUN_DELETE_BROKEN_ANNOTATIONS` | `1` | |
| `LOG_LEVEL` | `INFO` | |
| `ANNOTATION_MODE` | `note` | `dev annotate --annotation-mode` では上書き可 |
