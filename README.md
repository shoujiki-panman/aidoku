# 東京エージェント・レディネス調査

住民のAIエージェントが行政手続きを代行する時代に、東京の区市町村の行政情報が「AIから読めるか」を実測する調査。
都知事杯オープンデータ・ハッカソン2026 応募作品（First Stage 提出 2026-08-23 17:00）。

企画の全体像は [CLAUDE.md](CLAUDE.md) を参照。ここには**動かし方**だけ書く。

## 現在地

Phase 1（パイロット3自治体 × 転入届）でパイプラインが一周した。
→ [reports/phase1_tennyu_2026-07-20.md](reports/phase1_tennyu_2026-07-20.md)

## 動かす

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

1. ~~**採点器の判定がぶれる。**~~ 対策済み（2026-07-22）。原因は「正解/部分正解」の境目に
   *住民が困りうる欠落* という主観語しか置いていなかったこと。判定器から区分選択を取り上げ、
   人手で決めた必須要素ひとつずつに yes/no を答えさせ、点は `10×(yes数÷要素数)` で機械的に出す
   ようにした。before/after を同一入力で測った結果は
   [reports/stability_tennyu_2026-07-22_before.md](reports/stability_tennyu_2026-07-22_before.md) と
   `_after.md` を参照。
   **残る裁量**: どのスロットを必須にするかは人間が決めるので、ぶれが消えたのではなく
   裁量が人間側に移った。`required_elements` 列を公開して裁量を見えるようにしてある。
2. **ルーブリックが自治体とエージェントを混ぜている。** 現在は「サイトに記載がないことを
   正直に報告した」を満点にしている。エージェントの誠実さの評価としては正しいが、
   *自治体*の準備度としては、書いていないこと自体が減点であるべき。

## 採点基準を変えるときの決まり

プロンプトや配点を変えたら、必ずゴールデンセットで再計測してから全体に適用する。
感覚で変えない（CLAUDE.md §5）。
