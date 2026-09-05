// 自治体の担当者向けの画面。
//
// 住民向け（index.html）とは見るものが違うので、最初から分ける。
// ここには地図を出さない。担当者は自分の区を知っているので、選ぶだけでよい。
// 出すのは「読めなかった項目」「なぜ読めないか」「どう書けば届くか」の3つと、
// 持ち帰る1枚。点数の順位や、住民向けの案内は出さない。
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const FIELDS = ['必要書類', '窓口/オンライン可否', '期限', '手数料'];

  async function loadJson(path) {
    const r = await fetch(path);
    if (!r.ok) throw new Error(`${path}: ${r.status}`);
    return r.json();
  }

  let cells = [];   // 区 × 手続き
  let tops = new Map();

  function missing(c) {
    return FIELDS.filter((f) => ((c.breakdown || {})[f] ?? 0) < 20);
  }

  // 持ち帰る1枚。画面に並べたものと同じ中身を、そのまま渡せる形にする。
  function markdown(c) {
    const miss = missing(c);
    const base = new URL('.', location.href).href;
    const out = [
      `# ${c.muniName}・${c.procName} — 住民のAIが読み取れなかった項目と、書き方`, '',
      `対象ページ: ${c.url || '不明'}`,
      `測定日: ${c.generatedAt || '不明'}`,
      'AI読（アイドク）による第三者調査です。行政機関の公式発表ではありません。', '',
      '## 読み取れなかった項目', '',
      ...(miss.length ? miss.map((f) => `- ${f}`) : ['- なし（4項目とも読み取れました）']), '',
      '## どう書けば届くか', '',
    ];
    (c.improvements || []).forEach((w) => {
      out.push(`### ${w.field}（直ると +${w.gain}点）`, '', w.reason, '');
    });
    if (c.notes) out.push('## なぜ読み取れなかったか（判定したAIの観察記録）', '', c.notes, '');
    out.push('## 値はこちらでは埋めません', '',
      'AIが役所の情報を作り出さないよう、金額・期限・持ち物などの値は埋めていません。',
      'そこは職員の方が入れてください。AI読が示すのは「穴の場所」と「書き方」までです。', '',
      '---', '',
      `判定の基準: ${base}data/fact-types.json`,
      `元データの目次: ${base}data/index.json`);
    return out.join('\n');
  }

  function download(c) {
    const blob = new Blob([markdown(c)], { type: 'text/markdown;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `AI読_${c.muniName}_${c.procName}_直し方.md`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  function block(c) {
    const miss = missing(c);
    const fixes = (c.improvements || []).map((w) => `
      <li><span class="gain">+${esc(w.gain)}点</span><b>${esc(w.field)}</b>
          <span class="fixnote">${esc(w.reason)}</span></li>`).join('');
    return `<section class="fixcell">
      <h3 class="dads-heading" data-size="s">${esc(c.procName)}
        <span class="fixcell__score" data-ok="${miss.length === 0}">${FIELDS.length - miss.length}/${FIELDS.length}</span></h3>
      <p class="fixcell__page">採点したページ:
        <a class="dads-link" href="${esc(c.url || '')}" target="_blank" rel="noopener">${esc(c.url || '不明')}</a></p>
      ${miss.length
        ? `<p class="fixcell__miss">読み取れなかった項目: <b>${esc(miss.join('・'))}</b></p>`
        : '<p class="fixcell__ok">4項目とも読み取れました。住民のAIに答えが届いています。</p>'}
      ${c.notes ? `<details class="fixcell__why"><summary>なぜ読み取れなかったか（判定したAIの観察記録）</summary>
        <p>${esc(c.notes)}</p></details>` : ''}
      ${fixes ? `<p class="fixcell__lead">どう書けば届くか</p><ul class="fixlist">${fixes}</ul>` : ''}
      <p class="fixcell__acts">
        ${fixes ? `<button type="button" class="dads-button fix-dl"
                   data-key="${esc(c.muniId)}/${esc(c.procId)}">この1枚を持ち帰る（.md）</button>` : ''}
        <a class="dads-link" href="reference/journey.html?muni=${esc(c.muniId)}&proc=${esc(c.procId)}">AIがどう歩いたか</a>
      </p>
    </section>`;
  }

  function show(muniId) {
    const box = $('fix-result');
    if (!muniId) { box.innerHTML = ''; return; }
    const mine = cells.filter((c) => c.muniId === muniId);
    if (!mine.length) { box.innerHTML = '<p>この区はまだ調べていません。</p>'; return; }
    const top = tops.get(muniId);
    const done = mine.reduce((n, c) => n + (FIELDS.length - missing(c).length), 0);
    box.innerHTML = `
      <p class="fixhead"><b>${esc(mine[0].muniName)}</b>
        <span class="fixhead__sum">${done} / ${mine.length * FIELDS.length} 項目が住民のAIに届いています</span>
        ${top ? `<a class="dads-link" href="${esc(top.top_url)}" target="_blank" rel="noopener">区の公式サイト</a>` : ''}</p>
      ${mine.map(block).join('')}`;
    box.querySelectorAll('.fix-dl').forEach((b) => b.addEventListener('click', () => {
      const c = cells.find((x) => `${x.muniId}/${x.procId}` === b.dataset.key);
      if (c) download(c);
    }));
  }

  async function init() {
    try {
      const procs = (await loadJson('data/procedures.json')).procedures;
      const per = await Promise.all(procs.map(async (p) => {
        const d = await loadJson(`data/${p.file}`);
        return d.municipalities.map((m) => ({
          procId: p.id, procName: p.name, muniId: m.id, muniName: m.name,
          url: m.page_url, breakdown: m.breakdown, improvements: m.improvements || [],
          notes: m.notes || '', lgCode: m.lg_code || null,
          generatedAt: (d.generated_at || '').slice(0, 10),
        }));
      }));
      cells = per.flat();
      try {
        const doc = await loadJson('data/municipalities.json');
        tops = new Map(doc.municipalities.map((m) => [m.id, m]));
      } catch { tops = new Map(); }

      // 並びは全国地方公共団体コード順。漢字の文字コード順にしない
      const seen = new Map();
      cells.forEach((c) => { if (!seen.has(c.muniId)) seen.set(c.muniId, c); });
      const wards = [...seen.values()].sort((a, b) =>
        String(a.lgCode ?? '').localeCompare(String(b.lgCode ?? '')));
      const sel = $('fix-ward');
      sel.insertAdjacentHTML('beforeend',
        wards.map((w) => `<option value="${esc(w.muniId)}">${esc(w.muniName)}</option>`).join(''));
      sel.addEventListener('change', () => show(sel.value));

      // ?muni=setagaya で直接開く。庁内で共有するときに使える
      const want = new URLSearchParams(location.search).get('muni');
      if (want && seen.has(want)) { sel.value = want; show(want); }
    } catch (e) {
      $('fix-result').innerHTML = '<p>データを読めませんでした。時間をおいて開き直してください。</p>';
      console.error(e);
    }
  }
  init();
})();
