# #69 回答にconfidenceとevidence_locationを追加する計画

## 完了条件

新しいAI回答に`confidence`と`evidence_location`を必須で記録し、欠落・型違い・
状態矛盾を保存前に拒否できる。既存結果と採点方法は変えない。

## 判断基準

- `confidence`はAI自身の申告値であり、正解率ではない。
- `confidence`は0以上1以下の有限な数値だけを受理する。真偽値や文字列は数値扱いしない。
- `found=true`では引用と引用箇所を必須にする。
- `found=false`では引用箇所を`null`にする。
- AIを呼ばない到達失敗や添付ファイル判定では、AIの申告値を捏造せず両項目を`null`にする。
- 既存出力には測定していない値を埋めない。
- `confidence`を採点に使うかは、このIssueでは決めない。現行の採点には使わない。

## 実装

1. `extractor/prompt.md`へ両項目の形式と意味を追加する。
2. `normalize_item()`で両項目を正規化し、状態を厳密に検証する。
3. Test Case、attempt、後方互換`items`へ値をそのまま残す。
4. AIを呼ばない内部結果には、両項目を`null`で明記する。
5. README、METHOD、STATUSへ契約と非採点方針を記録する。

## テスト

- 0、1、小数のconfidenceを受理し、floatへ正規化する。
- 欠落、null、真偽値、文字列、負数、1超、NaN、正負の無限大を拒否する。
- `found=true`で引用箇所が無い場合を拒否する。
- `found=false`で引用箇所がある場合を拒否する。
- 初回・リンク追従後の結果と後方互換`items`に両項目が残る。
- 到達失敗・添付ファイル判定では両項目が`null`になる。
- 既存の採点・集計・画面の入力互換を保つ。
- 全Python・Nodeテスト、`py_compile`、`git diff --check`を通す。

## 既存データ

既存の抽出結果は、この契約を追加する前に作られたため両項目を持たない。
過去のAIの確信度や引用箇所を後から推測せず、そのまま残す。

## 検証結果

- Python 292件 PASS（root 80 / analysis 42 / crawler 49 / experiment 6 / extractor 56 / gennai_app 41 / scorer 18）
- Node 78件 PASS（local 11 / worker 23 / nlweb 20 / mcp 24）
- 合計370件 PASS
- `py_compile`と`git diff --check`に問題なし
- 既存抽出結果73件には両項目が0件であることを確認し、ファイルは変更していない
- confidenceが0と1のどちらでも採点結果が同じであることをテストで固定した
- 新契約での実AI回答はまだ0件。保存・拒否の契約は検証済みだが、AIが返す値の品質は未確認
