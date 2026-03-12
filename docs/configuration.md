# Configuration

このドキュメントは `.env` の説明場所です。利用可能なキー名と例示値・既定値は [../.env.example](../.env.example) を正本として扱います。設定を追加・変更する場合は、まず `.env.example` を更新してください。

## Basic rules

- `.env` はリポジトリ直下に置きます
- 推奨手順は `cp .env.example .env` です
- 実装は `.env` を自動で読み込みます
- 使っていない provider の項目は `.env.example` の placeholder のままで構いません
- `TRANSLATOR_PROVIDER=openai` は `chatgpt` の後方互換 alias として扱われます

## Common required settings

以下は provider に関係なく必要です。

| Key | Purpose |
| --- | --- |
| `Z_SCOPE` | Zotero の対象種別です。`user` または `group` を指定します。 |
| `Z_ID` | Zotero の user ID または group ID です。 |
| `Z_API_KEY` | Zotero API key です。 |
| `TRANSLATOR_PROVIDER` | 翻訳 provider を選びます。`deepl` / `chatgpt` / `local_llm` を使います。 |
| `TARGET_LANG` | 翻訳先言語です。 |

共通の任意項目:

| Key | Purpose |
| --- | --- |
| `SOURCE_LANG` | 翻訳元言語を固定したい場合に指定します。未設定時は provider 側の自動判定を使います。 |

## Provider settings

### DeepL

必須:

| Key | Purpose |
| --- | --- |
| `DEEPL_API_KEY` | DeepL API key です。 |

任意:

| Key | Purpose |
| --- | --- |
| `DEEPL_API_URL` | DeepL endpoint を切り替えます。Pro を使う場合は `.env.example` のコメントにある URL に変更します。 |

最小例:

```dotenv
TRANSLATOR_PROVIDER=deepl
TARGET_LANG=JA
DEEPL_API_KEY=your_deepl_api_key_here
```

### ChatGPT API

必須:

| Key | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | OpenAI API key です。 |
| `OPENAI_MODEL` | 使用する model 名です。 |

任意:

| Key | Purpose |
| --- | --- |
| `OPENAI_BASE_URL` | OpenAI 互換 endpoint を使う場合に切り替えます。公式 API のままなら `.env.example` の既定値を使います。 |

最小例:

```dotenv
TRANSLATOR_PROVIDER=chatgpt
TARGET_LANG=JA
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-4o-mini
```

### Local LLM

必須:

| Key | Purpose |
| --- | --- |
| `LOCAL_LLM_BASE_URL` | OpenAI 互換 endpoint の base URL です。Ollama を使う場合は `/v1` 付き URL を指定します。 |
| `LOCAL_LLM_MODEL` | 利用する local model 名です。 |

任意:

| Key | Purpose |
| --- | --- |
| `LOCAL_LLM_API_KEY` | OpenAI 互換 server が API key を要求する場合に使います。 |
| `LOCAL_LLM_TEMPERATURE` | 生成温度です。 |
| `LOCAL_LLM_TOP_P` | `top_p` です。 |

最小例:

```dotenv
TRANSLATOR_PROVIDER=local_llm
TARGET_LANG=JA
LOCAL_LLM_BASE_URL=http://localhost:11434/v1
LOCAL_LLM_MODEL=qwen2.5:7b-instruct
```

Ollama の起動手順や model の例は [local-llm.md](local-llm.md) を参照してください。

## Optional workflow settings

以下はタグ運用を調整したい場合だけ変更します。実際の既定値は [../.env.example](../.env.example) を参照してください。

| Key | Purpose |
| --- | --- |
| `Z_TARGET_TAG` | `search` / `run` / `base` が通常フローで参照する対象 item tag です。 |
| `Z_DONE_TAG` | `translate --write` 成功後に付ける item tag です。 |
| `Z_REMOVE_TAG` | `base --write` 完了時に外す item tag です。 |
| `Z_BASE_DONE_TAG` | `base --write` 完了後、または `translate` の入力集合として使う item tag です。 |
| `ANN_PENDING_TRANSLATION_TAG` | 未翻訳 annotation を示す annotation-level tag です。 |
| `ANN_TRANSLATED_TAG` | 翻訳済み annotation を示す annotation-level tag です。 |

## Optional extraction settings

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

## Fixed in code

以下は現在 `.env` では変更できません。

- `PARA_CONNECTOR_MAX_CHARS`
- `PARA_MATH_NEWLINES`
- `PARA_STRIP_PLOT_AXIS_PREFIX`
- `PARA_MERGE_SPLITS`
- `PARA_FORMULA_PLACEHOLDER`
- `RUN_MAX_PARAGRAPHS_PER_ITEM`
- `RUN_REPAIR_BROKEN_ANNOTATIONS`
- `RUN_DELETE_BROKEN_ANNOTATIONS`
- `LOG_LEVEL`
- `ANNOTATION_MODE`
