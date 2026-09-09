# demand画面に本物の来訪記録を接続する

Status: 実装中
Issue: [#206](https://github.com/shoujiki-panman/aidoku/issues/206)
前提: 門番は本番稼働済みで、本物の ChatGPT の検証済み来訪が KV に貯まっている（#199）。
画面（`web/reference/demand.html`）は `is_sample` が無いデータなら実データ表示に切り替わる
実装が既にある。足りないのは**KVの集計を公開データへ運ぶ経路**だけ。

## 経路の設計

```
本番 /_aidoku/demand（DEMAND_TOKEN で閉鎖）
  → gatekeeper/export_demand.mjs（手で回す。点数と同じ）
  → web/data/demand.json（PR経由＝コミット前に人が中身を見る）
  → demand.html が実データ表示に切り替わる
```

- **画面から直接KVは読まない。** 集計口は鍵つきのまま（質問文の選別が無いため。README の
  「置く前に直すこと」どおり）。公開されるのは、PRで人が見てからコミットした静的JSONだけ
- 自動化はしない（見張りと違い、質問文が入り始めたら人の目が要る）

## 完了条件

1. `export_demand.mjs` が本番の集計を `web/data/demand.json` の形でそのまま書き出す
2. 見本を実データとして書き出せない（`is_sample` 付きの入力は拒否して落ちる）
3. 書き出したデータで demand.html が「実データ」表示になり、検証済み来訪（ChatGPT）が出る
4. README（トップ・gatekeeper）の「画面の数字は見本」の注意が実情に更新される
5. 1〜2 が node の unit test で機械確認できる

## Progress

<!-- 追記のみ。1ステップ1行。失敗も書く。書き直さない -->

- 2026-09-09 計画作成・実装着手
- 2026-09-09 export_demand.mjs（見本は拒否）・テスト4件・実データ書き出し（来訪14/取れず5/
  検証済みエージェント1=ChatGPT・質問文なしを目視確認）。実画面で「実データ」表示を確認し、
  実データ時に「以下は見本の数字です」が残る取りこぼしを修正
