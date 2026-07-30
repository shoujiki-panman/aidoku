# 門番の署名検証を実際に動かした記録 — 2026-07-31

## 何を確かめたか

門番構想（自治体サイトの前段で、署名つきAIエージェントを見分けて応対する）の
**土台＝Web Bot Auth の署名検証が、この手元のコードで暗号として動くか**。
ここが壊れたら構想全体が崩れるので、最初にここだけを検証した。

実装は `gatekeeper/`（RFC 9421 の最小実装 `httpsig.mjs` ＋ Worker形の門番 `worker.mjs`）。
依存は WebCrypto のみ。Node v24.16.0 で実測（＝Cloudflare Workers と同じAPI面）。

## 結果の要約

| 確認 | 結果 |
|---|---|
| 自前 Ed25519 鍵で 署名→検証 | ✅ 通る |
| 改ざん・騙り・期限切れの拒否 | ✅ 4パターン全部正しく落ちる |
| ChatGPT の実鍵のインポート | ✅ 成功（WebCrypto / Ed25519） |
| **kid = RFC 7638 指紋 の一致** | ✅ **完全一致**（keyid規約の読みが正しい証明） |
| 門番の応対（答える/素通し/記録） | ✅ 7ケース全部想定どおり |

**テスト合計 14/14 PASS。**

## 1. 暗号テスト（`test_local.mjs` — 7 PASS）

自前で Ed25519 鍵ペアを作り、Web Bot Auth の形（署名対象 = `@authority` + `signature-agent`、
tag=`web-bot-auth`）で署名→検証を一周させた。

| ケース | 期待 | 結果 |
|---|---|---|
| 正しい署名 | verified | ✅ |
| 宛先(authority)を世田谷→港に改ざん | bad-signature | ✅ |
| 名乗り(signature-agent)を改ざん | bad-signature | ✅ |
| 期限切れ(expires超過) | expired | ✅ |
| 未知の keyid | unknown-key | ✅ |
| 署名なし（普通のブラウザ） | no-signature | ✅ |
| **他人の鍵で本物の keyid を騙る** | bad-signature | ✅ |

→ **User-Agent 偽装と違い、署名は宛先・名乗り・鍵の全部に縛られている**ことを実測で確認。

## 2. ChatGPT の実鍵での形式互換（`check_chatgpt_keys.mjs`）

```
GET https://chatgpt.com/.well-known/http-message-signatures-directory
HTTP 200 application/http-message-signatures-directory+json
鍵: 1本 (OKP / Ed25519)
kid: otMqcjr17mGyruktGvJU8oojQTSMHlVm7uO-lrcqbdg
```

- WebCrypto へのインポート: **成功**
- この実装で計算した RFC 7638 指紋: `otMqcjr17mGyruktGvJU8oojQTSMHlVm7uO-lrcqbdg` → **kid と完全一致**
- ディレクトリには `signature_agent: "https://chatgpt.com"` と `purpose: "ai"` も入っていた
- 検証呼び出しは例外なく動く（ダミー署名は false）

※ 7/30 の引き継ぎに書いた kid「otMqcjr17mGyruktGvJU8ooj」は**途中で切れていた**。正しくは上記43文字。

## 3. 門番の応対テスト（`test_worker.mjs` — 7 PASS）

ネットワークをスタブし、Worker 本体の `fetch` を4シナリオで一周：

| 来訪者 | 門番の応対 | 結果 |
|---|---|---|
| 署名つき＋答えがあるページ | 整った答え(JSON)を返す＋記録 | ✅ |
| 署名なし（人間） | 素通し・**記録しない** | ✅ |
| 検証失敗（偽の名乗り） | 素通し（拒否しない）・verified=false で記録 | ✅ |
| 署名つきだが答えが未整備 | 素通し＋記録 | ✅ |

記録レコードの形（これが「新しいオープンデータ」の種）:

```json
{
  "ts": "2026-07-31T…",
  "verified": true,
  "agent": "https://agent.example",
  "keyid": "…",
  "authority": "www.city.setagaya.lg.jp",
  "path": "/kurashi/tetsuduki/tennyu.html",
  "looking_for": "転入届 必要書類"
}
```

### テストで見つけて直したバグ

名乗ったオリジンが実在しない場合（偽エージェント）、JWKS取得の `fetch` が例外を投げて
**門番ごと落ちていた**。try/catch で握って unknown-key 扱いに修正。
→ 「検証失敗でも素通し（サイトを壊さない）」という設計原則がテストで守られた。

## 設計上の決め（今日の時点）

1. **門番は拒否しない。** 検証失敗も署名なしも素通し。自治体サイトの可用性に一切影響しない
2. **人間は記録しない。** 署名なしアクセスはログも取らない（住民のデータは集めない）
3. **鍵配布は https のみ信用**。JWKS は1時間キャッシュ
4. 整った答えの中身は **AI読 の実測データ（必須要素ごとの実文）をそのまま流用**する設計

## 追記（2026-07-31・立ち位置の確定を受けて）

別セッションの市場調査で立ち位置が確定した（詳細は `outputs/handoff-aidoku-2026-07-30.md` の更新分）:

- **402課金（通行料）は AWS WAF（2026-06提供開始・x402+USDC）／Cloudflare／Akamai の標準機能**。作る場所ではない
- **AEO（AIから見た自社の可視化）は評価額1000億円企業（Profound等）の土俵**。模擬質問ベースで、実トラフィックは見ていない
- 空いているのは **「AIが来て、答えを見つけられずに帰った」の実記録**。ここが我々の実測（22区で手数料不記載）と直結し、大手もAEO企業も作らないデータ

これを受けて記録レコードを改訂した（テスト8本に増補・全PASS）:

```json
{
  "looking_for": "戸籍謄本 手数料",   ← 何を探しに来たか（主役）
  "answered": false,                  ← 取れた/取れずに帰った（主役）
  "verified": true, "agent": "…", "authority": "…", "path": "…"
}
```

`answered` は検証済みエージェントのみ意味を持つ（署名なしは記録自体しない）。

## まだやっていないこと（次の一手）

- Cloudflare Workers への実デプロイ — **参加者特典の申請（本人タスク）が先**
- 記録先の永続化（console.log → Workers Analytics Engine / KV）
- ANSWERS への実データ投入（23区×転入届の実測が既にあるので変換だけ）
- 本物のエージェントからの実リクエスト受信（ChatGPT の Operator 等が署名を付けてくる相手が必要）
