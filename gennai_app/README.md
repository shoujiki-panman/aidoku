# AI読 — 源内AIアプリ（源内API仕様に準拠した独立エンドポイント）

デジタル庁OSS「源内」のAIアプリAPI仕様（2026年3月版）に準拠したHTTPエンドポイント。
自治体が自前で運用する源内に、GUI操作で追加登録できる形。

## 中身

| ファイル | 役割 |
|---|---|
| `aidoku_engine.py` | 判定エンジン。23区は実測値を即返し、未知URLはその場で取得→claude -pで判定 |
| `server.py` | 源内仕様のHTTPエンドポイント（同期 /invoke・非同期 /requests・/status/<id>） |
| `request_format.json` | 源内が入力フォームを自動生成するための定義 |

## 起動

```bash
AIDOKU_PORT=8791 python3 server.py
```

- ポート指定は環境変数 `AIDOKU_PORT`（`--port` 引数は無い）
- `AIDOKU_ALLOW_LIVE=0` にすると、実測データにあるURLだけを受け付ける（デモ時の保険）

## 動作確認

```bash
curl -X POST http://127.0.0.1:8791/invoke \
  -H "x-api-key: dev-local-key" \
  -d '{"inputs":{"url":"https://www.city.minato.tokyo.jp/shibamadosa/kurashi/todokede/hikkoshi/tennyu.html"}}'
```

## 判定の出どころ（正直に）

- **measured**: 23区は2026-07-22の実測値（クロール→claude -pで判定済み）。即座に返る
- **live**: 未知のURLはその場で取得して判定。**1回30〜60秒かかる**ため非同期エンドポイント推奨

## 処方箋についての実測

生成した文面を**そのまま貼っても点は上がらない**（3区で検証・全て0点上昇）。
**（　）を実際の値で埋めてから貼ると上がる**（世田谷 0→100 / 新宿 0→80 / 港ablated 60→100）。
これはバグではなく「AIが役所の情報を捏造しない」ための設計。
だから処方箋は「穴の場所と書き方の型」として出し、埋めるのは職員、と画面に明記している。

## 言い方の線

- ✅ 「源内のAIアプリAPI仕様（2026年3月版）に準拠」
- ❌ 「源内に採用された」「源内互換」（本物の源内には未登録）
