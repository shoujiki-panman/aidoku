// data/scores.json をそのまま描くだけ。集計は書き出し側で済ませてある。
// 見せるのは2つ ——「AIが何を読み取れたか」と「どこを直せば伝わるか」。

const ITEMS = ['必要書類', '窓口/オンライン可否', '期限', '手数料', 'オンライン明示'];

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// 点の色分け。満点／読める／一部／読めない
const tone = (n) => (n >= 100 ? 'green' : n >= 60 ? 'blue' : n > 0 ? 'orange' : 'red');

let data = null;

async function init() {
  const res = await fetch('data/scores.json');
  if (!res.ok) throw new Error(`データを読めませんでした (${res.status})`);
  data = await res.json();

  $('phase-note').textContent =
    `${data.phase}の${data.procedure}を、AIに読ませた結果です（${data.n_municipalities}自治体）`;
  $('proc-name').textContent = data.procedure;
  $('generated-at').textContent = (data.generated_at || '').slice(0, 10);

  renderSummary();
  renderRanking();
  // 最初に出すのは最下位。直す価値がいちばん大きいところから見せる
  select(data.municipalities[data.municipalities.length - 1].id);
}

function renderSummary() {
  const s = data.summary;
  const stats = [
    { label: '4項目すべて読めた区', value: s.full_marks, unit: '区', tone: 'green' },
    { label: 'ほとんど読めない区', value: s.zero, unit: '区', tone: 'red' },
    { label: '手数料が見つからない区', value: s.fee_missing, unit: '区', tone: 'orange' },
    { label: '平均', value: s.average, unit: '/100点', tone: '' },
  ];
  $('summary').innerHTML = stats.map((x) => `
    <div class="stat">
      <dt class="stat__label">${esc(x.label)}</dt>
      <dd class="stat__value" data-tone="${x.tone}">${esc(x.value)}<span class="stat__unit">${esc(x.unit)}</span></dd>
    </div>`).join('');
}

function renderRanking() {
  $('ranking-body').innerHTML = data.municipalities.map((m) => `
    <tr>
      <th scope="row"><button type="button" class="muni-link dads-link" data-id="${esc(m.id)}">${esc(m.name)}</button></th>
      <td class="num" data-tone="${tone(m.total)}"><b>${m.total}</b></td>
      ${ITEMS.map((k) => {
        const pt = m.breakdown[k] ?? 0;
        const mark = pt >= 20 ? '✓' : pt > 0 ? '△' : '✕';
        const t = pt >= 20 ? 'green' : pt > 0 ? 'orange' : 'red';
        return `<td class="mark" data-tone="${t}" title="${pt}/20点">${mark}</td>`;
      }).join('')}
      <td class="num">${m.hops ?? '-'}</td>
    </tr>`).join('');

  $('ranking-body').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-id]');
    if (b) select(b.dataset.id);
  });
}

function select(id) {
  const m = data.municipalities.find((x) => x.id === id);
  if (!m) return;
  document.querySelectorAll('.muni-link').forEach((b) =>
    b.setAttribute('aria-current', b.dataset.id === id ? 'true' : 'false'));

  const fixes = m.improvements.length
    ? `<h3 class="dads-heading" data-size="s">直すとしたら</h3>
       <ul class="fixlist">${m.improvements.map((w) => `
         <li><span class="gain">+${esc(w.gain)}点</span><b>${esc(w.field)}</b>
             <span class="fixnote">${esc(w.reason)}</span></li>`).join('')}</ul>
       <p class="section-note">これは「どこに、どう書けば伝わるか」の目安です。
          実際の値（窓口名・受付時間など）は各自治体でご確認ください。
          AIが役所の情報を作り出さないよう、そこは埋めない設計にしています。</p>`
    : `<p class="allok">読めない箇所はありませんでした。住民がAIに尋ねても、このページからは正しい答えが返ります。</p>`;

  $('detail').innerHTML = `
    <p class="detail-head">
      <b class="detail-name">${esc(m.name)}</b>
      <span class="detail-score" data-tone="${tone(m.total)}">${m.total}/100点</span>
      <span class="detail-src">トップページから ${m.hops ?? '-'} クリックで到達
        ／ <a class="dads-link" href="${esc(m.page_url)}" target="_blank" rel="noopener">診断したページ</a></span>
    </p>
    <dl class="dads-description-list readlist">
      ${m.fields.map((f) => `
        <div class="dads-description-list__item">
          <dt class="dads-description-list__term" data-tone="${f.verdict === '読めた' ? 'green' : 'red'}">
            ${f.verdict === '読めた' ? '✓' : '✕'} ${esc(f.field)}
          </dt>
          <dd class="dads-description-list__description">
            ${f.verdict === '読めた'
              ? esc(f.agent_value)
              : '<i class="ng">AIには読み取れませんでした</i>'}
          </dd>
        </div>`).join('')}
    </dl>
    ${fixes}`;
}

init().catch((e) => {
  $('detail').innerHTML =
    `<p class="err">${esc(e.message)}<br><code>data/scores.json</code> があるか確認してください。</p>`;
});
