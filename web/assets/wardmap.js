// 23区の地図。DOMに触らない Pure Function だけを置く。
//
// ★URLや区名を打たせない。地図を押すのが一番速い（本人の指摘）。
// ★地図ライブラリは足さない。境界は analysis/export_map.py が SVG パスに
//   変換済みで、ここは <path d="..."> を組み立てるだけ。
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.AidokuWardMap = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // 12項目のうち何項目届いているかで塗り分ける。
  // ★色だけに頼らない。押すと区名と数字が出るし、下に一覧も置く。
  function tone(got, total) {
    if (!total) return 'unknown';
    const r = got / total;
    if (r >= 0.75) return 'high';
    if (r >= 0.5) return 'mid';
    if (r > 0) return 'low';
    return 'zero';
  }

  // 区ごとの到達度をまとめる。cells は lookup と同じ形
  function wardProgress(cells, fields) {
    const by = new Map();
    for (const c of cells || []) {
      if (!c || !c.muniName) continue;
      const cur = by.get(c.muniName) || { name: c.muniName, id: c.muniId, got: 0, total: 0 };
      cur.got += (fields || []).filter((f) => ((c.breakdown || {})[f] ?? 0) >= 20).length;
      cur.total += (fields || []).length;
      by.set(c.muniName, cur);
    }
    for (const v of by.values()) v.tone = tone(v.got, v.total);
    return by;
  }

  // 地図に載せる1区ぶん
  function decorate(wards, progress) {
    return (wards || []).map((w) => {
      const p = progress.get(w.name);
      return {
        code: w.code,
        name: w.name,
        // 地図に書くのは「区」を落とした短い名前。狭いマスでも読めるようにする
        short: String(w.name || '').replace(/区$/, ''),
        d: w.d,
        lx: w.lx,
        ly: w.ly,
        got: p ? p.got : null,
        total: p ? p.total : null,
        tone: p ? p.tone : 'unknown',
        label: p ? `${w.name} ${p.got}/${p.total}項目` : `${w.name}（測っていません）`,
      };
    });
  }

  return { tone, wardProgress, decorate };
});
