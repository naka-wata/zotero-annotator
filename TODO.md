# 今日のTODO

## 目標
- 1段落だけをZoteroにannotationとして書き込み、位置を調整できる状態にする。

## 現状の問題
1. 🟨 実行環境の問題:
   - `ModuleNotFoundError: zotero_annotator` は一部手順で再発するため、安定運用手順を確定する必要がある。
2. ✅ CLIとドキュメントの不一致:
   - オプション表記と実装の差分が再発しないよう、更新時にREADME/CLI仕様を同時更新する。
3. ✅ 設定依存の強さ:
   - `CoreSettings` と `TranslationSettings` に分離し、翻訳なし実行でGemini必須を回避済み。

## 今日の計画（この順で実施）
1. ✅ `dev annotate` の実行経路を確保する
   - まずは1段落検証パスを確実に実行できる状態にする。
   - 実施済み: `dev annotate` の入力チェック強化、段階別エラー表示、read-only/write責務の固定。
2. ✅ 事前の疎通確認を行う
   - GROBIDに接続できることを確認する。
   - 対象ZoteroアイテムにPDF子アイテムがあることを確認する。
3. ✅ read-onlyでpayloadを確認する
   - `paragraph_index=0` を使う。
   - `annotationPosition` と `annotationSortIndex` を目視確認する。
4. ✅ 1段落だけwrite実行する
   - 同じ入力でannotationを1件だけ実際に作成する。
5. ✅ 重複防止を確認する
   - 同条件で再実行し、重複がスキップされることを確認する。

## 次にやること
1. ⬜ annotationの位置ズレ補正
   - note矩形(12x12)の基準点・y方向補正を調整する。
2. ✅ `dev items` 表示改善の反映確認
   - `item-key / title / tags` の色付き表示が実行時に反映されることを確認する。
3. ⬜ ドキュメント更新
   - 実際に安定して動く実行手順を `README.md` / `CLI.md` に反映する。

## 完了条件
- ✅ note annotationが1件、作成できる。
- ✅ 同じ段落を再実行しても重複annotationが作成されない。
- ⬜ 位置ズレが解消され、狙った位置に表示される。
