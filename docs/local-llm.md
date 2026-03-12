# ローカル LLM セットアップ

`TRANSLATOR_PROVIDER=local_llm` で Ollama などの OpenAI 互換ローカル LLM を使うためのセットアップ手順です。初回セットアップ全体は [セットアップ](setup.md)、`.env` の各項目は [設定](configuration.md) を参照してください。  
標準例では `qwen2.5:7b-instruct` を使いますが、pull 済みの別モデルに置き換えて構いません。

## `translategemma:4b` を使う場合

`translategemma:4b` を試したい場合は、qwen の代わりにこのモデルを pull して `LOCAL_LLM_MODEL` を差し替えます。  
現在の標準 compose 設定は `qwen2.5:7b-instruct` を pull するので、`translategemma:4b` は追加で明示的に pull してください。

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

補足:

- `translategemma:4b` を使う場合も `LOCAL_LLM_BASE_URL` は `/v1` 付きで設定します。
- `LOCAL_LLM_TEMPERATURE=0.1` / `LOCAL_LLM_TOP_P=0.9` はそのまま試して問題ありません。
- 既存の `qwen2.5:7b-instruct` を消す必要はありません。`LOCAL_LLM_MODEL` を切り替えるだけで使い分けできます。

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

注意:

- `LOCAL_LLM_BASE_URL` は OpenAI 互換の `/v1` エンドポイントが必要です。`http://localhost:11434` ではなく `http://localhost:11434/v1` を使ってください。
- `qwen2.5:7b-instruct` は標準例であり固定ではありません。別モデルを使う場合は pull 済み名を `LOCAL_LLM_MODEL` に設定してください。
- `LOCAL_LLM_TEMPERATURE` / `LOCAL_LLM_TOP_P` でローカル LLM の生成挙動を調整できます。標準例では Qwen 向けに `0.1` / `0.9` を使います。

## macOS ローカル

Docker を使わず、macOS 上で Ollama を直接起動する構成です。
macOS では一般に、Docker を挟むより `Ollama app` または `ollama serve` を直接使う方が起動が速く、オーバーヘッドも少ないため、こちらを優先することを勧めます。

1. Ollama app を起動するか、ターミナルで `ollama serve` を実行してサーバーを立ち上げます。

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

注意:

- `LOCAL_LLM_BASE_URL` は `/v1` 付きで設定してください。Ollama の OpenAI 互換エンドポイントを使うため、`http://localhost:11434/v1` が必要です。
- `qwen2.5:7b-instruct` は標準例であり固定ではありません。利用したい別モデルを pull したうえで `LOCAL_LLM_MODEL` を差し替えてください。
- `LOCAL_LLM_TEMPERATURE` / `LOCAL_LLM_TOP_P` はローカル LLM の生成挙動調整用です。標準例では Qwen 向けに `0.1` / `0.9` を使います。
- macOS では Docker 版よりこの `macOS ローカル` 構成の方が軽く、初回確認も速いことが多いです。
