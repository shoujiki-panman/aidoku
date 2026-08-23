# 提出用の画面キャプチャ（1600×900）

都知事杯の提出フォーム 5-2 の必須添付（JPEG/PNG・最大3枚・推奨1600×900）。
**すべて実際に動いている画面**から撮っている（合成・モックは無し）。

| ファイル | 何の画面か | 何が伝わるか |
|---|---|---|
| `01_gennai_answer.png` | デジタル庁OSS「源内」のAIアプリ画面でAI読を実行した結果（世田谷区） | 住民のAIが4項目すべて「このページからは分かりません」と答えること、**その理由**（入口が目次ページで詳細に到達できない）。右は23区の実行履歴 |
| `02_gennai_fix.png` | 同じ画面の続き。「直すと、住民のAIはこう答えられるようになります」 | 直す文面が型として出ること。（　）は職員が埋める＝AIは役所の情報を作らない |
| `03_dashboard_compare.png` | 公開ダッシュボードの冒頭 | **同じ質問への答えが、区のページの書き方だけでここまで変わる**（世田谷区 ✕4 / 港区 ✓4）。文はすべて実測値 |

## デモ操作動画（提出フォーム 3-8）

`demo.mp4` — **45.8秒・1600×900・無音**（提出条件は60秒以内・音声を使う作品以外は無音）。

流れ: 源内のAIアプリ一覧にAI読が並ぶ → 世田谷区のURLを入れて実行 → 住民のAIの答えが
4項目とも「分かりません」→ なぜ答えられないのか → 直すとどう答えられるようになるか →
港区で同じことをすると4項目とも答えられる。**すべて実操作の録画**（早送り・編集なし）。

```bash
node record.mjs <出力先>          # webm が出る
ffmpeg -i <出力先>/*.webm -an -c:v libx264 -pix_fmt yuv420p \
       -preset slow -crf 22 -movflags +faststart -y demo.mp4
```

`-an` で音声トラックを付けない（提出条件の「無音」）。

## 撮り直し方

`shoot.mjs` が撮影スクリプト（Playwright）。実画面を開き、実際にフォームへURLを入れて
「実行」を押し、結果が出てから撮る。

```bash
# 1) AI読API・源内バックエンドの代わり・源内Webフロント・公開ダッシュボード を起動
#    （手順は ../../START-HERE.md と reports/gennai_local_run_2026-07-26.md）
# 2) 撮影
node shoot.mjs <出力先ディレクトリ>
```

前提のポート: 源内Webフロント `5174` / 源内バックエンド代替 `8787` / AI読API `8791` /
公開ダッシュボード `4191`。Playwright は mulmoclaude の node_modules を借りている
（このリポジトリに依存を足さないため）。

**注意**: `pkill -f vite` は使わない。同じマシンの別のViteアプリを巻き添えにする。
必ず `lsof -ti tcp:<port>` でPIDを特定して止める。

## 公開画面（web/）のキャプチャ — 2026-08-23 撮り直し

`shoot_web.mjs` / `record_web.mjs` が撮影スクリプト。どちらもローカルの静的サーバを見る。

```bash
cd web && python3 -m http.server 4199 &     # 止めるときは lsof -ti tcp:4199 で PID を特定
node deck/captures/shoot_web.mjs  deck/captures      # cap_map / poster / cap_journey
node deck/captures/record_web.mjs /tmp/aidoku_vid    # webm が出る
ffmpeg -i /tmp/aidoku_vid/*.webm -an -c:v libx264 -pix_fmt yuv420p \
       -preset slow -crf 22 -movflags +faststart -y deck/captures/demo.mp4
```

| ファイル | 何の画面か |
|---|---|
| `cap_map.png` | トップ画面。ヘッダー＋23区の地図（**青の濃淡1色**。以前の緑/薄緑/黄/赤の4色ではない） |
| `poster.png` | 世田谷区を押し、転入届を開いた状態。「読めない 4項目」の札と「あなたが次にやること」 |
| `cap_journey.png` | `journey.html`「AIが歩いた道のり」。判断（点の付け方と候補の並び）を開いた状態 |
| `demo.mp4` | **52.6秒・1600×900・無音**。地図 → 世田谷区 → 転入届 → AIの道のり → 調査データ一覧 → 自分のAIに持たせる |

**注意**: `scrollIntoView` は使わない。headless で真っ白なフレームになったことがある。
位置は `getBoundingClientRect` で測って `window.scrollTo` で送る（両スクリプトの `glideTo` / `topOf`）。
