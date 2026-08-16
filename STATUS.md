# 進捗ボード — AI読（アイドク） 更新: 2026-08-16

> 最初に読む: [START-HERE.md](START-HERE.md)　／　経緯の全記録: [reports/](reports/)

> ## 次の締切: **作品提出 2026-08-23（日）17:00**
> （2026-08-16 19:46 JST 時点で残り約6日21時間）

### 📅 期日一覧

| 日付 | 何 | 状態 |
|---|---|---|
| **8/8ごろ** | Cloudflare特典の**招待メール**（8/1申請済み） | **届いたら3日以内に受諾**。切れると再申請 |
| 8/22・23 | ハッカソン本番 | — |
| **8/23（日）17:00** | **作品提出締切**。過ぎると提出も修正も不可 | **未提出** |
| 8/26〜30 | First Stage プレゼン動画の収録 | 枠の決まり方は**未確認** |
| 9月下旬 | First Stage 審査結果 | — |
| 10/17 | Final Stage・表彰式 | — |
| 未定 | キックオフのLT抽選結果／資料提出期限 | 事務局から**個別案内待ち**（8/3申込済み） |
| **9月末** | KVに貯めた記録のエクスポート期限 | 権限停止後は取り出せない |

## 🎯 作品

**AI読（アイドク）** — あなたの区のサイトを、AIの愛読書に。

自治体サイトのURLを入れると、AIがどこまで読めるかを採点し、**読めない箇所と「直す文面」まで出す**。
デジタル庁OSS「源内」のAIアプリ仕様に準拠し、職員が自分の区の源内で使える形。

## ✅ 動いているもの

| | 状態 |
|---|---|
| 23区の実測（転入届4項目） | ✅ 完了。港区のみ4項目、5区がほぼ読めず、手数料22区で不記載 |
| 採点器 | ✅ 必須要素チェック方式。3自治体12行で測った最大ぶれは2点。**公開23区のぶれは未測定** |
| Evidence Check | ✅ AIの引用を本文と照合。既存73出力は verified 104 / partial 23 / missing 0（この73件内のみ） |
| 判定エンジン `aidoku_engine.py` | ✅ 23区は実測値を即返す／未知URLはその場で取得して判定 |
| 源内API `server.py` | ✅ 仕様準拠（同期・非同期・ポーリング・添付・認証） |
| **源内Web本体がローカルで起動** | ✅ AWS不要（`web:dev`）。AI読が源内のAIアプリとして動作 |
| 源内画面での動作 | ✅ 港区100点／世田谷0点／処方箋／23区のランキング履歴 |
| 動画台本 | ✅ [VIDEO-SCRIPT-aidoku.md](VIDEO-SCRIPT-aidoku.md)（全カット実物・9シーン） |
| **門番の署名検証** [gatekeeper/](gatekeeper/) | ✅ Web Bot Auth (RFC 9421+Ed25519) の署名→検証 14/14 PASS。ChatGPT実鍵で形式互換を確認。[記録](reports/gatekeeper_sigverify_2026-07-31.md) |
| 門番を本番ランタイム(workerd)で実行 | ✅ Ed25519 は標準名のまま動く。[記録](reports/gatekeeper_runtime_2026-08-02.md) |
| 門番の監査と穴埋め | ✅ 落ちる経路2つ・偽の名乗り・黙った打ち切りを修正。[記録](reports/gatekeeper_audit_2026-08-02.md) |
| **AIの聞き方 `POST /ask`（NLWeb準拠）** | ✅ answer / failure / elicitation を規格どおり。[記録](reports/gatekeeper_nlweb_2026-08-02.md) |
| **MCPの窓口 `POST /mcp`** | ✅ JSON-RPC 2.0・ツール `ask` 1本。[記録](reports/gatekeeper_mcp_2026-08-02.md) |
| 門番のテスト | ✅ **78 PASS / 0 FAIL**（local 11 / worker 23 / nlweb 20 / mcp 24） |
| データ画面 [web/demand.html](web/demand.html) | ⚠️ 画面は完成。ただし**本物のAIエージェントの来訪は0件**（`is_sample: true`）。デプロイしないと集まらない |

## ⏭ 残り

**ゴール**: 最初のAI段差を1件消すために必要なものから進める。
PR #80のマージ後、open issue は29件。そのうち提出マイルストーンは
[#55〜#75](https://github.com/shoujiki-panman/aidoku/issues?q=is%3Aissue+is%3Aopen+milestone%3A%22%E4%BD%9C%E5%93%81%E6%8F%90%E5%87%BA%22)
のうち17件（#54・#55・#56・#67・#68は完了）。古い課題も消していない。全件は
[GitHub Issues](https://github.com/shoujiki-panman/aidoku/issues) を正とする。

### いま進める測定基盤

- [#55](https://github.com/shoujiki-panman/aidoku/issues/55) **Evidence Check** — 既存73件の照合まで完了し、PR [#77](https://github.com/shoujiki-panman/aidoku/pull/77) をmainへマージ済み
- [#56](https://github.com/shoujiki-panman/aidoku/issues/56) **測定条件を出力へ記録** — PR [#78](https://github.com/shoujiki-panman/aidoku/pull/78) をmainへマージ済み。既存73件は推測せず `legacy_unknown`
- [#67](https://github.com/shoujiki-panman/aidoku/issues/67) Page Normalizer — 実装・検証完了（PR [#79](https://github.com/shoujiki-panman/aidoku/pull/79)）
- [#68](https://github.com/shoujiki-panman/aidoku/issues/68) Test Caseをfact_type単位に分ける — 最新mainへの統合・検証完了（PR [#80](https://github.com/shoujiki-panman/aidoku/pull/80)）
- [#69](https://github.com/shoujiki-panman/aidoku/issues/69) 回答にconfidenceとevidence_locationを足す
- [#70](https://github.com/shoujiki-panman/aidoku/issues/70) Evaluatorの4判定を揃える
- [#71](https://github.com/shoujiki-panman/aidoku/issues/71) Failure Taxonomyを定義する

### 提出までに外せない確認

- [#3](https://github.com/shoujiki-panman/aidoku/issues/3) プレゼン動画2分の収録と収録枠の予約
- [#63](https://github.com/shoujiki-panman/aidoku/issues/63) 提出前チェック
- [#66](https://github.com/shoujiki-panman/aidoku/issues/66) Cloudflare確認後の主張を提出物へ反映

## ⚠️ 触るときの注意

- **`pkill -f vite` を使わない**。同じマシンの別のViteアプリを巻き添えにする。パスで絞る
- 源内の起動は `web:dev`。**`web:devw` はAWSを要求する**（末尾のwに注意）
- `server.py` のポートは環境変数 `AIDOKU_PORT`。`--port` 引数は**無い**（黙って無視される）
- 源内のフロントは `createdDate` を**エポックミリ秒**で扱う。ISO文字列だと `Invalid time value`
- 源内のチャット画面は動かない（Lambda直叩き構造）。**AIアプリ画面だけ見せる**
- 認証は5行バイパスしている（本家に無い改変）。説明できる範囲に留めてある
- 公開23区の点数は各1回しか測っておらず、ぶれ幅は未測定。**3自治体12行の最大2点と混ぜない**
- `web/assets/barrier.js` だけは `extractor_key` を使う。`display_label` に揃えると `barrier.html` が空欄になる
- `fact_types.json` と `web/data/fact-types.json` は生成スクリプトがなく手動同期。片方だけ直さない

## 📌 この1週間で学んだこと（同じ失敗を繰り返さないため）

1. **「〜のはず」で乗らない。確かめてから乗る。** 6回、前提が崩れた
   （海外の穴6本／母子手帳の空き5件／アトム接点4本／源内の配布経路／処方箋の効き方）
2. **正確さと安定性は別物。** ゴールデンを正確にしたらぶれが増えたことがある
3. **本人が評価できない確認を渡さない。** 機械照合で裏を取って、数字だけ報告する
4. **失敗の記録が資産になる。** 崩れた前提は全部 reports/ に残してある

## 📦 リポジトリ

**https://github.com/shoujiki-panman/aidoku**

- クロールした生HTMLは `.gitignore` で除外（自治体サイトの著作物のため）
- 触ってみたい方は [START-HERE.md](START-HERE.md) の「動かす」から。
  気づいたことは [Issues](https://github.com/shoujiki-panman/aidoku/issues) へどうぞ
