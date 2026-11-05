# 計画: 門番を自分の Cloudflare アカウントへ移す（#282）

**きっかけ**: 都知事杯の提供環境（アカウント tokyo_odh_310）は 11/6 に削除される（事務局メール 2026-10-30）。
門番 `aidoku-gatekeeper` はそこで動いているので、11/5 までに自分のアカウントへ移す。

**完了条件**: `https://aidoku-gatekeeper.panman.workers.dev` で門番が旧環境と同じ答えを返し、
いま使われている文書・画面の URL がそちらを指している。

## 前提（2026-11-03 に実物で確かめた）

- 提出作品の URL は GitHub Pages。門番が移っても変わらないので、事務局への連絡は要らない
- 旧環境のバインディング: KV `ANSWERS`（24件）・`DEMAND`（14件）、変数 `ORIGIN`、シークレット `DEMAND_TOKEN`
- `GITHUB_TOKEN` は旧環境でも未設定（受付は閉じたまま）。移した先でも入れない
- 本番の版は 9/9 のマージ直後。その後に門番へ入った変更は f642628（9/12 の修正）だけなので、main の版を出す

## 手順

1. 自分のアカウントに KV を2つ作り、旧環境から中身を写す（件数が一致することを確かめる）
2. `gatekeeper/wrangler.jsonc` に account_id と KV の id を入れる（PLACEHOLDER のままだった）
3. 門番のテストを回してから deploy する
4. `DEMAND_TOKEN` を作り直す。値はリポジトリの外（`~/.config/aidoku/gatekeeper.env`）に置く
5. 旧と新の URL に同じ問い合わせを投げて、答えが一致するか確かめる
6. URL を直す: `STATUS.md`・`web/reference/data.html`・`web/test_agent_endpoints.mjs`

## 直さないもの

- `web/data/demand.json`・`demand.csv` の `authority`: 当時どのホストに来たかの記録なので書き換えない
- `reports/`・`plans/archive/`: 当時の記録
