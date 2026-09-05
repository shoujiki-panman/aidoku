# 画面を「使うもの」と「読み物」に分ける

Status: 決定済み（2026-09-05・本人指示）
Tracks: web/*.html / web/reference/*.html / web/assets/app.js / web/assets/fix.js
        / web/test_askai.mjs / web/test_pipeline.mjs

## 問題

`web/` 直下に画面が11枚あった。中身を数えると次のようになっていた。

| | 何枚 | 役目 |
|---|---|---|
| 使う | `index.html` / `board.html` / `fix.html` | 住民が自分の区を見る。区が自分の区を直す |
| 読み物 | `how` `data` `archive` `journey` `barrier` `demand` `trends` `skill` | 「AI読とは何か」の説明 |

**「AI読は何か」を説明する部分が、「AI読を使う」部分の8倍**あった。
アプリが無いまま説明だけ増えた結果で、変更のたびに11画面と12データの
整合を取る羽目になっていた（`index.json` の sha256 ズレで実際に足を取られた）。

## 決定

**使う画面3枚を `web/` 直下に残し、読み物8枚を `web/reference/` に下げる。**

- 消さない。読み物が悪いのではなく、**使うもの（URLを入れる→診断→穴→埋める→貼る）を
  作る時間を空ける**ための移動。
- 下げた8枚には `<head>` の先頭に `<base href="../">` を置く。
  ページの中のパスは `assets/…` `data/…` `index.html` のまま上の階層を指す。
  リンクを1本ずつ書き換えるより、壊れたときに気づきやすい（`<base>` が1行消えれば全部落ちる）。
  下げた8枚に `href="#..."` のページ内リンクは無いので、`<base>` の副作用は出ない。
- 上の階層から読み物へ行くリンクだけ `reference/…` に書き換える
  （メニュー・フッター・`app.js` / `fix.js` が出すセルの「AIがどう歩いたか」）。

## データは動かさない

同じ日に一緒に切ろうとしたが、**16本のうち reference/ からしか読まれないのは4本だけ**だった
（`barriers` `demand` `pipeline` `surveys`）。いちばん大きい `journeys.json`（232K）も
`archive.json` も住民の画面（`app.js`）が読んでいる。
4本のために `data/` を2つに割ると、書き出し側（`analysis/export_*.py`）と
`data/index.json` の突き合わせが二重になる。**割に合わないのでやらない。**

## 壊れていないことの確かめ方

- `node web/test_askai.mjs` — 「使う画面は3枚」と、下げた8枚に `<base href="../">` があることを見る。
  `<base>` が落ちたらここで落ちる
- `node web/test_pipeline.mjs` — 画面から「調べ方とデータ」へ行けることを見る
- ブラウザで `web/index.html` と `web/reference/how.html` を開き、
  取得したファイルが全部 200 であることを確認済み（2026-09-05）
