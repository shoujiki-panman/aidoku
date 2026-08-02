# 門番（gatekeeper）— 自治体サイトの前に立つ AI 応対係のプロトタイプ

自治体サイトの前段（Cloudflare Workers 層）に置き、来たリクエストをこう振り分ける：

| 誰が来たか | 門番の応対 |
|---|---|
| **署名つきのAIエージェント**（検証OK） | HTMLを読ませる代わりに**整った答え（JSON）**を返す。「何を探しに来たか」を記録 |
| 人間のブラウザ（署名なし） | **記録せず**そのまま元サイトへ素通し |
| 署名の検証に失敗 | 素通し（拒否はしない）。ただし verified=false で記録 |

エージェントの見分けには **Web Bot Auth**（RFC 9421 HTTP Message Signatures + Ed25519）を使う。
User-Agent と違って**署名は偽装できない**。ChatGPT が実際に公開鍵を配布中で、
[Cloudflare は2025年7月から Verified Bots の一部として署名検証を提供](https://blog.cloudflare.com/verified-bots-with-cryptography/)、
[AWS WAF も2025年11月に対応](https://aws.amazon.com/about-aws/whats-new/2025/11/aws-waf-web-bot-auth-support)している。
ただし **Web Bot Auth 自体はまだ IETF のドラフト段階**（architecture draft-05・2026-03-02）で、
RFC にはなっていない。RFC 9421（署名の形式）だけが確定済み。

**通行料は取らない。** 402課金は AWS（WAF AI traffic monetization・2026-06提供開始）／
Cloudflare（Pay per crawl）／Akamai の標準機能で、作る場所ではない。
この門番が貯める主役のデータは **「AIが何を探しに来て、取れたか／取れずに帰ったか」**
（記録レコードの `looking_for` と `answered`）。サーバーログには「来た」しか残らず、
「来たが取れなかった」はどこにも記録されていない——これが誰も持っていないデータになる。

## AIの聞き方（`POST /ask` — NLWeb）

**探し物の受け取り方は自分で発明しない。** 実際のAIエージェントは `?q=` のような
各サイト独自のクエリを付けてこないので、[NLWeb](https://nlweb.ai/docs/specification)
（サイトを自然言語で聞ける窓口にする公開プロトコル。Shopify / Snowflake / O'Reilly /
Tripadvisor 等が採用、Cloudflare Workers への載せ方も公開されている）に合わせる。

```
POST /ask
{"query": {"text": "転入届の手数料はいくらですか", "site": "/todokede/tennyu.html"}}
```

返す型は規格のまま3つ。**「取れずに帰った」は我々の造語ではなく、NLWeb の `failure` そのもの。**

| 聞かれたもの | 返す型 | 記録 |
|---|---|---|
| 書いてある項目 | `answer`（schema.org の `GovernmentService` ＋ 実測値） | `answered: true` |
| **書かれていない項目** | **`failure` / `NO_RESULTS`** | **`answered: false`** ←主役 |
| どの項目か分からない | `elicitation`（聞き返す） | `answered: null` |

3つ目が肝心なところ。**曖昧な問いを黙って「取れた」に倒さない。**
推測で数えると、実運用ではほぼ全件が「取れた」になって、主役のデータが消える。
聞き返した分は `totals.undetermined` として別に数える。

※ `results` の `fields` は schema.org の語彙ではなく、AI読の実測値そのもの
（`answers/*.json` の中身）。文章はここで作らない。

### MCP からも同じことを聞ける（`POST /mcp`）

NLWeb は**各インスタンスがMCPサーバーにもなる**規格。公開するツール名は
NLWeb仕様 Appendix A のとおり **`ask`**、引数は `query` / `context` / `prefer` / `meta`。
[MCP 2025-06-18](https://modelcontextprotocol.io/specification/2025-06-18) の
JSON-RPC 2.0（`initialize` / `tools/list` / `tools/call` / `ping`）で話す。

```bash
curl -X POST https://<門番>/mcp -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"ask",
       "arguments":{"query":{"text":"転入届の手数料はいくらですか","site":"/todokede/tennyu.html"}}}}'
```

**どの口から来ても、答え方も数え方も同じ**（記録の `via` が `nlweb` / `mcp` / `query` で分かれるだけ）。

`isError` は「ツールが実行できなかった」ときの印なので、
**「そのページには書かれていなかった」(`NO_RESULTS`) は `isError: false`**。
書かれていないことは失敗ではなく、正しい答え。

## できるデータ（`GET /_aidoku/demand`）

門番は集めたものをKVに追記し、この口から集計して返す。**取れずに帰った一覧が、
そのまま区役所への更新依頼リストになる。**

⚠️ **下の回数は `demo_demand.mjs` の再現で、こちらで決めた仮の値**。
本物のAIが来た記録ではない（実データはまだ無い。「まだやっていないこと」を参照）。
実測で言えるのは「どのページのどの項目が空か」のほうで、そちらは `answers/` が実測値。

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
- **人（署名なし）のアクセスは記録しない。** 記録に入るのは署名を付けて来たAIだけ
- **「どのAIが来たか」(`by_agent`) は、署名の検証に成功した名乗りだけを数える。**
  他人の公開 keyid は誰でも書けるので、検証前の名乗りは自称にすぎない。
  検証に失敗した来訪は件数（`totals.unverified`）としてだけ出す
- KVには足し算が無いので、**書き込みは追記だけ**にして読み出し時に集計する（同時に来ても数え落ちない）
- **読み切れなかったことを隠さない。** 集計は上限（既定1000件）で打ち切るので、
  打ち切ったかどうかと集計対象の期間を `coverage` で必ず返す。
  落とすのは古いほう（キーを時刻の降順にしてある＝直近が必ず見える）
- 記録は90日で自動的に消える（貯めっぱなしにしない）

## ファイル

| ファイル | 中身 |
|---|---|
| `httpsig.mjs` | RFC 9421 の最小実装（署名ベース構築・Ed25519署名/検証・RFC 7638 JWK指紋）。依存はWebCryptoのみ＝NodeとWorkersで同じコードが動く |
| `worker.mjs` | 門番本体（Cloudflare Worker 形。`wrangler deploy` できる形） |
| `nlweb.mjs` | **AIの聞き方（NLWeb の `POST /ask`）**。answer / failure / elicitation を規格どおりに返す |
| `mcp.mjs` | **MCP の窓口（`POST /mcp`）**。JSON-RPC 2.0。ツールは NLWeb 仕様の `ask` 1本 |
| `demand.mjs` | **集めたものをデータにする部分**。KVに追記し、読み出し時に集計する |
| `demo_talk.mjs` | **AIと門番のやり取りをそのまま書き出すデモ**（何を聞かれ、何を返したか） |
| `demo_demand.mjs` | **Cloudflare無しで、データができるところを見せるデモ** |
| `test_local.mjs` | 署名→検証の暗号テスト 11本（門番が例外で落ちないことの確認を含む） |
| `test_worker.mjs` | 門番の応対テスト 23本（ネットワークはスタブ） |
| `test_nlweb.mjs` | NLWeb の窓口テスト 20本（自然文で聞いて answer / failure / elicitation） |
| `test_mcp.mjs` | MCP の窓口テスト 24本（握手・tools/list・tools/call・規格どおりのエラー） |
| `build_answers.mjs` | 23区の実測から「整った答え」を作る（`answers/`。文章はここで作らない） |
| `wrangler.jsonc` / `put_answers.sh` | Cloudflare Workers へのデプロイ設定とKV投入 |
| `check_chatgpt_keys.mjs` | ChatGPT の実鍵を取得してパース互換を確認（要ネットワーク） |
| `runtime_check.mjs` / `runtime_client.mjs` | **本番ランタイム(workerd)の上で門番を動かして確かめる**（25本）。素の worker.mjs をそのまま呼ぶ |

## 動かす

```bash
node gatekeeper/test_local.mjs        # 暗号として動く証明（11 PASS）
node gatekeeper/test_worker.mjs       # 門番の応対一周（23 PASS）
node gatekeeper/test_nlweb.mjs        # ★AIが自然文で聞く窓口（20 PASS）
node gatekeeper/test_mcp.mjs          # ★MCPクライアントから同じことを聞く（24 PASS）
node gatekeeper/check_chatgpt_keys.mjs  # ChatGPTの実鍵で形式互換を確認
node gatekeeper/build_answers.mjs     # 23区の実測から「整った答え」を作る
node gatekeeper/demo_talk.mjs         # ★AIと門番のやり取りをそのまま見る
node gatekeeper/demo_demand.mjs       # ★AIを来させて、データができるところを見る
```

Node v24 以上（WebCrypto の Ed25519 が必要）。npm install は不要。

### 本番ランタイム(workerd)で動かして確かめる

上のテストは Node の上で、ネットワークをスタブして動かしている。
実際に乗るのは Cloudflare の workerd なので、そこでも動くことを別に確かめる。

```bash
cd gatekeeper
npx wrangler dev -c runtime_check.wrangler.jsonc --local-protocol https --port 8901
node runtime_client.mjs   # 別の端末から。署名つきの実HTTPリクエストを送る（25 PASS）
```

- `--local-protocol https` は必須（門番は鍵配布を https でしか信用しない）
- ポート8787等は他のプロセスが居座っていることがある。`lsof -nP -iTCP -sTCP:LISTEN` で先に確認
- テスト用の鍵を作り直したら wrangler dev を再起動する（JWKSを1時間キャッシュするため）

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

## 実測で確かめたこと（2026-08-02・本番ランタイム）

- **workerd の上でも Ed25519 がそのまま動く**（標準名 `Ed25519` のまま。書き換え不要）
- **署名つきの実HTTPリクエストに、整った答えが返る**。書かれていない項目を聞かれたら
  `answered=false` を返して記録する（＝主役のデータが実ランタイムで貯まる）
- 期限切れ・鍵の騙りは、実リクエストでも答えを出さない
- workerd から本物の https は取れるが、**wrangler dev の自己署名証明書には繋げない**
  （ローカル固有の制約。本番の相手は必ず本物の https）

詳細: [reports/gatekeeper_runtime_2026-08-02.md](../reports/gatekeeper_runtime_2026-08-02.md)

## まだやっていないこと

- **Cloudflare Workers への実デプロイ**（特典は2026-08-01に申請済み。招待メール待ち）
- **本物のエージェント（ChatGPT等）からの実リクエスト受信確認**。
  いまのデータは、自前の鍵で署名した2体のエージェントを来させた再現（`demo_demand.mjs`）。
  署名検証・記録・集計はすべて実物のコードで動いているが、**本物のAIが来た実データはまだ無い**
- 集めたデータの画面（いまはJSONと、デモの標準出力まで）
