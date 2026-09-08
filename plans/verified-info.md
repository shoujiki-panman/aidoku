# 確認済み情報 — 担当者が確認すると、AIの案内が変わる

Status: 実装中（第1段: 保存と門番への接続）
Issue: [#192](https://github.com/shoujiki-panman/aidoku/issues/192)
決定: 2026-09-08 の設計会話（ChatGPT「AI読UIUX設計」）で、MVPの最初の実装対象を
**確認済み情報の保存と門番への接続**にすると本人が決定。申込自動化は将来機能のまま。
関連: [`spec-fix-app.md`](https://github.com/shoujiki-panman/aidoku/pull/187)（担当者アプリの要件・PR #187） /
[`gatekeeper-direction.md`](gatekeeper-direction.md)（門番の方向） /
[`decisions/api-layer-from-michiyomi.md`](decisions/api-layer-from-michiyomi.md)（公開判定APIは作らない）

---

## Why — なぜ要るか

いまの門番が返せるのは実測値だけで、実測は7〜8割が「読み取れなかった（null）」。
担当者が正しい値を確認しても、それを**保存する場所も、AIへ届ける経路も無い**。
「担当者が情報を確認・修正すると、利用者のAIの案内が変わる」という中核体験が、
データの層で成立していない。ここを先に通す（画面はその後）。

## 通す一周

```
担当者が確認 → verified/ に保存（出典・条件・確認者・版）
  → verified_sync.mjs → answers/*.json の verified_fields → put_answers.sh → KV
  → 門番が実測と確認済みを別の束で返す（AIがどちらの値か言える）

元情報が変わった（見張りが検出）
  → verified_sync.mjs が確認案件（needs_review）に戻す → 門番から消える
  → 担当者が見直して再公開（version +1）→ また届く
```

## 完了条件（第1段）

1. 確認済みの値を、出典・条件・確認者・版つきで保存できる（`gatekeeper/verified/*.json`）
2. 公開（published）した値だけが門番の答えに載り、実測（fields）とは別の束で返る
3. 実測が全null のページでも、確認済みがあれば failure ではなく answer が返る
4. 見張りが「公開後に元ページが変わった／消えた」と言ったら、確認案件に戻り、門番から消える
5. 再公開（version +1）で再び門番から出る
6. この間、実測 `fields` は1文字も変わらない
7. 以上が `gatekeeper/test_verified.mjs` で機械的に確かめられる

## 制約 — 既存の決定と衝突させない

- **公開の書き込みAPIは作らない**（`decisions/api-layer-from-michiyomi.md` と同じ理由）。
  記録の入り口はリポジトリ（PR）。ログインつき管理画面は方針7（8/18）の将来分
- **AI読は値を書かない**。`fix.html`「値はこちらでは埋めません」は変えない。値の主語は担当者
- **verified/ に見本・仮の値を置かない**。置くと門番が本物のAIに返す。試すのはテストの中だけ

## 次の段（この計画の残り）

- 第2段: 管理画面と接続。`fix.html` に「内容確認 → 公開 → AIが取得した結果」の一周を出す
  （静的のまま。公開＝記録ファイルの生成まで。PR #187 の入力チェックと合流）
- 第3段: 更新対応の運用。見張り → 確認案件の一覧を担当者画面の入口に出す（「今日直す1件」）

## Progress

<!-- 追記のみ。1ステップ1行。失敗も書く。書き直さない -->

- 2026-09-09 第1段を実装。verified/ の形・verified_sync.mjs・門番の返し方・test_verified.mjs（19件）
- 2026-09-09 PR前の多角レビュー（31エージェント・反証つき）で確定9件。うち4件は実装の穴:
  ①見張りの changed はラッチ式で、再公開が翌朝必ず差し戻される ②照合の形が公開側と差し戻し側で
  違い、URLの書きぶれで「公開されるのに監視されない」記録ができる ③紐の切れた verified_fields が
  answers に残り配信され続ける ④見張りが読めなくても公開を続行する。全て修正、テスト29件に増補
