// data/scores.json をそのまま描くだけ。集計は書き出し側で済ませてある。
// 主役は点数ではなく「住民のAIに聞くと、こう返ってくる」という答えそのもの。
// 答えの文はすべて実測値（agent_value）。ここで文章を作らない。

const ITEMS = ['必要書類', '窓口/オンライン可否', '期限', '手数料', 'オンライン明示'];
// 住民が知りたい4項目（オンライン明示は「書き方」の指標なので数に入れない）
const FIELDS = ['必要書類', '窓口/オンライン可否', '期限', '手数料'];
const REPORT_URL = 'https://github.com/shoujiki-panman/aidoku/blob/main/reports/aidoku_feasibility_2026-07-26.md';

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const trunc = (s, n) => (s.length > n ? s.slice(0, n) + '…' : s);

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

  renderHero();
  renderSummary();
  renderRanking();
  // 最初に見せるのは世田谷区。「情報はあるのに、入口からたどり着けない」の実例
  select('setagaya');
}

// 質問文はどの区でも同じにする（比較のため）
const question = (name) =>
  `${name}に引っ越します。${data.procedure}に必要なもの・期限・手数料を教えて。オンラインでできますか？`;

// 1項目ぶんの答え行。読めた→実測の実文／読めない→「分かりません」
function answerLine(f, maxLen) {
  if (f.verdict === '読めた') {
    const v = maxLen ? trunc(f.agent_value, maxLen) : f.agent_value;
    return `<li class="ans__item" data-ok="true"><b>${esc(f.field)}</b><span>${esc(v)}</span></li>`;
  }
  return `<li class="ans__item" data-ok="false"><b>${esc(f.field)}</b><span class="ng">このページからは分かりません</span></li>`;
}

function chatBlock(m, { maxLen = 0, withQuestion = true } = {}) {
  return `
    ${withQuestion ? `<p class="chat__q"><span class="chat__who">住民</span>「${esc(question(m.name))}」</p>` : ''}
    <div class="chat__a">
      <span class="chat__who">住民のAI</span>
      <ul class="ans">${m.fields.map((f) => answerLine(f, maxLen)).join('')}</ul>
    </div>`;
}

function renderHero() {
  const worst = data.municipalities.find((x) => x.id === 'setagaya');
  const best = data.municipalities.find((x) => x.id === 'minato');
  if (!worst || !best) { $('hero').hidden = true; return; }

  $('hero').innerHTML = `
    <p class="chat__q hero-q"><span class="chat__who">住民</span>「引っ越します。${esc(data.procedure)}に必要なもの・期限・手数料を教えて。オンラインでできますか？」</p>
    <div class="hero-grid">
      <div class="hero-card" data-kind="ng">
        <p class="hero-card__title">${esc(worst.name)}のページを読んだAI</p>
        ${chatBlock(worst, { maxLen: 60, withQuestion: false })}
        <p class="hero-card__foot">情報が無いのではありません。<b>別のページにはあるのに、入口からAIがたどり着けない</b>のが原因です（下で詳しく）。</p>
      </div>
      <div class="hero-card" data-kind="ok">
        <p class="hero-card__title">${esc(best.name)}のページを読んだAI</p>
        ${chatBlock(best, { maxLen: 60, withQuestion: false })}
        <p class="hero-card__foot">同じ質問でも、ページに書いてあれば<b>そのまま住民に届きます</b>。</p>
      </div>
    </div>`;
}

function renderSummary() {
  const s = data.summary;
  const stats = [
    { label: '4項目すべて答えられた区', value: s.full_marks, unit: '区', tone: 'green' },
    { label: 'ほぼ「分かりません」になる区', value: s.zero, unit: '区', tone: 'red' },
    { label: '手数料が答えられない区', value: s.fee_missing, unit: '区', tone: 'orange' },
    { label: '平均', value: s.average, unit: '/100点', tone: '' },
  ];
  $('summary').innerHTML = stats.map((x) => `
    <div class="stat">
      <dt class="stat__label">${esc(x.label)}</dt>
      <dd class="stat__value" data-tone="${x.tone}">${esc(x.value)}<span class="stat__unit">${esc(x.unit)}</span></dd>
    </div>`).join('');
}

// 一覧は「自治体 / 伝わった項目 / 到達」の3列に絞る。
// 内訳（どの項目が伝わらなかったか）は記号を横に並べて1列に収め、
// 詳しい中身は区を選んだあとに出す（全体 → 部分）。
function renderRanking() {
  $('ranking-body').innerHTML = data.municipalities.map((m) => {
    const got = FIELDS.filter((k) => (m.breakdown[k] ?? 0) >= 20).length;
    const marks = ITEMS.map((k) => {
      const pt = m.breakdown[k] ?? 0;
      const mark = pt >= 20 ? '✓' : pt > 0 ? '△' : '✕';
      const t = pt >= 20 ? 'green' : pt > 0 ? 'orange' : 'red';
      return `<span class="mark" data-tone="${t}" title="${esc(k)}: ${pt}/20点">${mark}</span>`;
    }).join('');
    return `
    <tr>
      <th scope="row"><button type="button" class="muni-link dads-link" data-id="${esc(m.id)}">${esc(m.name)}</button></th>
      <td class="marks">
        <b class="marks__count" data-tone="${got === 4 ? 'green' : got === 0 ? 'red' : 'orange'}">${got}/4</b>
        <span class="marks__row">${marks}</span>
      </td>
      <td class="num">${m.hops ?? '-'}</td>
    </tr>`;
  }).join('');

  $('ranking-body').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-id]');
    if (b) {
      select(b.dataset.id);
      // 見出しごと画面に入れる。結果だけ出ても「どこを見ているか」が分からなくなるため
      $('detail-heading').scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  });
}

function select(id) {
  const m = data.municipalities.find((x) => x.id === id);
  if (!m) return;
  document.querySelectorAll('.muni-link').forEach((b) =>
    b.setAttribute('aria-current', b.dataset.id === id ? 'true' : 'false'));

  const unread = m.fields.filter((f) => f.verdict !== '読めた').length;

  // なぜ読めないのか。判定AIが残した観察記録（notes）をそのまま見せる
  const why = unread > 0 && m.notes
    ? `<div class="whybox">
         <p class="whybox__title">なぜ「分かりません」になるのか</p>
         <p class="whybox__body">${esc(m.notes)}</p>
       </div>`
    : '';

  const fixes = m.improvements.length
    ? `<h3 class="dads-heading" data-size="s">ここを直すと、AIの答えが変わる</h3>
       <ul class="fixlist">${m.improvements.map((w) => `
         <li><span class="gain">+${esc(w.gain)}点</span><b>${esc(w.field)}</b>
             <span class="fixnote">${esc(w.reason)}</span></li>`).join('')}</ul>
       <p class="section-note">実測では、世田谷区のページ（手元の複製）に303文字を追記しただけで、
          4項目すべてが「分かりません」から実際の答えに変わりました
          （<a class="dads-link" href="${REPORT_URL}" target="_blank" rel="noopener">実験記録</a>）。
          値を埋めるのは職員さんです。AIが役所の情報を作り出さないよう、そこは埋めない設計にしています。
          実際の区のページは1文字も変更していません。</p>`
    : `<p class="allok">読めない箇所はありませんでした。住民がAIに尋ねても、このページからは正しい答えが返ります。</p>`;

  $('detail').innerHTML = `
    <p class="detail-head">
      <b class="detail-name">${esc(m.name)}</b>
      <span class="detail-verdict" data-tone="${unread === 0 ? 'green' : 'red'}">
        ${unread === 0 ? '4項目とも住民のAIに伝わります' : `4項目中${4 - unread}項目しか伝わりません`}
      </span>
      <span class="detail-src">トップページから ${m.hops ?? '-'} クリックで到達
        ／ <a class="dads-link" href="${esc(m.page_url)}" target="_blank" rel="noopener">診断したページ</a></span>
    </p>
    <div class="chat">${chatBlock(m)}</div>
    ${why}
    ${fixes}
    <p class="scoreline">参考: AI判読度 <b data-tone="${tone(m.total)}">${m.total}</b>/100点
      （4項目×20点＋オンライン明示20点。AI判定のため±2点の測定誤差があります）</p>`;
}

init().catch((e) => {
  $('detail').innerHTML =
    `<p class="err">${esc(e.message)}<br><code>data/scores.json</code> があるか確認してください。</p>`;
});
