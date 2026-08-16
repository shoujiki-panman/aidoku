# #68 Test Caseをfact_type単位に分ける計画

## 目的

4項目を1回のLLM応答へまとめず、項目ごとに独立した質問・呼び出し・成否を
記録できるようにする。

## 判断

- **1回のLLM呼び出しには1 fact_typeだけ**を入れる（4項目batchにしない）。
- 通常は1 Test Case = 1 attempt。`--follow`でその項目が「リンク先にあり」と返した
  場合だけ、同じTest Caseをリンク先本文つきでもう1 attempt実行する。各callの結果は
  `attempts[]`に残すため、呼出回数や上書き前の判定を隠さない。追従先がPDF等だと
  取得後に判明した場合は`llm_called: false`の観測attemptとして区別する。
- まとめたプロンプトでは、追加した語が別項目の判定へ漏れる副作用を実測済みのため、
  呼び出し回数より独立性を優先する。
- 公開画面が読む既存の`items`形式は残し、新しいTest Case記録から機械的に作る。

## データ契約

- Test Caseは次の4項目を必須にする。
  - `service`: 手続きID
  - `fact_type`: `fact_types.json`のID
  - `question`: 自治体・手続き・fact_typeを含む1項目だけの質問
  - `test_case_version`: 質問集合の版
- `crawler/targets.json`は、手続き単位の測定用`question`を廃止する。
  - 測定対象は`fact_types`のIDで持つ。
  - 画面表示用の従来文は`display_question`として区別する。
  - `test_case_version`をトップレベルに置く。
- 中央4 fact_typeの対象外である避難所は`fact_types: []`とし、対象外を暗黙に
  4項目へ当てはめない。

## 実装

1. 小さな`TestCase`データ型と、targets/fact_typesからの生成・検証関数を作る。
2. extractorのプロンプトを1項目用に変え、Test Caseごとに独立して呼ぶ。
3. `--follow`はTest Caseごとに最大2リンクを追い、そのTest Caseだけを2回目の
   attemptとして再実行する。
4. 出力へ`test_cases[]`と各callの`attempts[]`を追加し、既存`items`・
   `followed_urls`・`page_notes`も維持する。
5. 到達失敗でも各Test Caseを`found: false`として残し、成功率の分母から消さない。
6. dashboardの表示文は`display_question`から従来どおり生成する。
7. METHOD / README / STATUSを実装と同期する。

## テスト

- Test Caseの4必須項目、順序、一意性、版、自治体名展開
- 未知service・未知fact_type・Test Case対象外serviceの明示的エラー
- 初回は4 fact_typeが4回の独立呼び出しになり、他項目をpromptへ混ぜない
- `--follow`の任意の2回目も同じfact_typeだけで、初回と追従後を`attempts[]`へ残す
- 1項目の壊れた応答が、どのTest Caseで失敗したか分かる
- `--follow`のURLと再呼び出しがTest Case間で混ざらない
- 到達失敗も4件の失敗記録になる
- 既存`items`を新記録から同じキーで復元できる
- edge / error caseを含むunit testと全CI相当を通す

## 完了条件

1件のextract JSONから、service×fact_typeごとの質問・版・成否を直接集計でき、
既存の採点・公開画面も同じ`items`契約で動く。

## 検証結果

- #55・#56・#67を含む最新mainへの統合後、Python 271件、Node 78件、
  合計349件のテストが成功した。
- 既存discovery 73件（転入届24、児童手当24、粗大ごみ24、パスポート1）が
  新しい事前検証を通過した。
- 手続き別の公開データ3件は、生成日時を固定した再生成で既存ファイルと
  byte単位で一致した。
- Evidence CheckはTest Caseごとに、その項目が実際に読んだページだけを照合し、
  他項目の追従ページを混ぜない。
- extractor / experimentの直接実行とmodule実行、`py_compile`、JSON構文確認、
  `git diff --check`が成功した。
