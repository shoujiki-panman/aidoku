// 「この数字はどう作られたか」の画面。組み立ては pipeline-list.js（純関数）に置く。
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const P = window.AidokuPipeline;

  async function loadJson(path) {
    const r = await fetch(path);
    if (!r.ok) throw new Error(`${path}: ${r.status}`);
    return r.json();
  }

  // 外に出るのは取得層だけ。そこを見た目でも分ける
  function layerRow(l, max) {
    const pct = max ? Math.round((l.lines / max) * 100) : 0;
    const net = l.dir === 'crawler';
    return `<li class="layer" data-net="${net}">
      <div class="layer__head">
        <b class="layer__name">${esc(l.name)}</b>
        <code class="layer__dir">${esc(l.dir)}</code>
        ${net ? '<span class="layer__tag">外部に接続する</span>' : ''}
        <span class="layer__lines">${esc(String(l.lines))}行</span>
      </div>
      <div class="layer__bar"><span style="width:${pct}%"></span></div>
      <p class="layer__what">${esc(l.what)}</p>
    </li>`;
  }

  async function init() {
    try {
      const doc = await loadJson('data/pipeline.json');
      $('lead').textContent = P.headline(doc.layers);

      const max = Math.max(...doc.layers.map((l) => l.lines || 0));
      $('layers').innerHTML = `<ul class="layerlist">${
        doc.layers.map((l) => layerRow(l, max)).join('')}</ul>`;

      $('calibration').textContent = P.calibrationLine(doc.calibration);
      $('cond').textContent = P.conditionLine(doc.condition_keys);
      $('condkeys').innerHTML = doc.condition_keys.map(
        (k) => `<li><code>${esc(k)}</code></li>`).join('');
      $('exp').textContent = P.experimentLine(doc.experiment);
      $('cf').textContent = P.counterfactualLine(doc.counterfactual);

      const gen = $('generated-at');
      if (gen) gen.textContent = ((doc.experiment || {}).run_at || '').slice(0, 10);
    } catch (err) {
      $('lead').textContent = '読み込めませんでした。';
      console.error(err);
    }
  }

  document.addEventListener('DOMContentLoaded', init);
})();
