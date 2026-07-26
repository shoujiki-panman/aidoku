# 進捗ボード — AI読（アイドク） 2026-07-26

> 最初に読む: [START-HERE.md](START-HERE.md)　／　経緯の全記録: [reports/](reports/)

> ## ✅ エントリーは**済んでいる**（2026-07-08時点で事務局メールが「エントリーされた皆様へ」宛て）
> Slackワークスペースにも参加済み。7/27の締切は未エントリー者向けだった。
>
> ## 🚨 次の締切: **作品提出 8/23（日）17:00**
> - 提出フォーム: https://form.jotform.com/261870604352051
> - 提出ガイド: https://drive.google.com/file/d/15TPprqBEkUK6MMs0vj8FNGf7MVicAQLV/view
> - **プレゼン動画の収録予約もこのフォームから**（8/26〜30オンライン／8/29都内会場・**30分枠の早い者順**）
> - ハッカソン本番は 8/22・23

## 🎯 作品

**AI読（アイドク）** — あなたの区のサイトを、AIの愛読書に。

自治体サイトのURLを入れると、AIがどこまで読めるかを採点し、**読めない箇所と「直す文面」まで出す**。
デジタル庁OSS「源内」のAIアプリ仕様に準拠し、職員が自分の区の源内で使える形。

## ✅ 動いているもの

| | 状態 |
|---|---|
| 23区の実測（転入届4項目） | ✅ 完了。港区のみ4項目、5区がほぼ読めず、手数料22区で不記載 |
| 採点器 | ✅ 必須要素チェック方式。ぶれ幅 ±15点 → **±2点** |
| 判定エンジン `aidoku_engine.py` | ✅ 23区は実測値を即返す／未知URLはその場で取得して判定 |
| 源内API `server.py` | ✅ 仕様準拠（同期・非同期・ポーリング・添付・認証） |
| **源内Web本体がローカルで起動** | ✅ AWS不要（`web:dev`）。AI読が源内のAIアプリとして動作 |
| 源内画面での動作 | ✅ 港区100点／世田谷0点／処方箋／23区のランキング履歴 |
| 動画台本 | ✅ [VIDEO-SCRIPT-aidoku.md](VIDEO-SCRIPT-aidoku.md)（全カット実物・9シーン） |
| エントリー文 | ✅ [ENTRY-DRAFT.md](ENTRY-DRAFT.md)（302/334/234字） |

## ⏭ 残り

**ゴール**: 区の担当者が「開いて、直して、確かめた」までを迷わず一周できること。
フェーズと課題の全体像は [KICKOFF.md](KICKOFF.md)、個々の作業は
**[GitHub Issues](https://github.com/shoujiki-panman/aidoku/issues)** に切ってある。

### Phase A — 出せる状態にする（最優先）
- [#1](https://github.com/shoujiki-panman/aidoku/issues/1) 画面キャプチャ3枚（1600×900）
- [#2](https://github.com/shoujiki-panman/aidoku/issues/2) デモ操作動画（60秒・無音）
- [#3](https://github.com/shoujiki-panman/aidoku/issues/3) **プレゼン動画の収録と枠の予約** ← 早い者順
- [#4](https://github.com/shoujiki-panman/aidoku/issues/4) 提出ガイドで著作物の条件を確認
- [#15](https://github.com/shoujiki-panman/aidoku/issues/15) 提出前チェックリスト

### Phase B — 使い勝手を極める（本丸）
- [#5](https://github.com/shoujiki-panman/aidoku/issues/5) 判定中の進捗が見えない（30〜60秒 無言）
- [#6](https://github.com/shoujiki-panman/aidoku/issues/6) 処方箋の（　）を埋める作業が重い
- [#7](https://github.com/shoujiki-panman/aidoku/issues/7) 履歴から「もう一度診断」ができない
- [#8](https://github.com/shoujiki-panman/aidoku/issues/8) 1回に1URLしか診断できない
- [#9](https://github.com/shoujiki-panman/aidoku/issues/9) 点数だけで「どこから直すか」が分からない
- [#10](https://github.com/shoujiki-panman/aidoku/issues/10) 判定基準が画面から見えない
- [#11](https://github.com/shoujiki-panman/aidoku/issues/11) 転入届しか対応していない

### Phase C — 広げる（提出後）
- [#12](https://github.com/shoujiki-panman/aidoku/issues/12) 多摩地域へ拡大
- [#13](https://github.com/shoujiki-panman/aidoku/issues/13) 自治体との接点をつくる
- [#14](https://github.com/shoujiki-panman/aidoku/issues/14) 判定のぶれを提出前に測り直す

## ⚠️ 触るときの注意

- **`pkill -f vite` を使わない**。mulmoclaude（5173）を巻き添えにする。パスで絞る
- 源内の起動は `web:dev`。**`web:devw` はAWSを要求する**（末尾のwに注意）
- `server.py` のポートは環境変数 `AIDOKU_PORT`。`--port` 引数は**無い**（黙って無視される）
- 源内のフロントは `createdDate` を**エポックミリ秒**で扱う。ISO文字列だと `Invalid time value`
- 源内のチャット画面は動かない（Lambda直叩き構造）。**AIアプリ画面だけ見せる**
- 認証は5行バイパスしている（本家に無い改変）。説明できる範囲に留めてある
- 採点はLLM判定なのでぶれる。±2点は測定誤差として明記して出す

## 📌 この1週間で学んだこと（同じ失敗を繰り返さないため）

1. **「〜のはず」で乗らない。確かめてから乗る。** 6回、前提が崩れた
   （海外の穴6本／母子手帳の空き5件／アトム接点4本／源内の配布経路／処方箋の効き方）
2. **正確さと安定性は別物。** ゴールデンを正確にしたらぶれが増えたことがある
3. **本人が評価できない確認を渡さない。** 機械照合で裏を取って、数字だけ報告する
4. **失敗の記録が資産になる。** 崩れた前提は全部 reports/ に残してある

## 📦 リポジトリ

**https://github.com/shoujiki-panman/aidoku （プライベート）**

- 42コミット push 済み。ローカルだけの状態は解消
- クロールした生HTMLは `.gitignore` で除外（自治体サイトの著作物のため）
- **提出前に公開へ切り替える**かは要判断。公開すると、捨てた企画の検討過程
  （都営住宅・母子手帳・アトム等）と、源内の認証を5行バイパスした話も読める状態になる

```bash
git push          # 以降はこれだけ
```

## 👤 田沼さんタスク

- [ ] **Cloudflare特典＋OpenCode/Workers AI特典の申請**（マニュアルを読んでから。1人でも「1名のチーム」で可）
      Cloudflare: https://odh-tokyo2026.code4japan.org/2026-Cloudflare-Paid-39a3e9710744805a9da2c82af3ec7bd4
      OpenCode/Workers AI: https://odh-tokyo2026.code4japan.org/AI-2026-OpenCode-Cloudflare-Workers-AI-39a3e9710744804c82f0c30bc6f6db25
- [ ] キックオフウィークの申込（8/6〜8/9・8/19。申込フォームは後日公開）
- [ ] 提出ガイドの著作権条件の確認（自治体サイトのスクショを載せる前に）
- [ ] `crawler/polite_fetch.py` の `CONTACT` を自分の連絡先に差し替え（**公開前に必須**）
- [ ] リポジトリを公開に切り替えるか判断（提出でURLが要る場合）
