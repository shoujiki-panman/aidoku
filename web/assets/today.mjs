// 「今日直す1件」の中身（純粋ロジック）。画面の配線は today-ui.mjs。
//
// 見張りの変化（43件）を「43件の数字」として見せず、状態で分けて優先度順に並べ、
// 先頭の1件に変換する（2026-09-08 の設計決定）。状態は混ぜない:
//
//   確認案件   … 担当者が確認した値が、元ページの変化で門番から消えている（最優先）
//   要再確認   … 元ページが変わった／消えた。悪化したとは限らない、測り直しの対象
//   欠落候補   … 到達したページから特定の項目を読み取れなかった（影響の大きい順）
//   未確認     … 対象の手続きページに到達できたか確かめられていない。
//                「区が書いていない」とは言えないので、欠落候補と混ぜず最後に置く
import { FIELD_MAP } from './verify-form.mjs';

export const STATE = {
  needsReview: '確認案件',
  recheck: '要再確認',
  missing: '欠落候補',
  unconfirmed: '未確認',
};

const STATE_RANK = [STATE.needsReview, STATE.recheck, STATE.missing, STATE.unconfirmed];

// 記録・門番の項目名 → 画面の項目名（verify-form の逆引き）
const FIELD_JP = Object.fromEntries(Object.entries(FIELD_MAP).map(([jp, en]) => [en, jp]));

const cellKey = (muniId, procId) => `${muniId}/${procId}`;

// cells: fix.js が組んだ 区×手続き（muniId/procId/名前/breakdown/pageStatus/lgCode）
// statusItems: web/data/site-status.json の items
// verifiedRecords: web/data/verified-status.json の records
// 返り値: 優先度順の課題列。1セル1件（いちばん重い状態だけを出す）
export function buildQueue({ cells, statusItems = [], verifiedRecords = [] }) {
  const FIELDS = Object.keys(FIELD_MAP);
  const missingOf = (c) => FIELDS.filter((f) => ((c.breakdown || {})[f] ?? 0) < 20);
  const cellByKey = new Map(cells.map((c) => [cellKey(c.muniId, c.procId), c]));
  const byKey = new Map();

  // 欠落候補・未確認（実測から）
  for (const c of cells) {
    const missing = missingOf(c);
    if (c.pageStatus === 'target_unconfirmed') {
      byKey.set(cellKey(c.muniId, c.procId), {
        state: STATE.unconfirmed, cell: c, missing,
        reason: 'この手続きのページにたどり着けたか確かめられていません（「書いていない」とは言えません）',
      });
    } else if (missing.length) {
      byKey.set(cellKey(c.muniId, c.procId), {
        state: STATE.missing, cell: c, missing,
        reason: `読み取れなかった項目が ${missing.length} つ: ${missing.join('・')}`,
      });
    }
  }

  // 要再確認（見張りから）。欠落候補・未確認より重い。
  // 欠落の無いページでも、変わったなら測り直しの対象なので課題に出す
  for (const s of statusItems) {
    if (!s.changed && !s.gone) continue;
    const key = cellKey(s.municipality_id, s.procedure_id);
    const cell = cellByKey.get(key);
    if (!cell) continue; // 採点していないページは、この画面の課題にしない
    const when = (s.checked_at || '').slice(0, 10);
    byKey.set(key, {
      state: STATE.recheck, cell, missing: byKey.get(key)?.missing ?? missingOf(cell),
      reason: s.gone
        ? `元ページが消えています（${when} の見張りで検出）`
        : `元ページが変わっています（${when} の見張りで検出）。悪化したとは限りません`,
    });
  }

  // 確認案件（確認済み情報の状態から）。最優先
  for (const r of verifiedRecords) {
    const back = Object.entries(r.fields ?? {}).filter(([, e]) => e?.status === 'needs_review');
    if (!back.length) continue;
    const key = cellKey(r.municipality_id, r.procedure_id);
    const cell = cellByKey.get(key);
    if (!cell) continue;
    const names = back.map(([en]) => FIELD_JP[en] ?? en).join('・');
    const why = back[0][1]?.review_reason;
    byKey.set(key, {
      state: STATE.needsReview, cell, missing: byKey.get(key)?.missing ?? missingOf(cell),
      reason: `担当者確認済みの「${names}」が確認案件に戻り、AIへの配信が止まっています${why ? `（${why}）` : ''}`,
    });
  }

  return [...byKey.values()].sort((a, b) => {
    const rank = STATE_RANK.indexOf(a.state) - STATE_RANK.indexOf(b.state);
    if (rank) return rank;
    // 同じ状態の中は影響の大きい順（読み取れていない項目が多い順）→ 団体コード順
    if (b.missing.length !== a.missing.length) return b.missing.length - a.missing.length;
    return String(a.cell.lgCode ?? '').localeCompare(String(b.cell.lgCode ?? ''));
  });
}

export function countByState(queue) {
  const counts = Object.fromEntries(STATE_RANK.map((s) => [s, 0]));
  for (const q of queue) counts[q.state] += 1;
  return counts;
}
