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

## できるデータ（`GET /_aidoku/demand`）

門番は集めたものをKVに追記し、この口から集計して返す。**取れずに帰った一覧が、
そのまま区役所への更新依頼リストになる。**

```
■ AIが探しに来たのに、取れずに帰ったもの（＝そのページに足りていない情報）
   4回  転入届 必要書類   www.city.setagaya.lg.jp/kurashi/kosekijuumin/11531.html
   3回  転入届 手数料     www.city.setagaya.lg.jp/kurashi/kosekijuumin/11531.html
   2回  転入届 手数料     www.city.shinjuku.lg.jp/todokede/koseki01_000001_00007.html
```

数え方で気をつけていること:

- **「取れた」は、ページに答えの束があることではない。聞かれた項目に答えがあること。**
  手数料を聞かれて手数料だけ空なら、取れずに帰ったと数える（新宿区がまさにこれ）
- 表記ゆれ（全角空白など）はならしてから数える
- **人（署名なし）のアクセスは記録しない。** データに入るのは身元を署名で証明したAIだけ
- KVには足し算が無いので、**書き込みは追記だけ**にして読み出し時に集計する（同時に来ても数え落ちない）
- 記録は90日で自動的に消える（貯めっぱなしにしない）

## ファイル

| ファイル | 中身 |
|---|---|
| `httpsig.mjs` | RFC 9421 の最小実装（署名ベース構築・Ed25519署名/検証・RFC 7638 JWK指紋）。依存はWebCryptoのみ＝NodeとWorkersで同じコードが動く |
| `worker.mjs` | 門番本体（Cloudflare Worker 形。`wrangler deploy` できる形） |
| `demand.mjs` | **集めたものをデータにする部分**。KVに追記し、読み出し時に集計する |
| `demo_talk.mjs` | **AIと門番のやり取りをそのまま書き出すデモ**（何を聞かれ、何を返したか） |
| `demo_demand.mjs` | **Cloudflare無しで、データができるところを見せるデモ** |
| `test_local.mjs` | 署名→検証の暗号テスト 7本 |
| `test_worker.mjs` | 門番の応対テスト 17本（ネットワークはスタブ） |
| `build_answers.mjs` | 23区の実測から「整った答え」を作る（`answers/`。文章はここで作らない） |
| `wrangler.jsonc` / `put_answers.sh` | Cloudflare Workers へのデプロイ設定とKV投入 |
| `check_chatgpt_keys.mjs` | ChatGPT の実鍵を取得してパース互換を確認（要ネットワーク） |

## 動かす

```bash
node gatekeeper/test_local.mjs        # 暗号として動く証明（7 PASS）
node gatekeeper/test_worker.mjs       # 門番の応対一周（17 PASS）
node gatekeeper/check_chatgpt_keys.mjs  # ChatGPTの実鍵で形式互換を確認
node gatekeeper/build_answers.mjs     # 23区の実測から「整った答え」を作る
node gatekeeper/demo_talk.mjs         # ★AIと門番のやり取りをそのまま見る
node gatekeeper/demo_demand.mjs       # ★AIを来させて、データができるところを見る
```

Node v24 以上（WebCrypto の Ed25519 が必要）。npm install は不要。

## デプロイ（Cloudflare特典の招待が届いてから）

特典の申請 → 招待メール → 登録、までは本人の手続き。**招待メールの有効期限は3日**。

```bash
cd gatekeeper
npx wrangler login                        # ハッカソン用チームアカウントを選ぶ
npx wrangler kv namespace create ANSWERS  # 出力の id を wrangler.jsonc に貼る
npx wrangler kv namespace create DEMAND   # 同上（集めたデータの置き場）
node build_answers.mjs && ./put_answers.sh
npx wrangler deploy
```

`routes` は付けていない。他人のドメインの前に無断で置くことはできないので、
まずは workers.dev のURLで、自分で用意したテストページを相手に動かす。

### 特典の条件と、この門番の設計（2026-08-01 マニュアル確認）

| 特典側の条件 | 門番はどうなっているか |
|---|---|
| Workers AI で高額モデル（claude-sonnet-5 / claude-opus系 / gpt-5.6系 / gemini pro系など）の使用は**禁止** | **門番はCloudflare上でLLMを一切呼ばない**。KVに入れた実測値を返すだけ。AI読の判定は手元のClaude Codeで動かしていて、Cloudflareの外 |
| 個人情報・機密情報の不正な取り扱いは禁止 | **署名なしのアクセス（＝人間）は記録しない**。記録するのは署名で身元が証明されたAIエージェントの「何を探しに来て、取れたか」だけ |
| APIキーはSecrets Storeか環境変数で管理し、ソースに直書きしない | 門番に秘密情報は無い（公開鍵をJWKSから取りに行くだけ）。増やすときもここに直書きしない |
| ハッカソンの成果物開発以外の利用は禁止 | 門番は提出作品そのもの |
| **2026年9月末でチームアカウントの権限が停止**（Final進出なら延長） | **KVに貯めた記録は9月末までに必ずエクスポートする**。権限停止後は取り出せない |

## 実測で確かめたこと（2026-07-31）

- 自前の Ed25519 鍵で 署名→検証 が通る。宛先改ざん・名乗り改ざん・期限切れ・鍵の騙りは全部落ちる
- ChatGPT の実鍵（`https://chatgpt.com/.well-known/http-message-signatures-directory`）を
  この実装でインポートでき、**kid が RFC 7638 指紋と完全一致**（keyid 規約の読みが正しい証明）
- 名乗ったオリジンが存在しない場合も門番は落ちず unknown-key として記録する

詳細: [reports/gatekeeper_sigverify_2026-07-31.md](../reports/gatekeeper_sigverify_2026-07-31.md)

## まだやっていないこと

- **Cloudflare Workers への実デプロイ**（特典は2026-08-01に申請済み。招待メール待ち）
- **本物のエージェント（ChatGPT等）からの実リクエスト受信確認**。
  いまのデータは、自前の鍵で署名した2体のエージェントを来させた再現（`demo_demand.mjs`）。
  署名検証・記録・集計はすべて実物のコードで動いているが、**本物のAIが来た実データはまだ無い**
- 集めたデータの画面（いまはJSONと、デモの標準出力まで）
