# Failure Taxonomy

Version: 1.0

AI読で「答えられなかった」を記録するときの共通語彙。1つの失敗イベントには、処理の流れで最初に確定した1種を付ける。後段の推測で上書きしない。

## 8種の定義

| failure_type | 定義 | 判定条件 |
|---|---|---|
| `fact_missing` | 必要な事実が、実際に読めた対象ページ群に明記されていない。 | 対象ページ群の取得と本文抽出は成功しているが、答えを裏づける記述が無い。別ページを読めなかった場合には使わない。 |
| `fact_ambiguous` | 関連する記述はあるが、条件・対象・結論を1つに決められない。 | 取得済み本文に候補となる記述があり、矛盾や条件不足を解消できない。単なる取得失敗には使わない。 |
| `not_retrieved` | 答えがあると示された取得可能な資料を、AIが読めなかった。 | リンク先・PDF・添付・取得済みHTMLなどに進む必要があるが、その本文を取得または抽出できていない。入口から資料自体を発見できない場合には使わない。 |
| `wrong_evidence` | 回答の根拠として出した引用が存在しない、または回答を支えない。 | Evidence Checkが`missing`なら自動分類する。引用は存在しても主張との対応が誤っている場合はEvaluatorが判定する。回答値の正誤より先に根拠の不成立が確定する。 |
| `wrong_answer` | 十分で正しい根拠を読めているのに、回答値が正解と一致しない。 | 根拠の取得・照合に成功し、情報も現行だが、Ground Truthとの比較で答えが誤っている。 |
| `page_not_discoverable` | 公式の入口から、設定した探索条件内で対象ページを発見できない。 | 公式入口、探索深さ・件数、リンクのみという条件を記録した上で、対象ページへ到達できない。URLを知って直接開けるかどうかとは別。 |
| `structure_issue` | 取得したページに事実はあるが、構造のため本文と項目を正しく対応づけられない。 | 見出し・表・DOM・アクセシビリティ情報などを別の方法で確認すると事実が存在し、通常の正規化結果では対応関係を失う。 |
| `stale_information` | 取得したページの明記内容が、確認済みの現行情報より古い。 | 現行の一次情報と確認時点があり、対象ページの値が更新前のものだと証明できる。日付が不明なだけでは使わない。 |

## 判定の順序

処理の上流から、最初に失敗した段階を1つ記録する。

1. 対象ページを発見できない → `page_not_discoverable`
2. 発見後、必要な資料の本文を読めない → `not_retrieved`
3. 本文は読めたが構造で項目との対応を失う → `structure_issue`
4. 対応できた本文に事実が無い／曖昧 → `fact_missing` / `fact_ambiguous`
5. 回答の引用が存在しない／支えない → `wrong_evidence`
6. 引用元の情報自体が古い → `stale_information`
7. 現行の正しい根拠から答えを誤った → `wrong_answer`

この順序により、「リンク先を読めなかった」を`fact_missing`にせず、「入口からページを見つけられなかった」を`not_retrieved`にしない。

## 既存語彙のマッピング

抽出側の`failure_reason`は監査用に残し、コードが`failure_type`を導出する。

| 既存の場所 | 既存語彙 | failure_type | 理由 |
|---|---|---|---|
| extractor LLM | `記載なし` | `fact_missing` | 読めたページ群に明記が無いという申告 |
| extractor LLM | `電話でのみ確認可` | `fact_missing` | Webで読めたページ群に答えが無い |
| extractor LLM | `曖昧` | `fact_ambiguous` | 記述はあるが答えを確定できない |
| extractor LLM | `リンク先にあり` | `not_retrieved` | 別ページの取得が必要 |
| extractor LLM / 観測 | `PDF内のみ` | `not_retrieved` | PDF本文を今回の抽出器が読んでいない |
| experiment内部 | `抽出エラー` | `not_retrieved` | 呼び出した項目の答えを抽出できなかった |
| extractor内部 | `到達失敗` | `page_not_discoverable` | 公式入口から採点ページを選べなかった |
| experiment case | `target_page_unreachable_from_index` | `page_not_discoverable` | 公式入口から本体ページへ到達できなかった |

未知語彙は推測で分類せず、集計をエラーにする。

## 既存データの再分類

生成物: [`analysis/out/failure-taxonomy-summary.json`](../analysis/out/failure-taxonomy-summary.json)

```bash
python3 analysis/failure_distribution.py
```

分母が違うため、次の数字は足し合わせない。

| 単位 | 母数 | 失敗分布 |
|---|---:|---|
| 到達できた抽出実行のfact結果 | 284項目（71実行） | `fact_missing` 134、`fact_ambiguous` 11、`not_retrieved` 12 |
| 抽出実行そのもの | 73実行中、未到達2実行 | `page_not_discoverable` 2 |
| 再現実験のケース定義 | 1ケース | `page_not_discoverable` 1 |
| 再現実験のtrial結果 | 60項目（15 trial） | `fact_missing` 16、`not_retrieved` 4 |

抽出の旧結果には、`found=true`なのに`failure_reason`も入った契約矛盾が2項目ある。成功・失敗のどちらにも推測で寄せず、生成JSONの`legacy_contract_anomalies`へ別記した。

`wrong_evidence`は、既存73出力に対するEvidence Checkでも`missing` 0件だった（`partial` 23件は誤引用とは決めない）。`wrong_answer`、`structure_issue`、`stale_information`が0件なのは「存在しない」と確認した結果ではない。現在の既存データに、その判定を行う共通Evaluatorがまだ接続されていないためである。
