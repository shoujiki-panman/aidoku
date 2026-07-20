// data/scores.json をそのまま描くだけ。集計は analysis/export_web.py 側で済ませてある。
// 数字の出所を1か所にしたいので、ここでは計算しない。

const VERDICT_CHIP = {
  '正解': { color: 'green', label: '正解' },
  '正解(記載なしが正しい)': { color: 'green', label: '記載なしを正しく報告' },
  '部分正解': { color: 'orange', label: '部分正解' },
  '不正解': { color: 'red', label: '不正解' },
  '不正解(幻覚)': { color: 'red', label: '幻覚' },
  '未採点': { color: 'gray', label: '未採点' },
};

const MAX = { 情報到達: 20, 抽出正確性: 40, 機械可読性: 20, オンライン明示: 20 };

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

let data = null;
let selectedId = null;

async function init() {
  const res = await fetch('data/scores.json');
  if (!res.ok) throw new Error(`データを読めませんでした (${res.status})`);
  data = await res.json();

  $('phase-note').textContent = `${data.phase} — ${data.procedure} の${data.n_municipalities}自治体ぶんの結果です`;
  $('proc-name').textContent = data.procedure;
  $('generated-at').textContent = data.generated_at;

  renderSummary();
  renderRanking();
  renderReasons();
  select(data.municipalities[0].id);
}

function renderSummary() {
  const s = data.summary;
  const stats = [
    { label: '平均スコア', value: s.average, unit: `/ ${s.max_score}点` },
    { label: '調査した自治体', value: data.n_municipalities, unit: '自治体' },
    { label: '採点した項目', value: s.n_items, unit: '項目' },
    { label: '電話・窓口への送客率', value: s.phone_referral_rate, unit: '%' },
  ];
  $('summary').innerHTML = stats.map((st) => `
    <div class="stat">
      <dt>${esc(st.label)}</dt>
      <dd>${esc(st.value)}<span class="unit"> ${esc(st.unit)}</span></dd>
    </div>`).join('');
}

function renderRanking() {
  $('ranking-body').innerHTML = data.municipalities.map((m) => {
    const cells = Object.entries(MAX).map(([k, max]) => {
      const v = m.breakdown[k];
      return `<td class="sub-cell" data-full="${v === max}">${v}/${max}</td>`;
    }).join('');
    return `
      <tr data-muni="${esc(m.id)}">
        <th scope="row">
          <button type="button" class="muni-button" data-muni="${esc(m.id)}" aria-pressed="false">${esc(m.name)}</button>
        </th>
        <td class="score-cell">${m.total}</td>
        ${cells}
        <td class="sub-cell">${m.hops ?? '-'}</td>
      </tr>`;
  }).join('');

  $('ranking-body').addEventListener('click', (e) => {
    const btn = e.target.closest('.muni-button');
    if (btn) select(btn.dataset.muni);
  });
}

function renderReasons() {
  const rows = data.summary.failure_reasons;
  $('reasons-body').innerHTML = rows.length
    ? rows.map((r) => `<tr><th scope="row">${esc(r.reason)}</th><td class="sub-cell">${r.count}件</td></tr>`).join('')
    : '<tr><td colspan="2">エージェントが答えを出せなかった項目はありませんでした。</td></tr>';
}

function chip(verdict) {
  const c = VERDICT_CHIP[verdict] || { color: 'gray', label: verdict };
  return `<span class="dads-chip-label" data-style="text" data-color="${c.color}">${esc(c.label)}</span>`;
}

function select(id) {
  selectedId = id;
  const m = data.municipalities.find((x) => x.id === id);
  if (!m) return;

  document.querySelectorAll('#ranking-body tr').forEach((tr) => {
    const on = tr.dataset.muni === id;
    tr.dataset.selected = String(on);
    const b = tr.querySelector('.muni-button');
    if (b) b.setAttribute('aria-pressed', String(on));
  });

  const fieldRows = m.fields.map((f) => `
    <tr>
      <th scope="row">${esc(f.field)}</th>
      <td>${chip(f.verdict)}</td>
      <td>${esc(f.agent_value) || `<span class="placeholder">見つからず（${esc(f.failure_reason || '-')}）</span>`}</td>
    </tr>`).join('');

  const improvements = m.improvements.length
    ? `<ul class="improve-list">${m.improvements.map((w) => `
        <li>${esc(w.field)}：${esc(w.reason)} → <span class="gain">直すと +${w.gain}点</span></li>`).join('')}</ul>`
    : '<p>4項目すべて満点です。</p>';

  $('detail').innerHTML = `
    <div class="detail-card">
      <h3 class="dads-heading" data-size="m">${esc(m.name)}（${m.total}点）</h3>
      <p class="detail-card__source">
        エージェントが読んだページ: <a class="dads-link" href="${esc(m.page_url)}" target="_blank" rel="noopener">${esc(m.page_url)}</a>
        （トップから${m.hops}ホップ${m.followed ? `／さらにリンク先を${m.followed}件開いた` : ''}）
      </p>
      <div class="dads-table" data-size="dense">
        <table class="dads-table__table">
          <caption class="dads-table__caption">項目ごとの結果</caption>
          <thead>
            <tr class="dads-table__col-header">
              <th scope="col">項目</th><th scope="col">判定</th><th scope="col">エージェントの答え</th>
            </tr>
          </thead>
          <tbody>${fieldRows}</tbody>
        </table>
      </div>
      <h4 class="dads-heading" data-size="s">ここを直すと上がります</h4>
      ${improvements}
      ${m.notes ? `<p class="section-note">エージェントの所見: ${esc(m.notes)}</p>` : ''}
    </div>`;
}

init().catch((err) => {
  $('detail').innerHTML = `<p class="placeholder">${esc(err.message)}</p>`;
  console.error(err);
});
