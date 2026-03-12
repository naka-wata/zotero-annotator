# Local LLM Setup

`TRANSLATOR_PROVIDER=local_llm` で Ollama などの OpenAI 互換 local LLM を使うためのセットアップ手順です。  
標準例では `qwen2.5:7b-instruct` を使いますが、pull 済みの別 model に置き換えて構いません。

## `translategemma:4b` を使う場合

`translategemma:4b` を試したい場合は、qwen の代わりにこの model を pull して `LOCAL_LLM_MODEL` を差し替えます。  
現在の標準 compose 設定は `qwen2.5:7b-instruct` を pull するので、`translategemma:4b` は追加で明示的に pull してください。

Docker 版:

```bash
docker compose up -d ollama
docker compose exec ollama ollama pull translategemma:4b
```

macOS local 版:

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

補足:

- `translategemma:4b` を使う場合も `LOCAL_LLM_BASE_URL` は `/v1` 付きで設定します。
- `LOCAL_LLM_TEMPERATURE=0.1` / `LOCAL_LLM_TOP_P=0.9` はそのまま試して問題ありません。
- 既存の `qwen2.5:7b-instruct` を消す必要はありません。`LOCAL_LLM_MODEL` を切り替えるだけで使い分けできます。

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
LOCAL_LLM_TEMPERATURE=0.1
LOCAL_LLM_TOP_P=0.9
```

注意:

- `LOCAL_LLM_BASE_URL` は OpenAI 互換の `/v1` endpoint が必要です。`http://localhost:11434` ではなく `http://localhost:11434/v1` を使ってください。
- `qwen2.5:7b-instruct` は標準例であり固定ではありません。別 model を使う場合は pull 済み名を `LOCAL_LLM_MODEL` に設定してください。
- `LOCAL_LLM_TEMPERATURE` / `LOCAL_LLM_TOP_P` で local LLM の生成挙動を調整できます。標準例では Qwen 向けに `0.1` / `0.9` を使います。

## macOS local

Docker を使わず、macOS 上で Ollama を直接起動する構成です。
macOS では一般に、Docker を挟むより `Ollama app` または `ollama serve` を直接使う方が起動が速く、オーバーヘッドも少ないため、こちらを優先することを勧めます。

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
LOCAL_LLM_TEMPERATURE=0.1
LOCAL_LLM_TOP_P=0.9
```

注意:

- `LOCAL_LLM_BASE_URL` は `/v1` 付きで設定してください。Ollama の OpenAI 互換 endpoint を使うため、`http://localhost:11434/v1` が必要です。
- `qwen2.5:7b-instruct` は標準例であり固定ではありません。利用したい別 model を pull したうえで `LOCAL_LLM_MODEL` を差し替えてください。
- `LOCAL_LLM_TEMPERATURE` / `LOCAL_LLM_TOP_P` は local LLM の生成挙動調整用です。標準例では Qwen 向けに `0.1` / `0.9` を使います。
- macOS では Docker 版よりこの `macOS local` 構成の方が軽く、初回確認も速いことが多いです。
