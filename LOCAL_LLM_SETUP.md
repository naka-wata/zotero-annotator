# Local LLM Setup

`TRANSLATOR_PROVIDER=local_llm` で Ollama などの OpenAI 互換 local LLM を使うためのセットアップ手順です。  
標準例では `qwen2.5:7b-instruct` を使いますが、pull 済みの別 model に置き換えて構いません。

## Docker

リポジトリ直下の [compose.yaml](/Users/watarunakamura/Desktop/zotero-annotator/compose.yaml) を使う標準構成です。`ollama-data` volume を使うので、pull 済み model は再起動後も保持されます。

1. Ollama server を起動します。

```bash
docker compose up -d ollama
```

2. 初回だけ標準例の model を pull します。

```bash
docker compose --profile init up ollama-pull
```

3. `.env` を local provider 用に設定します。

```dotenv
TRANSLATOR_PROVIDER=local_llm
LOCAL_LLM_BASE_URL=http://localhost:11434/v1
LOCAL_LLM_MODEL=qwen2.5:7b-instruct
```

注意:

- `LOCAL_LLM_BASE_URL` は OpenAI 互換の `/v1` endpoint が必要です。`http://localhost:11434` ではなく `http://localhost:11434/v1` を使ってください。
- `qwen2.5:7b-instruct` は標準例であり固定ではありません。別 model を使う場合は pull 済み名を `LOCAL_LLM_MODEL` に設定してください。

## macOS local

Docker を使わず、macOS 上で Ollama を直接起動する構成です。

1. Ollama app を起動するか、ターミナルで `ollama serve` を実行して server を立ち上げます。

```bash
ollama serve
```

2. 標準例の model を pull します。

```bash
ollama pull qwen2.5:7b-instruct
```

3. `.env` は Docker 版と同じ設定を使います。

```dotenv
TRANSLATOR_PROVIDER=local_llm
LOCAL_LLM_BASE_URL=http://localhost:11434/v1
LOCAL_LLM_MODEL=qwen2.5:7b-instruct
```

注意:

- `LOCAL_LLM_BASE_URL` は `/v1` 付きで設定してください。Ollama の OpenAI 互換 endpoint を使うため、`http://localhost:11434/v1` が必要です。
- `qwen2.5:7b-instruct` は標準例であり固定ではありません。利用したい別 model を pull したうえで `LOCAL_LLM_MODEL` を差し替えてください。
