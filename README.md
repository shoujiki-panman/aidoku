# AI読（アイドク）

**あなたの区のサイトを、AIの愛読書に。**

自治体サイトのURLを入れると、AIがどこまで読めるかを採点し、**読めない箇所と「直す文面」まで出す**。
デジタル庁OSS「源内」のAIアプリ仕様に準拠し、職員が自分の区の源内で使える形にしている。

都知事杯オープンデータ・ハッカソン2026 応募作品（エントリー 7/27 17:00 / 提出 8/23 17:00）。

- はじめて読むなら → [START-HERE.md](START-HERE.md)
- いまの進捗 → [STATUS.md](STATUS.md)
- 実測と調査の記録 → [reports/](reports/)
- 企画の仕様（初期版） → [CLAUDE.md](CLAUDE.md)

## 実測でわかっていること（2026-07-22・東京23区・転入届）

- 4項目（必要書類・窓口/オンライン可否・期限・手数料）すべて読み取れたのは **港区だけ**
- **5区**（世田谷・中央・台東・墨田・荒川）はほとんど読み取れない
- 手数料は **22区** で見つからない（実際は無料）

## 構成

| ディレクトリ | 役割 |
|---|---|
| `gennai_app/` | **作品本体**。源内AIアプリとして動く判定API（[README](gennai_app/README.md)） |
| `crawler/` | 取得層。robots.txt遵守・3秒間隔・キャッシュ。ここだけが外に触る |
| `extractor/` | 読解層。`claude -p` で4項目を抽出 |
| `scorer/` | 採点層。人手で決めた必須要素と突合。ぶれ幅 ±2点 |
| `web/` | ダッシュボード（デジタル庁デザインシステム） |
| `reports/` | 実測・調査の全記録（崩れた探索も残してある） |
| `docs/archive/` | 使わなくなったもの |

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

# 2. 4項目の抽出（--follow でリンク先1階層まで追う）
python3 extractor/extract.py -p tennyu --follow

# 3. ゴールデンセットと突合して採点
python3 scorer/score.py -p tennyu

# 4. 1枚のレポートに出力
python3 scorer/report.py -p tennyu

# 5. ダッシュボード用のJSONを書き出す
python3 analysis/export_web.py -p tennyu
```

ダッシュボードは `web/` の静的ファイル。ローカルで見るには `web/` を配信する。

```bash
python3 -m http.server 4173 --directory web
```

デプロイ先は Cloudflare Pages 想定（ビルド不要・出力ディレクトリ = `web/`）。

再実行しても自治体サイトには一切アクセスしない（`crawler/cache/` から返る）。
取り直したいときだけ `python3 crawler/polite_fetch.py <URL> --refresh`。

## クロールの作法（変更しないこと）

- robots.txt を読み、Disallow なら取得しない。robots.txt が読めない場合は取得しない
- 同一ドメインへのリクエスト間隔 3秒以上（robots の Crawl-delay がそれより長ければ従う）
- User-Agent にプロジェクト名と連絡先を明記 — `crawler/polite_fetch.py` の `CONTACT` を
  **公開前に自分の連絡先へ差し替える**
- 一度取得したページは再取得しない
- 申請の送信・フォーム送信・脆弱性の探索は実装しない（Layer C として禁止）

## ディレクトリ

| 場所 | 役割 |
|---|---|
| `crawler/` | 取得層。`polite_fetch.py`（行儀のよいfetcher）、`discover.py`（情報到達の測定）、`targets.json` |
| `crawler/cache/` | 生HTML。再実行はここから。Git管理外 |
| `crawler/out/` | 探索結果（候補ページとホップ数、取得ログ） |
| `extractor/` | 読解層。`prompt.md` が抽出プロンプト本体 |
| `scorer/` | 採点層。`golden/*.csv` が人手の正解、`judge_prompt.md` が採点プロンプト |
| `reports/` | 突合表つきレポート |
| `analysis/` | 集計。`export_web.py` がダッシュボード用JSONを作る |
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
感覚で変えない（CLAUDE.md §5）。
