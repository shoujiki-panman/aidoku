# 使う画面3枚に絞る

Status: 実装済み（2026-09-05）
決定の理由: [decisions/three-screens.md](decisions/three-screens.md)

## やること

1. 読み物8枚（`how` `data` `archive` `journey` `barrier` `demand` `trends` `skill`）を
   `web/reference/` へ `git mv` する
2. 下げた8枚の `<head>` 先頭に `<base href="../">` を入れる
3. 上の階層から読み物へのリンクを `reference/…` にする
   （`index.html` / `board.html` / `fix.html` のメニューとフッター、`assets/app.js`、`assets/fix.js`）
4. テストを新しい形に合わせる（`test_askai.mjs` / `test_pipeline.mjs`）
5. 場所を書いている文書を直す（`README.md` / `START-HERE.md` とコード中のコメント）

## 完了の条件

- `web/test_*.mjs` 12本と `gatekeeper/test_*.mjs` 4本が緑
- Python のテストが緑（`.` 498 / `analysis` 90 / `crawler` 218）
- `ruff check .` と `npx jscpd .` が緑
- ブラウザで `index.html` と `reference/how.html` を開き、404 が1本も出ない

## やらないこと

- **データは分けない。** reference/ からしか読まれないのは16本中4本だけ。
  理由は決定ファイルに書いた
- **読み物を消さない。** 移すだけ

## Progress

<!-- 追記のみ。1ステップ1行。失敗も書く。書き直さない -->

- 2026-09-05 ①②③ 実施（前セッション）。`<base href="../">` 方式を採用
- 2026-09-05 テスト2本が旧レイアウト前提で落ちた
  （`test_askai` の「6枚以上」、`test_pipeline` の `./data.html` 直読み）→ ④で直した
- 2026-09-05 ⑤ `README` / `START-HERE` / `export_journey.py` / `build_demand_sample.mjs` /
  `lookup.js` / `app.js` のコメントを `reference/` に直した
- 2026-09-05 完了条件を全部確認。ブラウザは `index.html` 41本・`reference/how.html` 14本とも 200
- 2026-09-05 `feat/method-external-refs`（PR #178 マージ済み・その後 8dc18a5 が1本
  ぶら下がったまま）ではなく、`origin/main` から `feat/three-screens` を切って
  cherry-pick した（a8926d3）。main 側の変更は data だけで衝突なし
- 2026-09-05 新ブランチで node 16本（web 12 + gatekeeper 4）緑を再確認。
  **残り: ruff / jscpd / Python を新ブランチで1回、そのあと push と PR**
- 2026-09-05 別件の未処理: 8dc18a5「一度きりの調べものを分け、検査を1本にする」が
  main に入っていない。PR が無いので、この作業とは別に1本立てる必要がある
- 2026-09-05 `feat/three-screens` で完了条件を全部再確認。ruff 緑 /
  Python 986本 緑（`.`478 `analysis`123 `crawler`218 `experiment`37 `extractor`65
  `gennai_app`41 `scorer`24）/ jscpd 0.93%（閾値5%）/ node 16本 緑 /
  11枚 228リンクを実際に引いて 404 ゼロ
- 2026-09-05 8dc18a5 の別件は別セッションが `refactor/probes-split` で拾った。
  同じ作業ツリーを共有すると HEAD を取り合うので、こちらは worktree を分けた
