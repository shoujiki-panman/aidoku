// 確認済み情報の判定ロジック（純粋関数だけ。Node固有のAPIを使わない）。
//
// verified_sync.mjs（Nodeで動かす同期スクリプト）と、担当者画面（web/fix.html の
// 「AIが取得した結果」プレビュー）の両方がここを使う。画面用に別実装を作ると
// 実物とずれるので、判定はこの1か所に置く。
import { KNOWN_FIELDS } from './demand.mjs';

// 見張りの checked_at は "+0000" 形式のことがある。Date.parse が拾えない環境でも
// 落ちないように、コロン入りに直してから読む。読めない時刻は NaN のまま返す
// （NaN は比較で必ず false になる＝「変わった証拠にならない」側に倒れる）。
export function parseTime(ts) {
  if (!ts) return NaN;
  const t = Date.parse(ts);
  if (Number.isFinite(t)) return t;
  return Date.parse(String(ts).replace(/([+-]\d{2})(\d{2})$/, '$1:$2'));
}

// URLを「host+path」に畳む（KVのキーと同じ形）。スキームやクエリの書きぶれで
// 「answers には載るのに見張りとは照合できない」記録ができないよう、
// 差し戻しの照合も反映の照合も必ずこの1つの形でやる。読めなければ null。
export function urlKey(u) {
  try {
    const x = new URL(u);
    return `${x.host}${x.pathname}`;
  } catch {
    return null;
  }
}

// 4項目の語彙に無い項目名を返す（タイポや独自項目は公開せず、報告して直させる）。
export function unknownFields(record) {
  return Object.keys(record?.fields ?? {}).filter((name) => !KNOWN_FIELDS.includes(name));
}

// 差し戻し。record（verified/*.json の中身）を見張りの結果と突き合わせる。
// 返り値: { watched: 見張りに相手がいたか, demoted: 戻した項目名, cleared: 印を消した項目名 }
export function reviewAgainstWatch(record, statusItems) {
  const key = urlKey(record.source);
  const item = key ? (statusItems ?? []).find((s) => urlKey(s.url) === key) : null;
  if (!item) return { watched: false, demoted: [], cleared: [] };

  const demoted = [];
  const cleared = [];
  for (const [name, entry] of Object.entries(record.fields ?? {})) {
    if (!entry) continue;

    // 測り直しで基準が更新され「変わっていない」に戻った → ラッチが解けた。
    // 公開中の項目に残っている検出の印を消す（次の changed は新しい変化）。
    if (!item.changed && !item.gone) {
      if (entry.status === 'published' && (entry.review_detected_at || entry.review_reason)) {
        delete entry.review_detected_at;
        delete entry.review_reason;
        cleared.push(name);
      }
      continue;
    }

    if (entry.status !== 'published') continue;

    // 検出済みの変化より後に再公開されている＝担当者はその変化を見た上で確認している。
    // 見張りは測り直しまで同じラッチを出し続けるので、その間は戻さない。
    const detectedAt = parseTime(entry.review_detected_at);
    const publishedAt = parseTime(entry.published_at);
    if (Number.isFinite(detectedAt) && Number.isFinite(publishedAt) && publishedAt > detectedAt) {
      continue;
    }

    let reason = null;
    if (item.gone) {
      reason = '元ページが消えた';
    } else {
      const changedAt = parseTime(item.checked_at);
      // published_at が書かれていない記録は「いつ確認したか」を主張できないので、
      // 変化があれば戻す（確認済みを名乗るなら時刻を持て、という向きに倒す）
      if (!Number.isFinite(publishedAt) || changedAt > publishedAt) {
        reason = '元ページが変わった';
      }
    }
    if (!reason) continue;

    entry.status = 'needs_review';
    entry.review_reason = reason;
    entry.review_detected_at = item.checked_at ?? null;
    demoted.push(name);
  }
  return { watched: true, demoted, cleared };
}

// 反映。answers 1件に、published かつ語彙内の項目だけを verified_fields として載せる。
// 内部管理の鍵（status / published_at / review_*）は外に出さない。
// published が1つも無ければ verified_fields ごと消す（needs_review の値を出し続けない）。
export function publishInto(answer, record) {
  const published = {};
  for (const [name, entry] of Object.entries(record?.fields ?? {})) {
    if (!KNOWN_FIELDS.includes(name)) continue;
    if (!entry || entry.status !== 'published' || entry.value == null) continue;
    published[name] = {
      value: entry.value,
      conditions: entry.conditions ?? null,
      verified_by: entry.verified_by ?? null,
      verified_at: entry.verified_at ?? null,
      version: entry.version ?? 1,
      source: record.source ?? null,
    };
  }
  if (Object.keys(published).length) answer.verified_fields = published;
  else delete answer.verified_fields;
  return answer;
}

export const hasPublished = (record) =>
  Object.values(record?.fields ?? {}).some((e) => e?.status === 'published');
