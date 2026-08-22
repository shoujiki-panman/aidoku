// 前回からの差。DOMに触らない Pure Function だけを置く。
//
// ★一番大事なこと: 差を出すことと、差の原因を言うことを分ける。
//   点数が動いても、それが「サイトが直った」のか「こちらの測り方が変わった」のかは、
//   測定条件（measurement_signature）が一致していなければ区別できない。
//   history.py の attribution と同じ判断を、画面側でも守る。
//
//   既存の履歴は全部 recording_status: "legacy_unknown"（METHOD.md §4-8）なので、
//   **いまの実データでは必ず「原因は言えない」になる。それが正しい。**
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.AidokuTrend = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // JSON Lines を読む。壊れた行は飛ばす（履歴は読めるところまで読む）
  function parseJsonl(text) {
    if (typeof text !== 'string') return [];
    const out = [];
    for (const line of text.split('\n')) {
      const t = line.trim();
      if (!t) continue;
      try {
        const o = JSON.parse(t);
        if (o && typeof o === 'object' && !Array.isArray(o)) out.push(o);
      } catch { /* 飛ばす */ }
    }
    return out;
  }

  // 差の原因を言ってよいか。history.py の attribution と同じ規則。
  function attribution(a, b) {
    if (!a || !b) return { how: 'unknown', why: '比べる相手がない' };
    if (a.measurement_signature !== b.measurement_signature) {
      return { how: 'unknown', why: '測定条件が違う（モデル・プロンプト・探索幅のいずれかが変わっている）' };
    }
    if (a.recording_status !== 'recorded' || b.recording_status !== 'recorded') {
      return { how: 'unknown', why: '測定条件が記録されていない期間を含む' };
    }
    return { how: 'site', why: '測定条件が同じなので、差はサイト側の変化と見てよい' };
  }

  const gotOf = (m, fields) =>
    fields.filter((f) => ((m && m.breakdown) || {})[f] >= 20).length;

  // 1区ぶんの推移。手続きをまたいで合算する（12項目のメーターと同じ数え方）
  function wardSeries(snapshots, muniId, fields) {
    const byTime = new Map();
    for (const s of snapshots) {
      const m = (s.municipalities || []).find((x) => x.id === muniId);
      if (!m) continue;
      const key = s.generated_at || '';
      const cur = byTime.get(key) || {
        at: key, got: 0, total: 0,
        signature: s.measurement_signature, recording: s.recording_status,
      };
      cur.got += gotOf(m, fields);
      cur.total += fields.length;
      byTime.set(key, cur);
    }
    return [...byTime.values()].sort((a, b) => String(a.at).localeCompare(String(b.at)));
  }

  // 直近2点の差。動いていなければ delta 0 で返す（「変化なし」も情報）
  function lastChange(series) {
    if (!Array.isArray(series) || series.length < 2) return null;
    const prev = series[series.length - 2];
    const now = series[series.length - 1];
    return {
      prev, now,
      delta: now.got - prev.got,
      ...attribution(
        { measurement_signature: prev.signature, recording_status: prev.recording },
        { measurement_signature: now.signature, recording_status: now.recording }),
    };
  }

  // 見張りの推移。ここは測定条件の問題が無い（本文を読まず、変わったかだけ見るため）
  function watchSeries(snapshots) {
    return snapshots
      .filter((s) => s && s.checked_at)
      .map((s) => ({
        at: s.checked_at,
        changed: Array.isArray(s.changed) ? s.changed.length : 0,
        gone: Array.isArray(s.changed) ? s.changed.filter((c) => c && c.gone).length : 0,
        total: (s.summary && s.summary.total) || 0,
      }))
      .sort((a, b) => String(a.at).localeCompare(String(b.at)));
  }

  return { parseJsonl, attribution, wardSeries, lastChange, watchSeries };
});
