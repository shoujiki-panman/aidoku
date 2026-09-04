# 書き出し時刻を「測定時刻」と呼ぶのをやめる

Status: 実装済み（2026-08-23）／未コミット
Tracks: `history.py` / `analysis/export_timeseries.py` / `analysis/export_surveys.py` /
`analysis/export_data_index.py` / `web/assets/archive-list.js` / `web/assets/archive-view.js` /
`web/archive.html` / `web/data/README.md`

## 問題

`web/data/history/scores.jsonl` は **測定ではなく、書き出しを走らせた回を記録していた。**

    measured=2026-08-11T13:52:32  recorded=2026-08-17T01:02:39  転入届  平均=59.6
    measured=2026-08-17T12:56:14  recorded=2026-08-17T22:01:07  転入届  平均=59.6
    measured=2026-08-17T15:10:26  recorded=2026-08-18T00:59:18  転入届  平均=59.6

`measured_on` の元が `generated_at`（`analysis/export_dashboard.py` の実行時刻）なので、
**3回ぶんの記録があるのに345観測すべて値が同一**。いまは再測定していないので実害は
出ていないが、**測り直した瞬間に日付が嘘になる。**

前提は `plans/decisions/resident-vs-data.md` の「残っている宿題」。

## ① まず探した — 実測時刻はどこにも残っていない

| 探した場所 | 結果 |
|---|---|
| `extractor/out/*.json`（73件） | 全件 `recording_status: legacy_unknown`。`run_at` / `discovery_run_at` は `null` |
| `crawler/out/*.json`（83件） | `measurement` キー自体が無い。`fetch_log` にも時刻は無い |
| `scorer/out/*.json` | `measurement` は `null` |
| `web/data/scores-*.json` | `measurement.run_at` は `[]`、`runs[]` 23件も全部 `run_at: null` |
| `experiment/out/setagaya-tennyu_2026-08-15.json` | `run_at` を持つ**が**、1区の安定性実験。23区の点数とは別系統なので流用しない |

散文の「2026-07-22」（`README.md` / `export_dashboard.py` の DISCLAIMER）は人が書いた文で、
レコードごとの時刻ではない。転入届の初回ぶんしか指さない。**データに書き戻すのは捏造。**

→ **依頼の選択肢3番を採る。** 実測時刻は出せない。出せないと公開データ自身に書く。

## ② 直したこと

日付が3つあり、意味が違う。名前をそこに合わせた。

    measured_at / measured_on   実際に測った時刻。**記録が無ければ null / 空欄**
    exported_at / exported_on   書き出しを走らせた時刻（旧 measured_at の中身）
    recorded_at / recorded_on   履歴行を記録に残した時刻

| ファイル | 変更 |
|---|---|
| `history.py` | `measured_at_of()` を新設。`measurement.run_at`（str / list）から実測時刻を取り、無ければ `None`。`snapshot_from_doc()` が `measured_at` を持つ。`series()` も両方の時刻を返す |
| `analysis/export_timeseries.py` | `measured_on` の出どころを `measured_at` に。記録が無い回は空欄。`exported_on` 列を追加。並びの第2キーに `exported_on`。実行時の表示も「測定日」と「書き出し日」を言い分ける |
| `analysis/export_surveys.py` | `measured_at` → `exported_at` に改名。実測の `measured_at` / `measured_on` / `measured_at_status`（recorded / unknown）を別に持つ。`n_measured_unknown` を追加。schema を `aidoku-surveys-2` に。`ABOUT` に「書き出し時刻であって測定時刻ではない」と明記 |
| `analysis/export_data_index.py` | CSV の列説明（`measured_on` の空欄の意味 / `exported_on`）、surveys の説明と `join`、`provenance.note` に「測った時刻も記録されていない」を追記 |
| `web/assets/archive-list.js` | `exportedLabel()` / `measuredLabel()` を追加。「◯月◯日に測定」をやめ「◯月◯日 ◯:◯ に書き出し」＋「測った日時: 記録なし」 |
| `web/assets/archive-view.js` | 上記を使う。フッタの生成日は `exported_on` |
| `web/archive.html` | リード文を「書き出した日ごと」に。日付が書き出し時刻である旨を1段落追加 |
| `web/data/README.md` | history 節に「日付は3つあり、意味が違う」表と、いま全件 null である理由 |

**なぜ注釈でなく改名まで要ったか**: `_about` に but 書きを足すだけでは、列名
`measured_on` をそのまま読む機械（表計算・統計ソフト・AI）が嘘を読む。名前が嘘なら
注釈は届かない。

**`same_as_previous` との整合**: 従来どおり「値が前回の書き出しと同じ」を指す。
改名後は「3回の**書き出し**／値が違うのは1回」と読み方が一致する。

## ③ 再生成したもの

- `web/data/history/measurements.csv`（1035行 / `measured_on` は全行空欄 / 書き出し日2回）
- `web/data/surveys.json`（書き出し3回 / 値が違うのは1回 / 実測時刻が無い回3）
- `web/data/index.json`

`history/scores.jsonl` は**追記のみ・過去行は書き換えない**方針なので触っていない。
既存9行に `measured_at` キーが無いのは「不明」として扱われる（`.get()` が `None`）。

## ④ テスト

- `test_history.py` に `測定時刻` クラス（9件）。`measured_at_of()` の各分岐と、
  「書き出し時刻を `measured_at` に流し込まない」を固定
- `analysis/test_export_surveys.py` に `日付の名前` クラス（6件）。
  `measured*` のどのキーにも書き出し時刻が入らないことを、値の一致で直接見る
- `analysis/test_export_timeseries.py`（新規・8件）。空欄の意味、書き出しを流し直しても
  測定日が増えないこと、実データが全件空欄であること
- `web/test_archive.mjs` に日付の言い方の検査（6件）と、`archive-view.js` に
  「に測定」を戻していないことの検査（3件）

## やらなかったこと

- **`scores.jsonl` の既存行に `measured_at: null` を書き足す** — 追記のみの方針を破る。
  キーが無い＝不明で読めるので実利も無い
- **散文の「2026-07-22」をデータに書き戻す** — 捏造。手続き1つ・初回ぶんしか指さない
- **ファイルの mtime を実測時刻とみなす** — チェックアウト・コピーで壊れる。時刻ではない
- **`history.diff()` の `from` / `to`** — 名前が中立で嘘を含まないので触らない

## 残っている宿題

次に測り直すとき、抽出器が `recording_status: recorded` で `run_at` を書けば、以降の
履歴行は自動的に本物の実測時刻を持つ。**コードはもうそちらを見ている。**
過去の回は不明のままで、それが正しい。

## Progress

<!-- 追記のみ。1ステップ1行、失敗も書く。書き直さない。 -->

- 2026-08-23 extractor/out・crawler/out・scorer/out・experiment/out を全走査。実測時刻は無し。
- 2026-08-23 選択肢3（名前を実態に合わせる）で実装。①〜④完了。
- 2026-08-23 Python 全ディレクトリ + node 11本を実行。**別エージェントが作業中の
  `measurement.py`（`table_reading` を CONDITION_KEYS に追加）が `web/data/scores-*.json`
  未再生成のため、`test_history.RealData` が1件 ValueError で落ちる。**
  HEAD の `history.py` でも同じ落ち方をするので、この変更とは無関係。scores-*.json の
  再生成待ち。
