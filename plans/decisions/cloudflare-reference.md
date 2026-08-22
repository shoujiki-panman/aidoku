# Cloudflare 完全ガイドを、ハーネスの実装リファレンスに置く

Status: 参考として確保（2026-08-22）。**今回の提出では使わない**
関連: [`plans/measurement-harness.md`](../measurement-harness.md)、[`api-layer-from-michiyomi.md`](api-layer-from-michiyomi.md)

## 何を確保するか

宮田（@miyataArcHack）「Cloudflare完全ガイド」
https://note.com/miyata_archack/n/n2eb6da4d2cc8 — 全23章・約23万字・単一HTML。

**取得済み（2026-08-22、本人がリポストで入手）。**

| | |
|---|---|
| 原本 | `~/Downloads/cloudflare_complete_edition.html` |
| 本文だけ抜いたもの | `<repo親>/references/cloudflare_complete_edition.text.md` |

**原本は 156MB あり、その 99.6% が base64 で埋め込まれた図です。**
本文は 0.6MB しかありません。「AIに読ませる前提の単一HTML」という触れ込みですが、
**156MB はどのAIの文脈にも入らない**ので、そのままでは読ませられません。
図を落として本文だけ抜いた 517KB の版を references に置いてあり、
実装フェーズで読むのはそちら（23章・コード片134個・図の位置46箇所を保持）。

**どちらも公開リポジトリには置きません。** 有料コンテンツなので、
`agent-readiness/` の中に入れると GitHub Pages が配信してしまいます。
置き場はリポジトリの親（git 管理外）です。

同梱の `<script>` は目次の絞り込みとコードのコピーボタンだけで、
`fetch` も `eval` もありません（511字、確認済み）。

## ハーネスのどこに効くか

[`measurement-harness.md`](../measurement-harness.md) の **⑤実行場所** に、
4つ目の案として入ります。

| 章 | ハーネスのどこ |
|---|---|
| 14 / 15（MCPとは・ネット越しの道具箱） | 採点エンジンのリモートMCP公開 |
| 18（必要な権限だけ渡す） | read-only 公開の設計。`api-layer-from-michiyomi.md` で「新規測定は受け付けない」と決めた部分の実装 |
| 9 / 11 / 12（Workers・保存場所・Queues/Workflows） | 23区 → 全国1,741 のクロールを非同期バッチで回す。②再開可能なランナーの置き換え先 |
| 10 / 22 / 21 | 運用と、AIがWebを使う時代の前提 |

**ただし、これで ⑤ の分岐が消えるわけではありません。**
判定は `claude -p`（Claude Code CLI）で、**Cloudflare Workers では動きません**。
Workers に持っていくなら Anthropic API に切り替えることになり、
それは `measurement-harness.md` の案A（CI + APIキー）と同じ選択です。
つまりこのガイドが教えてくれるのは**案Aの実装方法**であって、
「サブスク認証のまま無人で回す」問題は解きません。そこは案B
（セルフホストランナー）のままです。

クロール側（LLMを呼ばない部分）は話が別で、Queues / Workflows へ移す価値があります。
毎日の見張りは既に GitHub Actions で回っているので、置き換えの必然性は
**全国規模に行くと決めてから**。

## 配布形態（B）について

「23万字を人間が頭から読ませず、AIに読ませる前提の単一HTMLにする」という形は、
主張と成果物の形式を一致させる考え方として正しい。

**ただしAI読では、同じ狙いは別の形で既に満たしています。**

| | AI読での実装 |
|---|---|
| AIが最初に読む1枚 | `web/data/index.json`（機械可読な目次。件数・被覆・来歴・較正の欠けまで） |
| AIへの使い方の指示 | `web/skill/SKILL.md` |
| 本文をAIに渡す導線 | 各ページの「AIに渡して調べる」ボタン |

単一HTMLは**長文記事**にとって最良の形で、AI読の成果物は長文記事ではありません。
23区の結果は既に構造化データで、散文に戻すと**むしろAIから読みにくくなります**。

提出まで残り約1日で、フォームも未送信です。**3つ目の配布形式を今から足すのは
割に合いません。** 通過後、報告書という形の成果物を作るときに、この形を採ります。
