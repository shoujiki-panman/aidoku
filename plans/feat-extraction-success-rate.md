# #57 本番抽出を複数回測定する計画

## 完了条件

`extractor/extract.py --trials 5`で、項目ごとに5回中何回`found=true`だったかを
記録し、公開JSONへ同じ分子・分母を運べる。既定1回と既存の採点方法は変えない。

## 判断基準

- success rateは値を抽出できた割合であり、答えの正しさではない。
- 1回ごとの結果を消さず、1から始まる`run_number`で追跡できるようにする。
- 分母は全項目で揃える。欠落や型違いを0回へ丸めない。
- 途中で例外が起きた測定を、少ない分母の完成結果として公開しない。
- 従来の`items`と点数は最後の試行を使い、多数決で意味を変えない。
- 旧結果は実際に1回測定しているため、1回中1回または0回として公開する。
- 実測対象はIssue指定の段差6件に絞り、69マスを一度に回さない。

## 出力契約

- `trial_count`: 試行数
- `trials[]`: 各1回分の従来結果と`run_number`
- `success_rate.{項目}.successful_runs`: `found=true`の回数
- `success_rate.{項目}.total_runs`: 全試行数
- `success_rate.{項目}.rate`: 小数4桁までの割合
- 公開JSONの`municipalities[].fields[].success_rate`: 同じ分子・分母・割合

## 実装

1. 集約と成功率計算を小さなPure Functionへ分離する。
2. `extract.py`へ既定1の`--trials`を追加する。
3. 全試行が成功してから、既存のatomic batch writeで出力する。
4. CLIに項目ごとの「全何回中、成功何回」を表示する。
5. `export_dashboard.py`で新結果を検証して公開JSONへ運ぶ。
6. README、METHOD、STATUS、公開データ説明を同期する。

## 呼び出し数

Issue #68以降、ページへ到達できた1試行は4 fact_typeとonline clarityの5 LLM call。
段差6件がすべて到達済みなら5試行で150 call、69マスがすべて到達済みなら
1,725 callになり、リンク追従時は増える。到達失敗ではLLMを呼ばないため、実数は
到達結果で変わる。この変更では実AI測定を勝手に実行しない。

## テスト

- 1回、3回、成功0回、全回成功、項目ごとの結果差を確認する。
- run_numberの連番、入力非破壊、最後の試行との後方互換を確認する。
- 0、負数、bool、小数、文字列の試行数を拒否する。
- 空配列、試行型違い、items欠落、found型違いを拒否する。
- 途中試行の例外で既存出力を変更しない。
- 公開JSONで旧1回測定と新しい複数回測定を扱う。
- 分子・分母・割合・root trial_countの矛盾を拒否する。
- 全Python・Nodeテスト、py_compile、git diff --checkを通す。

## 検証結果

- Python 300件 PASS（root 81 / analysis 47 / crawler 49 / experiment 6 / extractor 59 / gennai_app 41 / scorer 17）
- Node 78件 PASS（local 11 / worker 23 / nlweb 20 / mcp 24）
- 合計378件 PASS
- py_compile、git diff --check、競合マーカー確認に問題なし
- 既存公開69件へ1回測定の分子・分母を追加し、点数・判定・実文・集計など既存値は変更していない
- `--trials 3`の一時出力でrun_number 1〜3と全項目0/3を確認した
- 実AIの複数回測定は0件。コード契約は検証済みだが、実際のぶれ幅はまだ分からない
