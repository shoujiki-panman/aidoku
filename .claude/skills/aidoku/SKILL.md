---
name: aidoku
description: AI読（アイドク）の作業を始めるときの入口。いまの状態（見張り・測定条件・虱潰し・公開データ）をデータから出し、次にやることを決める。「続き」「いまどうなってる」「測り直して」「公開して」と言われたらこれを使う。調べ直す前に必ず通ること。
---

# AI読の作業を始める

**調べ直さない。まずこれを実行する。**

```bash
python3 analysis/status.py
```

5つの状態と「次にやること」が出る。**その出力に従う。**
`STATUS.md` は手書きで古くなるので、現在地の判断には使わない（経緯を読むときだけ）。

## 状態ごとの動き

### ② 測定条件が「★N区ぶん古い」と出たとき

**公開できない状態。** `export_dashboard.py` が拒む（正しい拒否）。
揃えるには、古い区だけ測り直す。**6区ずつに切る**（落ちても失うのが6区で済む）。

```bash
python3 extractor/extract.py -m <区ID> -p <手続き> --follow
```

一括で回さない。利用上限で落ちた実績がある（71ページ失った）。

### ① 見張りが変化を見つけているとき

`web/data/site-status.json` の `items` で、変わったページを見る。
**見張りは自動では測り直さない。** 何を測り直すかは人が決める。

### ③ 虱潰しに「言えない」が残っているとき

`analysis/sweep.py` の `stopped` を見る。**混ぜない。**

| 印 | 意味 | 言えること |
|---|---|---|
| `found` | 見つかった | こちらの読み落としだった |
| `exhausted` | 候補を全部読んだ上で無い | **ここだけ「区が書いていない」と言える** |
| `unreadable` | 読めない候補が残っている | **言えない** |
| `budget` / `error` | 打ち切り・失敗 | **言えない** |

### 公開まで通すとき

```bash
python3 analysis/apply_evidence_check.py                  # キャッシュのみ・LLM不要
python3 analysis/export_dashboard.py -p <手続き> --out web/data/scores-<手続き>.json
```

## 守ること

- **「その区が書いていない」は5条件が揃った項目だけ** → `METHOD.md §4-7c`。
  判定するのは人ではなく `analysis/sweep.py`
- **数字を手で数えない。** 変化セルは `analysis/compare_runs.py`、
  現在地は `analysis/status.py`。手で数えて一度間違えている（29→21）
- **間違った結果は消さない** → `analysis/out/known-wrong/`。判定には使わない
- **作品本体は標準ライブラリのみ。** 外部の変換器（anydoc）は
  `analysis/probes/compare_readers.py` の検算だけ → `plans/decisions/external-reader.md`
- 作業の記録は `plans/<名前>.md` の `## Progress` に**追記のみ**

## よく使う道具

| したいこと | コマンド |
|---|---|
| いまの状態 | `python3 analysis/status.py` |
| 虱潰し | `python3 analysis/sweep.py -p <手続き>` |
| 2回の測定の差 | `python3 analysis/compare_runs.py -p <手続き>` |
| 壊れたキャッシュを取り直す | `python3 crawler/refetch_broken.py --check` |
| 読み手の検算（要 .venv） | `.venv/bin/python analysis/probes/compare_readers.py` |
| 全テスト | `python3 -m unittest discover -s . -p "test_*.py"` |
