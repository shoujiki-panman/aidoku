# 4判定 Evaluator を公開値へ接続する

Issue: #70

## 完了条件

回答・根拠・Ground Truth の4判定を1つの契約で記録し、公開値が
`found=true` だけで20点にならず、未判定は「未検証」と表示される。

## 判断基準

- `pass` / `fail` / `not_checked` / `not_applicable` を混ぜない。
- 必要な判定が1つでも `not_checked` なら、点数を付けない。
- `found` は「AIが回答を返した」という観測値であり、正解の証明には使わない。
- Evidenceの実在は文字列照合、回答を支えるかは意味関係なのでLLM、
  Ground Truthとの一致は人手で固定した必須要素で判定する。
- Ground Truthが無い自治体・手続きは推測せず `not_checked` にする。
- 旧公開値は削除せず、回答内容の観測値として残す。検証済み点数とは分離する。

## 4判定

1. `answer_correct` — 情報の有無について、AIの回答状態がGround Truthと一致するか。
2. `evidence_exists` — 引用が、そのTest CaseでAIへ渡した本文に実在するか。
3. `evidence_supports_answer` — 引用の内容が、AIの回答を実際に支えているか。
4. `ground_truth_matches` — 回答が人手で固定した必須要素を満たすか。

`answer_correct` は情報の有無、`ground_truth_matches` は回答内容を判定するため、
両方を残す。情報が無いことが正解の場合、Evidenceの2判定は
`not_applicable`、残る2判定が `pass` なら全体を `pass` とする。

## 実装

1. `evaluator.py`
   - 4状態と4判定名を固定する。
   - 各判定を小さなPure Functionに分け、全体判定と配点を機械的に決める。
   - 不明な語彙・型・矛盾は例外にし、合格へ丸めない。
2. `scorer/`
   - 既存の1回のLLM判定で、必須要素の充足に加えてEvidence支持を返す。
   - 4判定と全体判定を各fieldへ保存する。
3. `analysis/export_dashboard.py`
   - `found` 直結の配点を廃止する。
   - Evaluatorの `overall=pass` だけ20点、`fail` は0点、
     `not_checked` はnullとする。
   - scorer結果が無い、または旧形式なら未検証にする。
4. `web/`
   - 回答の実測表示と、検証済み点数を分ける。
   - nullを0点や不正解として見せず「未検証」と表示する。
5. `experiment/run.py`
   - 既存Ground Truth照合を同じEvaluator契約で出力する。
6. README・METHOD・STATUS・公開データの定義を同期する。

## テスト

- 4判定名、4状態、優先順位を固定する。
- true/false/None、未知値、型違い、矛盾を網羅する。
- Evidence Checkのexact/normalized/partial/missing/not_checkedを全件確認する。
- Ground Truthあり・なし、記載あり・なし、部分正解を確認する。
- LLM応答の要素数・順序・ID・yes/no・Evidence支持値を厳格に検証する。
- `found=true` だけでは公開点が付かない回帰テストを書く。
- `pass=20`、`fail=0`、未検証=nullを固定する。
- 公開画面がnullを「0点」「読めない」と表示しないことをNodeテストで固定する。
- 源内向けAPIも回答観測と正解点を分け、Ground Truth無しでは「未検証」と表示する。
- 全Python・Nodeテスト、`py_compile`、`git diff --check`を通す。

## 既存データの扱い

現在の公開69マスはGround Truthが揃っていない。`scorer/golden/tennyu.csv` に
あるのは転入届3自治体だけで、既存の `scorer/out` もEvidence支持を記録していない。
このため既存値を推測で検証済みに昇格せず、再評価するまでは未検証とする。
