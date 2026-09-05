// 「自分の区を調べる」の照合。DOMに触らない Pure Function だけを置く。
// ブラウザ（app.js）と node のテスト（web/test_lookup.mjs）の両方から読む。
//
// ★ここでは、その場でAIに読ませない。
//   判定は claude -p をローカルで呼ぶ設計で、静的ホスティングからは動かせない（#59）。
//   できるのは「すでに測ってある69マスから引く」ことだけ。
//   当たらなかったら、当てずっぽうを返さずに「まだ測っていない」と言う。
//   盤面のグレーと同じ約束 — 憶測では塗らない。
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.AidokuLookup = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // URLを比べられる形にそろえる。プロトコル・www・末尾スラッシュ・クエリ・
  // フラグメントは、同じページを指していても表記が割れるので落とす。
  // 一方 index.html は落とさない（/a/ と /a/index.html が別ページのことがある）。
  function normalizeUrl(raw) {
    if (typeof raw !== 'string') return null;
    let s = raw.trim();
    if (!s) return null;
    s = s.replace(/^https?:\/\//i, '').split('#')[0].split('?')[0].replace(/\/+$/, '');
    const slash = s.indexOf('/');
    const host = (slash === -1 ? s : s.slice(0, slash)).toLowerCase().replace(/^www\./, '');
    if (!host.includes('.') || host.endsWith('.')) return null;
    return { host, path: slash === -1 ? '' : s.slice(slash), key: host + (slash === -1 ? '' : s.slice(slash)) };
  }

  // 「区」の有無だけ吸収する。読みは持っていないので、かなでは引けない。
  const normalizeName = (s) => String(s === null || s === undefined ? '' : s)
    .trim().replace(/\s+/g, '').replace(/区$/, '');

  // cells の1件が使える形か。壊れた行は黙って落とす（例外にしない）。
  const isCell = (c) =>
    c !== null && typeof c === 'object' && !Array.isArray(c) &&
    typeof c.muniName === 'string' && c.muniName !== '' && typeof c.procId === 'string';

  // 同じ区のマスを、procOrder（data/procedures.json の並び）どおりに返す
  function wardCells(muniName, cells, procOrder) {
    const mine = cells.filter((c) => c.muniName === muniName);
    const rank = (id) => {
      const i = Array.isArray(procOrder) ? procOrder.indexOf(id) : -1;
      return i === -1 ? Number.MAX_SAFE_INTEGER : i;
    };
    return mine.sort((a, b) => rank(a.procId) - rank(b.procId) || a.procId.localeCompare(b.procId));
  }

  // 返す形:
  //   { kind: 'page',  cell }                        貼られたページそのものを測ってある
  //   { kind: 'ward',  muniName, cells, matchedBy }  区は測ってあるが、そのページは測っていない
  //   { kind: 'none',  reason }                      'empty' | 'unmeasured'
  function lookup(query, cells, procOrder) {
    const list = Array.isArray(cells) ? cells.filter(isCell) : [];
    const q = String(query === null || query === undefined ? '' : query).trim();
    if (!q) return { kind: 'none', reason: 'empty' };

    const u = normalizeUrl(q);
    if (u && u.path) {
      const hit = list.find((c) => {
        const n = normalizeUrl(c.url);
        return n && n.key === u.key;
      });
      if (hit) return { kind: 'page', cell: hit };
    }
    if (u) {
      const sameHost = list.find((c) => {
        const n = normalizeUrl(c.url);
        return n && n.host === u.host;
      });
      if (sameHost) {
        return { kind: 'ward', muniName: sameHost.muniName,
                 cells: wardCells(sameHost.muniName, list, procOrder), matchedBy: 'url-host' };
      }
      return { kind: 'none', reason: 'unmeasured' };
    }

    const nq = normalizeName(q);
    if (nq) {
      const byName = list.find((c) => normalizeName(c.muniName) === nq)
        || list.find((c) => normalizeName(c.muniName).includes(nq));
      if (byName) {
        return { kind: 'ward', muniName: byName.muniName,
                 cells: wardCells(byName.muniName, list, procOrder), matchedBy: 'name' };
      }
    }
    return { kind: 'none', reason: 'unmeasured' };
  }

  // 住民に見せる言い方。点数（7/12）と棒グラフはここには出さない。
  // ★本人の指摘:「住民側にこれいらないでしょ。一切説明もない」。
  //   住民が知りたいのは「自分のAIが何を知れないか」であって、区の成績ではない。
  //   点数と推移は reference/archive.html（調査データ一覧）に置く。
  function missingSummary(missing, procedures, fieldsPerProc) {
    const m = Number(missing);
    const p = Number(procedures);
    if (!Number.isFinite(m) || !Number.isFinite(p) || p <= 0) return '';
    const all = p * Number(fieldsPerProc);
    if (m === 0) return `測った${p}つの手続きは、どれも${fieldsPerProc}項目すべてを読み取れました。`;
    if (m === all) return `測った${p}つの手続きは、どれも1項目も読み取れませんでした。`;
    return `測った${p}つの手続きのうち、AIが区のページから読み取れなかった項目が${m}つあります。`;
  }

  // 手続き1行の見出しに出す短い札。0/4 のような点数はやめる
  function cellChip(missing, fields) {
    const m = Number(missing);
    if (!Number.isFinite(m)) return '';
    return m === 0 ? `${fields}項目とも読めた` : `読めない ${m}項目`;
  }

  return { normalizeUrl, normalizeName, lookup, wardCells, missingSummary, cellChip };
});
