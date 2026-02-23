# 今日のTODO

## 目標
- `run --item-key` で指定した論文を、Zotero 7 で安定して annotation 作成できる状態にする（必要なら翻訳）。

## 現状の問題
1. ☑ DeepL認証仕様変更対応:
   - DeepLの header-based auth に切り替え済み。
2. ☑ Zotero 7 側エラー対策（sortIndex NOT NULL）:
   - note 注釈に `annotationSortIndex` / `annotationPosition` / `annotationPageLabel` を付与。
3. ☑ 注釈一覧のページング不足:
   - APIのデフォルト25件で止まっていたため、dedup/監査が誤っていた。ページング対応済み。
4. ⬜ 失敗時ポリシー/再実行性:
   - 途中失敗や部分成功が起きた時に、原因の可視化と再実行の手順をさらに明確化したい。
5. ⬜ 2段組PDFの読み順:
   - 段落順はGROBIDのTEI順に依存するため、論文によっては左右段が混ざる可能性がある。

## 今日の計画（この順で実施）
1. ☑ 翻訳インターフェースの導入
   - `services/translators/base.py` / `factory.py` / `deepl.py` を追加。
2. ☑ `pipeline.py` に翻訳呼び出しを接続
   - `translator.translate()` の結果を annotation コメントに反映。
3. ☑ `run` で「翻訳なし」確認モードを追加
   - `run --no-translate` を追加し、API消費なしで書き込み検証可能にする。
4. ☑ 監査・修復系 dev コマンドを追加
   - `dev audit-annotations` / `dev repair-annotations` を追加。
5. ☑ 「壊れ注釈」削除の自動化
   - `RUN_DELETE_BROKEN_ANNOTATIONS` と `run --delete-broken` を追加。
6. ⬜ 失敗の可視化を強化
   - Zotero create の failed サンプル表示/再送ポリシーの調整（必要ならログ出力改善）。
7. ⬜ 2段組の検証を進める
   - `dev annotate` で段落を順に入れて、Zotero側で読み順/位置を目視確認。

## 次にやること
1. ⬜ OpenAI翻訳プロバイダを実装
   - `TRANSLATOR_PROVIDER=openai` を実装して factory に接続する。
2. ⬜ フォールバック連鎖を追加（任意）
   - 例: `TRANSLATOR_CHAIN=deepl,openai` のように失敗時に切替。
3. ⬜ 壊れ注釈の削除ポリシーを精緻化（任意）
   - 削除対象の条件をより安全に（例: `para:` タグあり/なし、annotationType限定、dry-run表示の拡充）。
4. ☑ ドキュメント同期
   - `CLI.md` などは現行実装に追随済み。
5. ☑ 数式トークンの可読性改善
   - `PARA_MATH_NEWLINES=1` で `[MATH] (n)` の前後に改行を挿入。
6. ☑ アルゴリズム段落のスキップ
   - `PARA_SKIP_ALGORITHMS=1` で `Algorithm 1 ...` の擬似コードブロックを除外。
7. ☑ 図中の軸ラベル除去
   - `PARA_STRIP_PLOT_AXIS_PREFIX=1` で `Figure N:` の直前に混入した数値列を除去。
8. ☑ 図表キャプションの抑制
   - `PARA_SKIP_CAPTIONS=1` で `Figure N:` / `Table N:` のキャプション段落をノート化しない。
9. ☑ 継続段落の結合
   - 図表削除後に小文字や `, ) ]` で始まる段落は、前段落末尾が文末（`.?!`）でなければ結合。
10. ☑ 注釈タイプの切替
   - `.env` の `ANNOTATION_MODE=note` / `# ANNOTATION_MODE=highlight` で note と highlight を切替可能にした。
   - highlightでも `annotationSortIndex` を必須付与してZotero 7のNOT NULLを回避。

## 完了条件
- `run --item-key ... --write --no-translate` で全段落の dedup タグが揃う。
- `dev audit-annotations` で `missing dedup tags filtered=0` になる。
- Zotero 7 の `NOT NULL constraint failed: itemAnnotations.sortIndex` が出ない。
- `--translate` 有効時も、翻訳失敗の原因が分かる形で停止/スキップできる。
