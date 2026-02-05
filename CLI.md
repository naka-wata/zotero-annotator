# CLI Specification

このファイルは `zotero-annotator` のCLI仕様（コマンドとオプション）をまとめたメモです。

## コマンド一覧

### `zotero-annotator run`

タグ付き論文を処理して、Zotero PDFへ annotation を追加します。

**主な用途**
- 通常運用（翻訳あり）
- 必要に応じて翻訳なしで疎通確認（`--no-translate`）

**基本挙動**
- デフォルトの対象タグは `.env` の `Z_TARGET_TAG`（例: `to-translate`）
- `--tag` で一時的に上書き可能
- `--max-items` で1回の処理本数を制限

**書き込み制御（重要）**
- `--read-only`：Zoteroへの書き込み（注釈作成/タグ更新）を行わない  
  - ただし、取得・解析・重複判定・注釈payload生成までは行う
- `--write`：Zoteroへ実際に書き込む

**オプション**
- `--tag TEXT`：対象タグ上書き（例: `to-translate`）
- `--max-items INT`：処理する論文数の上限
- `--read-only/--write`：書き込みの有無
- `--no-translate`：翻訳を行わず、原文のまま注釈を作る（開発/疎通確認用）
- `--dump-payloads PATH`：`--read-only` 時に「送信予定の注釈payload(JSON)」をファイル出力

**タグ更新（自動）**
- `--write` 実行時、全段落の `para:<hash>` が揃ったと判定できた場合のみ、自動で `Z_REMOVE_TAG` を削除し `Z_DONE_TAG` を追加します。

**例**
```bash
# read-only（安全確認）
zotero-annotator run --read-only --tag to-translate --max-items 1

# read-only + payload出力（送信内容を目視確認）
zotero-annotator run --read-only --tag to-translate --max-items 1 --dump-payloads payloads.json

# 実行（Zoteroに書き込み）
zotero-annotator run --write --tag to-translate --max-items 1

# 開発用：翻訳なしで注釈が作れるかの疎通
zotero-annotator run --no-translate --write --tag to-translate --max-items 1
```

---

### `zotero-annotator search`

指定タグが付いた論文（親アイテム）の件数を数えます（書き込みなし）。

**オプション**
- `--tag TEXT`：対象タグ上書き（例: `to-translate`）

**例**
```bash
zotero-annotator search --tag to-translate
```

---

## 今後追加予定（案）

### `zotero-annotator dev ...`（開発用コマンド群）

パイプラインを分解して検証しやすくするためのコマンド群です。特に「段落1つだけ書き込む」「位置が正しいか確認する」を想定します。

#### `dev items`（read-only）
- タグ付き親アイテムの一覧/件数を出力（書き込みなし）
- 主なオプション：`--tag`, `--max-items`, `--json`

例:
```bash
zotero-annotator dev items --tag to-translate --max-items 20
```

#### `dev children`（read-only）
- `--item-key` を指定して children（添付一覧）を出力（PDF添付があるか確認）

例:
```bash
zotero-annotator dev children --item-key ABCD1234
```

#### `dev pdf`（read-only）
- `--item-key` を指定してPDF添付をダウンロードし保存
- 主なオプション：`--out paper.pdf`

例:
```bash
zotero-annotator dev pdf --item-key ABCD1234 --out paper.pdf
```

#### `dev grobid`（read-only）
- PDF→TEI(XML)を取得して保存（位置情報付きTEIの確認）
- 入力はどちらか：`--item-key` / `--pdf`
- 主なオプション：`--out tei.xml`

例:
```bash
zotero-annotator dev grobid --item-key ABCD1234 --out tei.xml
```

#### `dev paragraphs`（read-only）
- TEI(XML)→段落抽出（text/hash/pageIndex/bbox）をJSONで保存
- 主なオプション：`--tei tei.xml`, `--out paragraphs.json`

例:
```bash
zotero-annotator dev paragraphs --tei tei.xml --out paragraphs.json
```

#### `dev annotate`（read-only / write）
- 翻訳なしで注釈を作成し、位置が正しいかを検証
- デフォルトは `annotationType="note"` + `annotationPosition`（n8n/Work.json互換）
- 「左の小矩形」は 12x12 固定（n8n互換）

主なオプション:
- `--item-key KEY`（必須）
- `--paragraph-index INT`：0始まりで段落を1つ指定（位置検証の最重要オプション）
- `--max-paragraphs INT`：複数作成する場合の上限（未指定なら全段落）
- `--read-only/--write`：書き込みの有無
- `--dump-payloads PATH`：送信予定payloadをJSON出力（read-only時のみ）

例:
```bash
# 0番の段落だけ、payloadを確認（書き込みなし）
zotero-annotator dev annotate --item-key ABCD1234 --paragraph-index 0 --read-only --dump-payloads payloads.json

# 0番の段落だけ、実際に書き込む（位置の目視確認）
zotero-annotator dev annotate --item-key ABCD1234 --paragraph-index 0 --write
```

#### `dev annotations`（read-only）
- 既存annotationを一覧出力（`para:<hash>` の重複判定確認）
- 主なオプション：`--pdf-key KEY`

例:
```bash
zotero-annotator dev annotations --pdf-key EFGH5678
```
