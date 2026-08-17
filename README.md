# AI読（アイドク）

**あなたの区のサイトを、AIの愛読書に。**

自治体サイトのURLを入れると、AIがどこまで回答できるかを測り、**回答・根拠・正解を4判定で検証する**。
デジタル庁OSS「源内」のAIアプリ仕様に準拠し、職員が自分の区の源内で使える形にしている。

都知事杯オープンデータ・ハッカソン2026 応募作品（提出 2026-08-23）。

## 触ってみる

### 1. ブラウザで見る（設定不要）

**https://shoujiki-panman.github.io/aidoku/**

東京23区の実測結果がそのまま見られます。自治体名を選ぶと、
**AIが読み取った実際の文**と、**どこを直せば回答が変わるか**が出ます。
旧データはGround Truthが揃っていないため、回答文は表示し、正解点は「未検証」と明記します。

### 2. 手元で動かす

Python 3.10 の標準ライブラリだけで動きます。判定に Claude Code の `claude -p` を使うので、
Claude Code にログイン済みであれば APIキーは要りません。

```bash
cd gennai_app
AIDOKU_PORT=8791 python3 server.py

# 別のターミナルから
curl -X POST http://127.0.0.1:8791/invoke \
  -H "x-api-key: dev-local-key" \
  -d '{"inputs":{"url":"https://www.city.minato.tokyo.jp/shibamadosa/kurashi/todokede/hikkoshi/tennyu.html"}}'
```

23区の実測済みURLは即座に返ります。

**それ以外のURLを試すには Claude Code が必要です**（`claude -p` を呼ぶため）。
その場で取得して判定するので30〜60秒かかります（robots.txt遵守・3秒以上の間隔）。
Claude Code が無い環境では、23区の実測結果のみ返ります。

**気づいたこと・動かなかったことは [Issues](https://github.com/shoujiki-panman/aidoku/issues) へどうぞ。**
使い勝手の課題は既に7件挙げてあります（`Phase B` ラベル）。

## ドキュメント

- 公開ダッシュボード → https://shoujiki-panman.github.io/aidoku/
- はじめて読むなら → [START-HERE.md](START-HERE.md)
- いまの進捗 → [STATUS.md](STATUS.md)
- 実測と調査の記録 → [reports/](reports/)

## 実測でわかっていること（2026-07-21〜08-05・東京23区・転入届）

- 4項目（必要書類・窓口/オンライン可否・期限・手数料）すべてAI回答が返ったのは **港区だけ**
- **5区**（世田谷・中央・台東・墨田・荒川）はほとんど回答が返らない
- 手数料は **22区** でAI回答が無い（実際は無料）
- これは回答有無の観測で、正解確認済み件数ではない。4判定が未完了の値は点にしない

## 門番（gatekeeper）— 来たエージェントに答え、取れなかったものを記録する

住民のAIエージェントが行政サイトへ**代わりに来る**ことを前提にした前段レイヤー。
署名（Web Bot Auth）でエージェントを見分け、HTMLの代わりに整った答えを返す。
**人（ブラウザ）は記録しない。**

| 窓口 | 何 |
|---|---|
| `POST /ask` | [NLWeb](https://nlweb.ai/docs/specification) 準拠。`answer` / `failure` / `elicitation` を規格どおり返す |
| `POST /mcp` | MCP（JSON-RPC 2.0）。ツールは NLWeb 仕様の `ask` 1本 |
| `web/demand.html` | 集めたものの画面「AIが取れずに帰ったもの」 |

**主役のデータは「取れなかった」の方**。サーバーログには「来た」しか残らず、
**「来たが答えを見つけられずに帰った」はどこにも記録されていない**。

> ⚠️ 現在、**本物のAIエージェントの来訪は0件**。画面に出ている数字は自分で作った見本で、
> JSON に `"is_sample": true` が付いている。デプロイするまで本物は集まらない。

詳しくは [gatekeeper/README.md](gatekeeper/README.md)。テストは **78 PASS / 0 FAIL**。

## 門番を置いてみたい方へ（サイトを持っている方）

門番は**サイトの持ち主がサーバーの前に置いて初めて動く**。他人のサイトには置けないし、置かない。
だから、いま一番ほしいのは**置かせてくれる1サイト**。まだ本物の来訪は0件で、
「本物のAIエージェントがどう来るのか」は誰も観測していない。

置いたときに門番がすることは、これだけ。

- 記録するのは3つ — **どのAIか**（署名を検証）／**何を探しに来たか**／**答えられたか**
- **人のアクセスは記録しない。** 署名なしは記録処理に入る前に素通しする
- 記録するのは**AIが送ってきた質問文**。集計画面は現在いっさい認証をかけておらず、
  質問文の中身も選別していない（**置く前に必ず塞ぐ**。下の「置く前に直すこと」）
- **拒否しない。** 署名の検証に失敗しても素通しする。サイトの動作を止めない
- 他人の名を騙れない。検証に成功したときだけ名前を記録する

置くもの: Cloudflare Workers 1本（手順は [gatekeeper/README.md](gatekeeper/README.md) のデプロイ節）。

### 置く前に直すこと（正直に書いておく）

まだ本物のサイトに置ける状態ではない。**声をかけてもらえたら、まずここを塞いでから置く。**

| | いまの状態 |
|---|---|
| 集計画面 `/_aidoku/demand` | **認証なしで誰でも読める。**レート制限も無い |
| 記録する質問文 | AIが送ってきた自然文がそのまま入る。**個人情報の選別をしていない** |
| 署名が守る範囲 | 宛先ホストと名乗りだけ。パス・本文・クエリは署名対象外。**リプレイ防止も無い** |
| `/ask`・`/mcp` | 署名が無くても答える（記録だけ止めている） |
| 書き込み失敗 | KVへの追記に失敗しても**誰にも見えない**（例外を握っている） |

門番が**拒否せず・落ちない**ことは実装済み（検証全体を try/catch で囲み、鍵取得は2秒で打ち切る）。
サイトの動作を止めない側の作りは先に固めてある。

**試したい方・話を聞きたい方は [Issues](https://github.com/shoujiki-panman/aidoku/issues) へ。**
自分のサイトが無くても観測はできる。区のページの写しを**自分のドメイン**に置いて、
その前に門番を立て、実際のAIに調べさせる方法がある（他人のサイトには一切触れない）。

## 構成

| ディレクトリ | 役割 |
|---|---|
| `gennai_app/` | **作品本体**。源内AIアプリとして動く判定API（[README](gennai_app/README.md)） |
| `gatekeeper/` | **門番**。自治体サイトの前に立ち、AIエージェントに答えを返して「取れずに帰った」を記録（[README](gatekeeper/README.md)） |
| `crawler/` | 取得・正規化層。robots.txt遵守・3秒間隔・キャッシュ。title・meta・見出し・更新情報も構造化する。ここだけが外に触る |
| `extractor/` | 読解層。`claude -p`をfact_typeごとに独立して呼び、4項目を抽出 |
| `evaluator.py` | 回答・Evidence実在・Evidence支持・Ground Truth一致の4判定を集約 |
| `scorer/` | 人手で決めた必須要素との突合とEvidence支持判定。ぶれ幅 ±2点は既存3自治体だけ |
| `web/` | ダッシュボード（デジタル庁デザインシステム） |
| `reports/` | 実測・調査の全記録（崩れた探索も残してある） |

## 動かす

### 作品（源内AIアプリとして）

```bash
cd gennai_app
AIDOKU_PORT=8791 python3 server.py &     # AI読API（判定エンジン）
python3 stub_backend.py &                # 源内バックエンドの代わり
# 源内Webフロントは別途クローンして  npm run web:dev  （web:devw ではない）
python3 seed_history.py                  # デモ用: 23区の履歴を積む
```

詳しくは [gennai_app/README.md](gennai_app/README.md)。

### 調査パイプライン（判定の中身を作る側）

外部ライブラリは使わない（Python 3.10 標準ライブラリのみ）。LLM は `claude -p` を呼ぶので、
Claude Code にログイン済みであれば APIキーは要らない。

```bash
# 1. 取得＋情報到達の測定（トップページから深さ3までビーム探索）
python3 crawler/discover.py -m nerima -m edogawa -m hachioji -p tennyu

# 2. 4項目を独立したTest Caseで抽出（--followで各項目のリンク先を追う）
python3 extractor/extract.py -p tennyu --follow

# 3. 失敗理由を8種の共通分類へ再分類し、分布を出す
python3 analysis/failure_distribution.py

# 4. 既存の抽出結果も、AIが読んだ本文と引用を照合（元ファイルは上書きしない）
python3 analysis/apply_evidence_check.py

# 5. ゴールデンセットと突合し、4判定Evaluatorを記録
python3 scorer/score.py -p tennyu

# 6. 4判定を通った値だけ公開点へ変換（未判定はnull）
python3 analysis/export_dashboard.py -p tennyu --out web/data/scores-tennyu.json

# 7. 1枚のレポートに出力
python3 scorer/report.py -p tennyu
```

ダッシュボードは `web/` の静的ファイル。ローカルで見るには `web/` を配信する。

```bash
python3 -m http.server 4173 --directory web
```

デプロイ先は Cloudflare Pages 想定（ビルド不要・出力ディレクトリ = `web/`）。

再実行しても自治体サイトには一切アクセスしない（`crawler/cache/` から返る）。
取り直したいときだけ `python3 crawler/polite_fetch.py <URL> --refresh`。

抽出は1回のLLM呼び出しに1つの`service × fact_type`だけを入れる。通常は1回、
`--follow`で「リンク先にあり」と返した項目だけ同じTest Caseをもう1回呼び、全callを
`attempts[]`へ残す。追従先がPDF等だった場合は本文を読まず`llm_called: false`の
観測attemptとして区別する。各結果には質問と`test_case_version`も残す。従来の`items`は
最後のattemptと同じ値から生成するため、採点・公開画面の入力形式は変わらない。
失敗項目にはLLMの日本語`failure_reason`を残したまま、8種の共通`failure_type`を
コードで付ける。定義と既存語彙の対応は
[`docs/failure-taxonomy.md`](docs/failure-taxonomy.md)を参照。
採点は `evaluator.py` の4判定をすべて通った項目だけ20点にする。1つでも失敗なら0点、
必要な判定が未実施なら `null`（未検証）で、`found=true`だけでは点を付けない。

## クロールの作法（変更しないこと）

- robots.txt を読み、Disallow なら取得しない。robots.txt が読めない場合は取得しない
- 同一ドメインへのリクエスト間隔 3秒以上（robots の Crawl-delay がそれより長ければ従う）
- User-Agent にプロジェクト名と連絡先を明記（`crawler/polite_fetch.py` の `CONTACT`）。
  **フォークして自分でクロールする場合は、必ず自分の連絡先に差し替えること**
- 一度取得したページは再取得しない
- 申請の送信・フォーム送信・脆弱性の探索は実装しない（Layer C として禁止）

## ディレクトリ

| 場所 | 役割 |
|---|---|
| `crawler/` | 取得層。`polite_fetch.py`（行儀のよいfetcher）、`discover.py`（情報到達の測定）、`targets.json` |
| `crawler/cache/` | 生HTMLとHTTPメタデータ。再実行はここから。Git管理外 |
| `crawler/out/` | 探索結果（候補ページ・ホップ数・title/meta/見出し/更新情報・取得ログ） |
| `extractor/` | 読解層。`fact_extract.py`がfact_typeごとの呼び出し、`prompt.md`が1項目用プロンプト |
| `evidence_check.py` | AIの引用が、実際に渡した本文に存在するか照合 |
| `measurement.py` | 測定条件を記録し、条件の違う結果が同じ集計へ混ざるのを防止 |
| `failure_taxonomy.py` | 失敗を8種へ変換する共通のPure Function |
| `evaluator.py` | 4判定を厳格に集約し、pass=20 / fail=0 / 未検証=nullを決めるPure Function |
| `experiment/` | 再現実験。本測定と同じ1 fact_typeずつのpromptで手元HTMLを反復測定 |
| `scorer/` | 採点層。`golden/*.csv` が人手の正解、`judge_prompt.md` が採点プロンプト |
| `reports/` | 突合表つきレポート |
| `analysis/` | 集計。`failure_distribution.py` が失敗分布、`export_dashboard.py` が公開JSONを作る |
| `web/` | ダッシュボード。`vendor/dads/` はデジタル庁デザインシステムの複製（[NOTICE](web/vendor/dads/NOTICE.md)） |
| `personas/` `trust_check/` | Phase 2 以降。Phase 1 では触らない |

## 未解決（Phase 2 に入る前に決着させる）

1. **採点器の判定のぶれ — 大幅に縮小、ただし未解決（2026-07-22）。** 原因は「正解/部分正解」の
   境目に *住民が困りうる欠落* という主観語しか置いていなかったこと。判定器から区分選択を
   取り上げ、人手で決めた必須要素ひとつずつに yes/no を答えさせ、点は `10×(yes数÷要素数)` で
   機械的に出すようにした。さらに全28スロットを原典と突き合わせて監査し13スロットを書き直した
   （[reports/slot_audit_tennyu_2026-07-22.md](reports/slot_audit_tennyu_2026-07-22.md)）。
   合計点のふれ幅は ±15点 → ±2〜6点。測定は `reports/stability_tennyu_2026-07-22_before.md` /
   `_after.md` / `_after2.md` の3本。
   **残る揺れは1点に絞れている**: エージェントが条件を圧縮した答えに対し、判定器ルール4
   （条件・数量まで読み取れるときだけ yes）をどこまで厳密に当てるか。ここの線引きは
   設計判断として STATUS.md に選択肢を書いた。
   **残る裁量**: どのスロットを必須にするかは人間が決める。ぶれが消えたのではなく裁量が
   人間側に移った。`required_elements` 列を公開して裁量を見えるようにしてある。
2. **ルーブリックが自治体とエージェントを混ぜている。** 現在は「サイトに記載がないことを
   正直に報告した」を満点にしている。エージェントの誠実さの評価としては正しいが、
   *自治体*の準備度としては、書いていないこと自体が減点であるべき。

## 採点基準を変えるときの決まり

プロンプトや配点を変えたら、必ずゴールデンセットで再計測してから全体に適用する。
感覚で変えない。


## この作品について

- 判定の対象は**実在の公開情報のみ**。申請の送信や個人情報の取り扱いは行いません
- スコアは自治体を非難するためのものではなく、**どこを直せば伝わるか**を示すためのものです
- 判定基準（`scorer/golden/*.csv` の `required_elements`）を公開しています。
  基準を隠さないことで、結果を検証でき、同じ物差しで再測定できます
- **行政機関の公式発表ではありません。** 個人による調査・開発です
- デジタル庁OSS「源内」の**AIアプリAPI仕様（2026年3月版）に準拠**しています。
  源内本体に採用されたものではありません

## ライセンス

MIT（[LICENSE](LICENSE)）。`web/vendor/dads/` はデジタル庁デザインシステムの複製で、
その利用条件は [NOTICE](web/vendor/dads/NOTICE.md) を参照してください。
