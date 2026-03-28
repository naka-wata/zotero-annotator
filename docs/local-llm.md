# ローカル LLM セットアップ

`TRANSLATOR_PROVIDER=local_llm` で Ollama などの OpenAI 互換ローカル LLM を使うためのセットアップ手順です。初回セットアップ全体は [セットアップ](setup.md)、`.env` の各項目は [設定](configuration.md) を参照してください。

## 共通の注意

- `LOCAL_LLM_BASE_URL` は OpenAI 互換の `/v1` エンドポイントが必要です。Ollama の場合は `http://localhost:11434/v1` を使ってください（`http://localhost:11434` ではありません）。
- 標準例は `qwen2.5:7b-instruct` ですが固定ではありません。pull 済みの別モデルに置き換えて構いません。
- `LOCAL_LLM_TEMPERATURE` / `LOCAL_LLM_TOP_P` で生成挙動を調整できます。標準例では `0.1` / `0.9` を使います。

## Docker

リポジトリ直下の [compose.yaml](../compose.yaml) を使う標準構成です。`ollama-data` volume を使うので、pull 済みモデルは再起動後も保持されます。

1. Ollama サーバーを起動します。

```bash
docker compose up -d ollama
```

2. 初回だけ標準例のモデルを pull します。

```bash
docker compose --profile init up ollama-pull
```

3. `.env` をローカル LLM 用に設定します。

```dotenv
TRANSLATOR_PROVIDER=local_llm
LOCAL_LLM_BASE_URL=http://localhost:11434/v1
LOCAL_LLM_MODEL=qwen2.5:7b-instruct
LOCAL_LLM_TEMPERATURE=0.1
LOCAL_LLM_TOP_P=0.9
```

## macOS ローカル

Docker を使わず、macOS 上で Ollama を直接起動する構成です。Docker を挟むより起動が速く、オーバーヘッドも少ないため、macOS ではこちらを優先することを勧めます。

1. Ollama app を起動するか、ターミナルで `ollama serve` を実行します。

```bash
ollama serve
```

2. 標準例のモデルを pull します。

```bash
ollama pull qwen2.5:7b-instruct
```

3. `.env` は Docker 版と同じ設定を使います。

```dotenv
TRANSLATOR_PROVIDER=local_llm
LOCAL_LLM_BASE_URL=http://localhost:11434/v1
LOCAL_LLM_MODEL=qwen2.5:7b-instruct
LOCAL_LLM_TEMPERATURE=0.1
LOCAL_LLM_TOP_P=0.9
```

## 別モデルを使う場合

`translategemma:4b` など別モデルを試したい場合は、モデルを pull して `LOCAL_LLM_MODEL` を差し替えます。既存モデルを消す必要はありません。

Docker 版:

```bash
docker compose up -d ollama
docker compose exec ollama ollama pull translategemma:4b
```

macOS ローカル版:

```bash
ollama pull translategemma:4b
```

`.env` 例:

```dotenv
TRANSLATOR_PROVIDER=local_llm
LOCAL_LLM_BASE_URL=http://localhost:11434/v1
LOCAL_LLM_MODEL=translategemma:4b
LOCAL_LLM_TEMPERATURE=0.1
LOCAL_LLM_TOP_P=0.9
```
