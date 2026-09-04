# 住民の画面に点数を出すか、調査データに置くか

Status: 決定済み（2026-08-23）
Tracks: web/index.html / web/assets/app.js / web/archive.html / analysis/export_surveys.py

## 問題

住民が区を押すと、まずこれが出ていた。

    7 / 12  区のページから読み取れた項目 — 読み取れなかった項目が5つあります
    ▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬（緑の棒）
    この区の点数の移り変わりは 見張りと推移 にあります。

本人の指摘:「住民側にこれいらないでしょ。あくまで自分が調べたいときに参考にする
情報としてならわかるけど、一切説明もないしユーザー体験としておかしくない？」

そのとおり。**7/12 が何の点なのか、住民には説明していない。** 住民が知りたいのは
「自分のAIが何を知れないか」であって、区の成績でも調査の履歴でもない。
点数を最初に出すのは、住民の用事ではなく調査側の都合。

## 決定

**住民の画面からは点数・棒グラフ・推移リンクを外す。** 代わりに1文を出す。

    測った3つの手続きのうち、AIが区のページから読み取れなかった項目が5つあります。

手続き1行の札も `0/4` をやめ、「読めない 3項目」「4項目とも読めた」と言葉にする。

**点数と履歴は archive.html（調査データ一覧）に移す。** 年月日で引ける形にして、
参照したい人が参照できるようにする（本人の指摘:「調査データは調査データ一覧で
年月日ごとにアーカイブで別タブでもいいので残した方がいい」）。

## 作るときに見つかったこと（重要）

`history/scores.jsonl` は **測定ではなく、書き出しを走らせた回を記録していた**。
`measured_on` の元は `generated_at`＝エクスポータの実行時刻だったため、
3回ぶんの記録があるのに 345観測すべて値が同じ。

そのまま一覧にすると「3回調べました」に読める。そこで `export_surveys.py` が
自治体ごとの合計点で指紋を取り、値が同じ回に `same_as_previous: true` を付ける。
画面は「3回ぶんの記録がありますが、値が前回と違ったのは1回です」と言う。

**残っている宿題**: 測定の日付を、エクスポータの実行時刻ではなく
実際に測った時刻から取ること。いまは再測定していないので実害は出ていないが、
測り直した瞬間に日付が嘘になる。

---

## 追記（2026-08-23）— 宿題への回答: 実測時刻は残っていなかった

**まず探した。無かった。**

| 探した場所 | 結果 |
|---|---|
| `extractor/out/*.json`（73件） | 全件 `recording_status: legacy_unknown`。`run_at` / `discovery_run_at` は `null` |
| `crawler/out/*.json`（83件） | `measurement` キー自体が無い。`fetch_log` にも時刻は無い |
| `scorer/out/*.json` | `measurement` は `null` |
| `web/data/scores-*.json` | `measurement.run_at` は `[]`、`runs[]` 23件も全部 `run_at: null` |
| `experiment/out/setagaya-tennyu_2026-08-15.json` | `run_at` を持つ**が**、これは1区の安定性実験で、23区の点数とは別系統。流用しない |

`README.md` や `export_dashboard.py` の散文に「2026-07-22」という日付はあるが、
これは人が書いた文であって、レコードごとに付いた時刻ではない。転入届の初回ぶんしか
指しておらず、その後の再抽出も同じ日として扱われてしまう。**データに書き戻すのは
捏造なので、しない。**

**したがって決定（依頼の選択肢3番）: いまの `generated_at` が何であるかを、公開データ
自身に明示する。注釈で済ませず、名前を実態に合わせる。**

    measured_at / measured_on   実際に測った時刻。**記録が無ければ null / 空欄**
    exported_at / exported_on   書き出しを走らせた時刻（旧 measured_at の中身）
    recorded_at / recorded_on   履歴行を記録に残した時刻

- `history.snapshot_from_doc()` は `measurement.run_at` から `measured_at` を取る
  （新設 `measured_at_of()`）。記録が無ければ `None`。**`generated_at` で埋めない。**
- `analysis/export_timeseries.py` の CSV は `measured_on` を空欄にし、`exported_on` を足した。
- `analysis/export_surveys.py` は `measured_at` → `exported_at` に改名し、実測の
  `measured_at` と `measured_at_status`（recorded / unknown）を別に持つ。schema は
  `aidoku-surveys-2`。`same_as_previous` は従来どおり「値が前回と同じ書き出し」を指し、
  改名後は「3回の書き出し／値が違うのは1回」と読み方が一致する。
- 画面（`archive.html` / `archive-list.js` / `archive-view.js`）は「◯月◯日に測定」をやめ、
  「◯月◯日 ◯:◯ に書き出し」＋「測った日時: 記録なし」と書く。

**なぜ注釈でなく改名まで要ったか**: `_about` に but 書きを足すだけでは、列名
`measured_on` をそのまま読む機械（表計算・統計ソフト・AI）が嘘を読む。
**名前が嘘なら、注釈は届かない。**

**次に測り直したときに直ること**: 抽出器が `recording_status: recorded` で `run_at` を
書けば、以降の履歴行は自動的に本物の実測時刻を持つ。コードはもうそちらを見ている。
**過去の回は不明のまま**で、それが正しい。
