# #55 Evidence Check 実装計画

## 目的

AIが返した `evidence` が、実際にAIへ渡したページ本文に存在するかを照合し、
結果を測定出力へ残す。既存73件にも遡って適用し、照合できない件数を数える。

## 判断

- `missing` でも `found=false` には倒さない。リンク先など正当な不一致があり得るため、
  測定値を改変せず監査フラグとして保存する。
- 照合対象は、LLMへ実際に渡した範囲と同じにする。
  本体ページと `--follow` で追加したページを、それぞれ
  `MAX_TEXT_CHARS_PER_PAGE` まで含める。
- `found=false` の `evidence` は引用ではないため `not_applicable` とする。
- 既存出力は上書きせず、専用コマンドで照合結果を付加した派生JSONと集計を生成する。

## 実装

1. `extractor/extract.py`
   - 本体ページと追加ページから照合用本文を組み立てる
   - `items` に `evidence_check`、ページ全体に `evidence_summary` を保存する
2. `analysis/apply_evidence_check.py`
   - `extractor/out/*.json` とキャッシュ済みHTMLを対応づける
   - 既存出力を変更せず `analysis/out/evidence-checked/` へ派生JSONを出す
   - `analysis/out/evidence-check-summary.json` に件数を集計する
3. テスト
   - 本体ページ、リンク先、missing、キャッシュ欠損、`found=false` を固定する
   - 既存73件へ適用して件数を確認する
4. 文書
   - `STATUS.md` を現在地へ更新する
   - 必要なら `METHOD.md` とデータ辞書へ照合結果の意味を追記する

## 完了条件

- 新しい測定出力に項目別の照合結果が入る
- 既存73件のうち、照合対象数・verified・missing・too_short・キャッシュ欠損数が分かる
- 既存テストと追加テストがすべて通る

## 実施結果（2026-08-16）

- 新規抽出へ `evidence_check` / `evidence_summary` / 照合範囲を追加
- 既存73出力は上書きせず派生生成
- 到達71件、未到達2件、参照117 URLのキャッシュ欠損0
- 照合対象127項目: verified 104（exact 74 + normalized 30）/
  partial 23 / missing 0 / too_short 0
- `found=false` の157項目は not_applicable
- Node 78件＋Python 164件、計242件 PASS
