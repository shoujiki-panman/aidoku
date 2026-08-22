// 見張りと推移の描画。数字は trend.js（Pure）が作る。ここは置くだけ。
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  async function loadJsonl(path) {
    try {
      const r = await fetch(path);
      return r.ok ? AidokuTrend.parseJsonl(await r.text()) : [];
    } catch { return []; }
  }
  async function loadJson(path) {
    try {
      const r = await fetch(path);
      return r.ok ? await r.json() : null;
    } catch { return null; }
  }

  const d10 = (s) => String(s || '').slice(0, 10);
  const ymd = (ts) => (typeof ts === 'string' && ts.length >= 8
    ? `${ts.slice(0, 4)}-${ts.slice(4, 6)}-${ts.slice(6, 8)}` : '');

  // 見張り: 変わったページ数の棒。ここは測定条件の問題が無い（本文を読んでいないため）
  function renderWatch(rows) {
    if (!rows.length) { $('watch').innerHTML = '<p class="section-note">記録がまだありません。</p>'; return; }
    const max = Math.max(...rows.map((r) => r.changed), 1);
    const bars = rows.map((r) => `
      <li class="bar">
        <span class="bar__fill" style="height:${Math.max(Math.round((r.changed / max) * 100), 3)}%"
              title="${esc(d10(r.at))} 変化 ${r.changed}件 / 確認 ${r.total}ページ"></span>
        <b class="bar__n">${r.changed}</b>
        <i class="bar__d">${esc(d10(r.at)).slice(5)}</i>
      </li>`).join('');
    const last = rows[rows.length - 1];
    const gone = rows.reduce((a, r) => a + r.gone, 0);
    $('watch').innerHTML = `
      <div class="panel">
        <p class="panel__head">
          <b class="panel__num">${last.changed}</b>
          <span>最新（${esc(d10(last.at))}）に変わっていたページ
            <span class="panel__sub">／ ${last.total}ページを確認</span></span>
        </p>
        <ul class="bars">${bars}</ul>
        <p class="panel__note">記録 ${rows.length}回分。消えたページ（404・410）の累計は <b>${gone}</b> 件。</p>
      </div>`;
  }

  // 点数: 手続きごとの平均点。★原因の断定は attribution に従う
  function renderScores(snaps) {
    if (!snaps.length) { $('scores').innerHTML = '<p class="section-note">記録がまだありません。</p>'; return; }
    const byProc = new Map();
    for (const s of snaps) {
      const k = s.procedure_id || '(不明)';
      if (!byProc.has(k)) byProc.set(k, { name: s.procedure || k, rows: [] });
      byProc.get(k).rows.push(s);
    }
    const blocks = [...byProc.values()].map((p) => {
      const rows = p.rows.sort((a, b) => String(a.generated_at).localeCompare(String(b.generated_at)));
      const pts = rows.map((r) => `
        <li class="pt">
          <b>${esc(String((r.summary && r.summary.average) ?? '-'))}</b>
          <i>${esc(d10(r.generated_at))}</i>
        </li>`).join('');
      const a = rows[rows.length - 2];
      const b = rows[rows.length - 1];
      const at = a && b ? AidokuTrend.attribution(a, b) : null;
      const da = a && b
        ? Math.round(((b.summary?.average ?? 0) - (a.summary?.average ?? 0)) * 10) / 10 : null;
      return `<div class="panel">
        <p class="panel__head"><b>${esc(p.name)}</b>
          ${da !== null ? `<span class="panel__delta" data-tone="${da > 0 ? 'up' : da < 0 ? 'down' : 'flat'}">
            ${da > 0 ? '+' : ''}${da}</span>` : ''}
        </p>
        <ol class="pts">${pts}</ol>
        ${at ? `<p class="panel__why" data-how="${esc(at.how)}">
          ${at.how === 'site'
            ? 'この差はサイト側の変化と見てよい（測定条件が同じ）'
            : `<b>この差の原因は言えない</b> — ${esc(at.why)}`}</p>` : ''}
      </div>`;
    }).join('');
    $('scores').innerHTML = blocks;
  }

  function renderArchive(doc) {
    if (!doc || !doc.pages) { $('archive').innerHTML = '<p class="section-note">記録がまだありません。</p>'; return; }
    const withSnap = doc.pages.filter((p) => p.snapshots);
    const total = doc.pages.reduce((a, p) => a + (p.snapshots || 0), 0);
    const oldest = withSnap.map((p) => p.first).sort()[0];
    const top = [...withSnap].sort((a, b) => b.snapshots - a.snapshots).slice(0, 5);
    $('archive').innerHTML = `
      <div class="panel">
        <p class="panel__head"><b class="panel__num">${total}</b>
          <span>版が残っている（${withSnap.length} / ${doc.pages.length} ページ）
            <span class="panel__sub">／ 一番古い版 ${esc(ymd(oldest))}</span></span></p>
        <ul class="arch">${top.map((p) => `
          <li><b>${esc(p.municipality)}</b>・${esc(p.procedure)}
            <span class="arch__n">${p.snapshots}版</span>
            <span class="arch__d">${esc(ymd(p.first))} 〜 ${esc(ymd(p.last))}</span>
            <a class="dads-link" href="${esc(p.wayback)}" target="_blank" rel="noopener">見る</a></li>`).join('')}
        </ul>
        <p class="panel__note">⚠️ 残っているのは<strong>HTMLだけ</strong>で、
          当時AIが読めたかは記録されていません。それは
          <a class="dads-link" href="#scores-heading">点数の履歴</a>のほうにしかありません。</p>
      </div>`;
  }

  (async function init() {
    const [watch, scores, arch] = await Promise.all([
      loadJsonl('data/history/site-status.jsonl'),
      loadJsonl('data/history/scores.jsonl'),
      loadJson('data/archive.json'),
    ]);
    renderWatch(AidokuTrend.watchSeries(watch));
    renderScores(scores);
    renderArchive(arch);
  })();
})();
