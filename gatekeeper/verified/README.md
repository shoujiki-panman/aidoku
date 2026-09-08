# verified/ — 自治体担当者が確認した情報の置き場

門番が返す答えには2種類ある。**実測**（AI読が区のページを読んで取れた値。`answers/*.json` の
`fields`）と、**確認済み**（自治体の担当者が「これが正しい」と確認した値。ここに置く）。

この2つは最後まで混ぜない。門番は両方を別の束のまま返し、どちらの値かをAI側が言えるようにする。
AI読自身は値を作らない方針（`web/fix.html`「値はこちらでは埋めません」）のままで、
**値を書けるのは担当者だけ**。その受け皿がこのディレクトリ。

## ファイルの形

1ファイル = 1ページ（区 × 手続き）。ファイル名は `<municipality_id>-<procedure_id>.json`。

```json
{
  "municipality": "世田谷区",
  "municipality_id": "setagaya",
  "procedure": "転入届",
  "procedure_id": "tennyu",
  "source": "https://www.city.setagaya.lg.jp/kurashi/kosekijuumin/11531.html",
  "fields": {
    "fee": {
      "value": "無料",
      "conditions": "窓口で届け出る場合",
      "verified_by": "世田谷区 戸籍住民課",
      "verified_at": "2026-09-09",
      "published_at": "2026-09-09T12:00:00+09:00",
      "version": 1,
      "status": "published"
    }
  }
}
```

| 鍵 | 意味 |
|---|---|
| `source` | 出典。確認した元ページのURL。answers側の相手も見張りとの照合も **host+path に畳んだ形**で行う（スキームやクエリの書きぶれは無視される） |
| `value` | 確認した値。担当者が書く。AI読は書かない |
| `conditions` | その値が成り立つ条件（「窓口の場合」など）。無条件なら null |
| `verified_by` | 確認者（部署名まででよい） |
| `verified_at` | 確認した日 |
| `published_at` | 公開した時刻。見張りの変化とどちらが後かの比較に使うので**時刻まで**書く |
| `version` | 版。再公開のたびに +1 |
| `status` | `published`（公開中）か `needs_review`（確認案件。門番からは出ない） |

項目名（`fields` の鍵）に使えるのは実測と同じ4つだけ:
`required_documents` / `fee` / `deadline` / `how_to_apply`。
それ以外の名前（タイポ含む）は公開されず、`verified_sync.mjs` が報告して落ちる。

## 流れ

```
担当者が確認 → このファイルに記録（status: published）
  → node gatekeeper/verified_sync.mjs   … answers/*.json の verified_fields に反映
  → gatekeeper/put_answers.sh           … KVへ。ここで初めてAIの案内が変わる

元ページが変わった（見張り web/data/site-status.json が検出）
  → verified_sync.mjs が status を needs_review に戻す＝確認案件に戻る
  → 門番はその項目の確認済みを返さなくなる（実測 fields は影響なし）

担当者が見直して再公開
  → status を published に戻し、version +1、verified_at / published_at を更新
  → verified_sync.mjs → put_answers.sh で再びAIへ届く
```

**再公開が翌朝取り消されない理由**: 見張りの `changed` はラッチ式で、測り直しまで
毎朝出続ける。そのため sync は「検出済みの変化（`review_detected_at`）より後に
再公開された項目」は戻さない。`review_*` の印は消さずに残しておくこと（これが
「その変化は確認済み」の証拠になる）。測り直しで見張りが `changed: false` に戻ると
sync が印を消し、その後の変化はまた新しい確認案件になる。
本筋としては、再公開したページは早めに測り直して見張りの基準も更新する。

いまは記録の入り口が「このファイルを直接書く（PRで置く）」しかない。
`fix.html` の確認フォームから記録を作る導線は次の段（`plans/verified-info.md`）。

⚠️ ここに**見本・仮の値を置かない**。置いた瞬間、門番が「担当者確認済み」として
本物のAIに返してしまう。試すときはテスト（`test_verified.mjs`）の中だけで完結させる。
