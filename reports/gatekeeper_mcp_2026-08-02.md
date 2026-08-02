# MCP の窓口を足した — 2026-08-02

## なぜ足したか

NLWeb は「**各インスタンスがMCPサーバーにもなる**」規格で、[NLWeb を Cloudflare Workers に
載せる公式の手順](https://blog.cloudflare.com/conversational-search-with-nlweb-and-autorag/)でも
`/ask` と `/mcp` の2本を持つWorkerになっている。`/ask` だけだと規格の半分。

そして「エージェント同士の会話」という観点では、こちらが本体に近い。
MCPクライアント（Claude 等）から、この門番が**そのままツールとして見える**ようになる。

## 公式の形をそのまま再現した

自分でツール名や引数を決めない。両方の仕様に書いてあるとおりにした。

| どこ | 何が決まっていたか |
|---|---|
| NLWeb 仕様 Appendix A | ツール名は **`ask`**、引数は **`query`（必須）/ `context` / `prefer` / `meta`** |
| NLWeb 仕様 Appendix C.1 | MCPの返答には、HTTPの `/ask` と**同じNLWebレスポンスをそのまま入れる** |
| MCP 2025-06-18 | JSON-RPC 2.0。`initialize` / `tools/list` / `tools/call` / `ping`。通知は返事をしない |
| MCP 2025-06-18 | 版が合わなければ、サーバーは**自分が対応している版を返す** |
| MCP 2025-06-18 | 構造化して返す場合も、**後方互換のため `text` にも同じJSONを入れる** |

## 判断したこと

**`isError` を「そのページに書かれていなかった」に使わない。**

MCP の `isError` は「ツールが実行できなかった」ときの印。
`NO_RESULTS`（そのページには書かれていない）は**正しい答え**であって失敗ではないので、
`isError: false` のままにした。ここを `true` にすると、
主役のデータ（「取れずに帰った」）がクライアント側でエラー扱いされて捨てられる。

`isError: true` にするのは `INVALID_QUERY`（そもそも質問になっていない）だけ。

**答え方も数え方も、口によって変えない。**
`/ask`（HTTP）と `/mcp`（MCP）と `?q=`（旧）は同じ中身を呼ぶ。
記録の `via` が `nlweb` / `mcp` / `query` に分かれるだけで、
`answered` の数え方も、署名なしを記録しない原則も同じ。

## テスト

| | 本数 |
|---|---|
| `test_local.mjs`（暗号・落ちない保証） | 11 |
| `test_worker.mjs`（門番の応対・数え方） | 23 |
| `test_nlweb.mjs`（自然文で聞く窓口） | 20 |
| **`test_mcp.mjs`（MCPの窓口）** | **24** |
| `runtime_client.mjs`（workerd 上の実HTTP。`/ask` と `/mcp` を含む） | 25 |
| **合計** | **103 PASS / 0 FAIL** |

MCP側で確かめたこと: 握手／版が合わないときの返し方／通知に本文を返さない（202）／
`tools/list` が `ask` を返す／`tools/call` が answer・failure・elicitation を返す／
知らないツールは `-32602`・知らないメソッドは `-32601`・壊れたJSONは `-32700` で
**門番が落ちない**／署名なしは記録しない／MCP経由の質問も同じ更新依頼リストに出る。

`/mcp` は Node のテストだけでなく、**本番ランタイム(workerd)上に実HTTPで投げても
握手・`tools/list`・`tools/call` が通る**ことを確認済み。

## まだやっていないこと

- **本物のMCPクライアントからの接続確認**。いまのテストは自分でJSON-RPCを組み立てている。
  実際に Claude 等から繋ぐには、公開URL（＝Cloudflareへのデプロイ）が要る
- SSE / Streamable HTTP の通知ストリーム。いまは1リクエスト＝1レスポンスだけ
- `site` を省略されたときの既定ページ
