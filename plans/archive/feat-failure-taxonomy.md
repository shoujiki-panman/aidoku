# Failure Taxonomy を共通化する

Issue: #71

## 完了条件

8種の失敗分類を1か所で定義し、抽出結果と実験結果の既存語彙を機械的に再分類でき、既存データの分布を単位別に再生成できる。

## 判断基準

- 「ページに書かれていない」`fact_missing` と「書かれた場所を読めなかった」`not_retrieved` を混ぜない。
- 入口から対象ページ自体を見つけられない場合は `page_not_discoverable` とする。
- LLMの日本語理由は監査用に残し、共通の `failure_type` はコードで決定する。
- 未知の語彙は推測せずエラーにする。
- 抽出項目、抽出実行、実験ケース、実験試行は分母が違うため、分布を別々に出す。

## 実装

1. `docs/failure-taxonomy.md` に8種の定義、判定条件、優先順位、既存語彙の対応表を書く。
2. `failure_taxonomy.py` に8種の定数と、既存語彙を厳密に変換するPure Functionを置く。
3. 新しい抽出結果の各失敗項目へ、既存 `failure_reason` に加えて `failure_type` を記録する。
4. `analysis/failure_distribution.py` で既存の `extractor/out`、`experiment/cases`、`experiment/out` を再分類する。
5. `analysis/out/failure-taxonomy-summary.json` に単位別の分布を保存する。
6. README・STATUSを新しい契約と実測分布へ同期する。

## テスト

- 8種の語彙と順序を固定する。
- 既存の日本語5種、内部失敗2種、実験側1種を全件マッピングする。
- 未知語彙、型違い、矛盾したfound状態を拒否する。
- 新規の成功・失敗・到達失敗結果に `failure_type` が正しく入る。
- 一時fixtureで各集計単位と0件の分類を含む分布を確認する。
- 既存データ再集計値を回帰テストで固定する。
- 全Python・Nodeテスト、`py_compile`、`git diff --check` を通す。

## 既存データの基準値（実装前に一次データから確認）

- 抽出結果: 73ファイル。到達71実行、未到達2実行。到達分は284項目、整合した失敗157項目。
- 抽出側の整合した旧理由: `記載なし` 132、`曖昧` 11、`リンク先にあり` 9、`PDF内のみ` 3、`電話でのみ確認可` 2。
- 旧契約の矛盾が2項目ある。`found=true` と `failure_reason=曖昧`、`found=true` と `failure_reason=記載なし` が各1件。成功にも失敗にも推測で寄せず別枠にする。
- 実験結果: 1ファイル、60項目、失敗20項目（`記載なし` 16、`リンク先にあり` 4）。
- 実験ケース: 1件、旧分類 `target_page_unreachable_from_index` 1件。

数が変わった場合は、データ追加か集計退行かを確認してから期待値を更新する。

## 検証結果

- Python 285件 PASS（root 80 / analysis 42 / crawler 49 / experiment 6 / extractor 50 / gennai_app 41 / scorer 17）
- Node 78件 PASS（local 11 / worker 23 / nlweb 20 / mcp 24）
- 合計363件 PASS
- `py_compile`、`git diff --check`、競合マーカー、末尾空白の確認に問題なし
- Failure Taxonomy集計を一時出力へ再生成し、追跡中JSONとbyte一致
- 公開3手続きのdashboard JSONを既存生成時刻で再生成し、3件ともbyte一致
