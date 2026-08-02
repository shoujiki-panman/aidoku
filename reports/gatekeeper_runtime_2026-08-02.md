# 門番を本番ランタイム(workerd)で動かした記録 — 2026-08-02

## なぜやったか

7/31 の [gatekeeper_sigverify_2026-07-31.md](gatekeeper_sigverify_2026-07-31.md) で
署名検証は 24 PASS で通っている。ただし**その24本は全部 Node の上で、ネットワークを
スタブして動かしたもの**だった。

門番が実際に乗るのは Cloudflare の **workerd**。WebCrypto の Ed25519 対応も
fetch の挙動も Node と同じとは限らない。ここが違えばデプロイした瞬間に崩れる。
**「Nodeで通ったから Workers でも通るはず」で乗らない**ために、実測した。

デプロイ（＝Cloudflare特典の招待待ち・本人タスク）を待たずにできる確認はここまで。

## やったこと

`wrangler dev`（＝本物の workerd）で門番を起動し、**外から署名つきの実HTTPリクエストを送った**。
test_worker.mjs との違いは「関数を呼ぶ」ではなく「HTTPで送る」こと。
署名ヘッダは実際にネットワークを通り、鍵は門番が JWKS を取りに来て解決する。

```bash
npx wrangler dev -c runtime_check.wrangler.jsonc --local-protocol https --port 8901
node runtime_client.mjs
```

**worker.mjs / httpsig.mjs / demand.mjs には1文字も触っていない。** 足場は新規3本だけ。

## 結果

**18 PASS / 0 FAIL**（3回連続で同じ結果）

| 確認 | 結果 |
|---|---|
| workerd の中で 鍵生成→署名→検証 が一周する | ✅ |
| └ 宛先(authority)を改ざんすると bad-signature | ✅ |
| workerd の中から ChatGPT の実鍵を取得・インポートできる | ✅ |
| └ kid と RFC 7638 指紋が一致 | ✅ |
| **署名つきの実HTTPリクエストに、整った答え(JSON)が返る** | ✅ |
| └ 書いてある項目を聞いたら answered=true | ✅ |
| └ **書かれていない項目を聞いたら answered=false**（主役のデータ） | ✅ |
| └ 空の項目を隠さず null で返す | ✅ |
| 期限切れの署名には整った答えを返さない | ✅ |
| 他人の鍵で keyid を騙っても答えは出ない | ✅ |
| KV(ANSWERS/DEMAND) が workerd 上で読み書きできる | ✅ |
| `/_aidoku/demand` が集計を返し、取れずに帰った探し物が一覧に出る | ✅ |

**これで「Cloudflare の本番ランタイムで動く」は推測ではなく実測になった。**

## 分かったこと（実測して初めて分かった3つ）

### 1. Ed25519 は workerd でそのまま動く

Cloudflare Workers は昔 `NODE-ED25519` という独自名を使っていた時期があり、
標準の `Ed25519` が通るかは実際に動かすまで分からなかった。
`compatibility_date: 2026-07-01` で **標準名のまま通った**。httpsig.mjs の書き換えは不要。

### 2. workerd から本物の https は取れるが、自分の自己署名証明書には繋げない

門番は「鍵配布は https のみ信用する」設計なので、テスト用エージェントの鍵も
https で配る必要がある。ところが `wrangler dev --local-protocol https` の証明書は
自己署名で、**workerd から自分自身を fetch すると `internal error` で落ちる**。

原因を推測で決めず、`/_check/resolve` を足して実際の例外を見て切り分けた:

| 取りに行く先 | 結果 |
|---|---|
| 自分自身 `https://localhost:8901/.well-known/...` | ❌ internal error（自己署名証明書） |
| 本物 `https://chatgpt.com/.well-known/...` | ✅ HTTP 200・鍵を取得 |

→ **ローカル固有の制約であって、門番の欠陥ではない**（本番の相手は必ず本物の https）。
足場側で「自分宛の fetch だけ中で折り返す」ようにして回避した。
**差し替えたのは経路だけで、署名の検証・鍵のインポート・KVの読み書きは素の worker.mjs が実行している。**

### 3. JWKSの1時間キャッシュは、実行のたびに鍵を作ると2回目を落とす

最初は毎回新しい鍵ペアを作っていたので、2回目の実行が全部 `unknown-key` で落ちた。
**バグではなくキャッシュが正しく効いていた**（門番は1時間 JWKS を保持する）。
テスト用エージェントの鍵を固定して、何度流しても同じ結果になるようにした。
本番でも「エージェントが鍵を替えた直後は最大1時間ズレる」ということなので、覚えておく。

## この足場でやっていないこと

- **素通し（署名なし・検証失敗）を実ネットワークで確かめること。**
  本番は「門番の後ろに自治体サイト」だが、この足場では門番が自分の前に立っているため、
  素通しがそのまま自分に戻ってしまう。素通しの挙動は Node の 17本で確認済み
- **本物のエージェント（ChatGPT等）からの実リクエスト受信。** 相手が署名を付けて
  来てくれないと確かめられない。いまのデータは自前の鍵で署名した再現
- **Cloudflare Workers への実デプロイ**（特典の招待待ち・本人タスク）

## ファイル

| ファイル | 中身 |
|---|---|
| `gatekeeper/runtime_check.mjs` | workerd 上の足場。素の worker.mjs をそのまま呼ぶ |
| `gatekeeper/runtime_check.wrangler.jsonc` | 検査用の wrangler 設定（デプロイ用とは別） |
| `gatekeeper/runtime_client.mjs` | 外から署名つきの実リクエストを送る側（18本） |

## ハマりどころ（次に触る人へ）

- **ポート8787・8791・8177 は別の Python プロセスが居座っている**（過去セッションの残骸）。
  巻き添えを避けるため、この検査は **8901** を使う。空きポートは
  `lsof -nP -iTCP -sTCP:LISTEN` で先に確認する
- `--local-protocol https` は必須。http だと門番が鍵配布を信用せず `unknown-key` になる
- テスト用エージェントの鍵を作り直したら、**wrangler dev を再起動する**（1時間キャッシュ）
- `gatekeeper/.wrangler/` はローカル状態（KVの中身・証明書）。`.gitignore` 済み
