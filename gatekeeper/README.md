# 門番（gatekeeper）— 自治体サイトの前に立つ AI 応対係のプロトタイプ

自治体サイトの前段（Cloudflare Workers 層）に置き、来たリクエストをこう振り分ける：

| 誰が来たか | 門番の応対 |
|---|---|
| **署名つきのAIエージェント**（検証OK） | HTMLを読ませる代わりに**整った答え（JSON）**を返す。「何を探しに来たか」を記録 |
| 人間のブラウザ（署名なし） | **記録せず**そのまま元サイトへ素通し |
| 署名の検証に失敗 | 素通し（拒否はしない）。ただし verified=false で記録 |

エージェントの見分けには **Web Bot Auth**（RFC 9421 HTTP Message Signatures + Ed25519）を使う。
User-Agent と違って**署名は偽装できない**。ChatGPT が実際に公開鍵を配布中で、
Cloudflare のエッジでは2026年3月から本番稼働している標準。

**通行料は取らない。** 402課金は AWS（WAF AI traffic monetization・2026-06提供開始）／
Cloudflare（Pay per crawl）／Akamai の標準機能で、作る場所ではない。
この門番が貯める主役のデータは **「AIが何を探しに来て、取れたか／取れずに帰ったか」**
（記録レコードの `looking_for` と `answered`）。サーバーログには「来た」しか残らず、
「来たが取れなかった」はどこにも記録されていない——これが誰も持っていないデータになる。

## ファイル

| ファイル | 中身 |
|---|---|
| `httpsig.mjs` | RFC 9421 の最小実装（署名ベース構築・Ed25519署名/検証・RFC 7638 JWK指紋）。依存はWebCryptoのみ＝NodeとWorkersで同じコードが動く |
| `worker.mjs` | 門番本体（Cloudflare Worker 形。`wrangler deploy` できる形） |
| `test_local.mjs` | 署名→検証の暗号テスト 7本 |
| `test_worker.mjs` | 門番の応対テスト 10本（ネットワークはスタブ） |
| `build_answers.mjs` | 23区の実測から「整った答え」を作る（`answers/`。文章はここで作らない） |
| `wrangler.jsonc` / `put_answers.sh` | Cloudflare Workers へのデプロイ設定とKV投入 |
| `check_chatgpt_keys.mjs` | ChatGPT の実鍵を取得してパース互換を確認（要ネットワーク） |

## 動かす

```bash
node gatekeeper/test_local.mjs        # 暗号として動く証明（7 PASS）
node gatekeeper/test_worker.mjs       # 門番の応対一周（10 PASS）
node gatekeeper/check_chatgpt_keys.mjs  # ChatGPTの実鍵で形式互換を確認
node gatekeeper/build_answers.mjs     # 23区の実測から「整った答え」を作る
```

Node v24 以上（WebCrypto の Ed25519 が必要）。npm install は不要。

## デプロイ（Cloudflare特典の招待が届いてから）

特典の申請 → 招待メール → 登録、までは本人の手続き。**招待メールの有効期限は3日**。

```bash
cd gatekeeper
npx wrangler login                        # ハッカソン用チームアカウントを選ぶ
npx wrangler kv namespace create ANSWERS  # 出力の id を wrangler.jsonc に貼る
node build_answers.mjs && ./put_answers.sh
npx wrangler deploy
```

`routes` は付けていない。他人のドメインの前に無断で置くことはできないので、
まずは workers.dev のURLで、自分で用意したテストページを相手に動かす。

## 実測で確かめたこと（2026-07-31）

- 自前の Ed25519 鍵で 署名→検証 が通る。宛先改ざん・名乗り改ざん・期限切れ・鍵の騙りは全部落ちる
- ChatGPT の実鍵（`https://chatgpt.com/.well-known/http-message-signatures-directory`）を
  この実装でインポートでき、**kid が RFC 7638 指紋と完全一致**（keyid 規約の読みが正しい証明）
- 名乗ったオリジンが存在しない場合も門番は落ちず unknown-key として記録する

詳細: [reports/gatekeeper_sigverify_2026-07-31.md](../reports/gatekeeper_sigverify_2026-07-31.md)

## まだやっていないこと

- Cloudflare Workers への実デプロイ（**参加者特典の申請が先**＝本人タスク）
- 記録先の永続化（いまは console.log。Workers Analytics Engine / KV に差し替える）
- 整った答え（ANSWERS）への AI読 実測データの投入
- 本物のエージェント（ChatGPT等）からの実リクエスト受信確認
