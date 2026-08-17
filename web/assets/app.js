// data/scores.json をそのまま描くだけ。集計は書き出し側で済ませてある。
// 主役は点数ではなく「住民のAIに聞くと、こう返ってくる」という答えそのもの。
// 答えの文はすべて実測値（agent_value）。ここで文章を作らない。

// 項目名は data/fact-types.json が唯一の出どころ。ここに直書きしない。
// （直書きしていた頃、app.js は「窓口/オンライン可否」、barrier.js は
//   「窓口オンライン可否」を使っていて、同じものが別名で並んでいた）
// この画面が使うのは display_label のほう（scores-*.json の breakdown のキー）。
let ITEMS = [];
// 住民が知りたい4項目（オンライン明示は「書き方」の指標なので数に入れない）
let FIELDS = [];
const REPORT_URL = 'https://github.com/shoujiki-panman/aidoku/blob/main/reports/aidoku_feasibility_2026-07-26.md';

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const trunc = (s, n) => (s.length > n ? s.slice(0, n) + '…' : s);

// 検証済み点数の色分け。null（未検証）には使わない。
const tone = (n) => (n >= 100 ? 'green' : n >= 60 ? 'blue' : n > 0 ? 'orange' : 'red');
const fieldFor = (m, label) => m.fields.find((f) => f.field === label);
const answered = (f) => typeof f?.answered === 'boolean' ? f.answered : f?.verdict === '読めた';
const scoreText = (m) => m.total == null ? '未検証' : `${m.total}/100点`;
const gainText = (improvement) => {
  if (improvement.gain == null) return '点数未検証';
  return FIELDS.includes(improvement.field)
    ? `+${improvement.gain}点`
    : `明示度 +${improvement.gain}点`;
};

let data = null;
let procs = [];

async function loadJson(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`データを読めませんでした (${res.status}): ${path}`);
  return res.json();
}

async function init() {
  const ft = await loadJson('data/fact-types.json');
  FIELDS = ft.fact_types.map((f) => f.display_label);
  ITEMS = [...FIELDS, ...ft.extra_measures.map((m) => m.display_label)];

  procs = (await loadJson('data/procedures.json')).procedures;
  renderProcTabs();
  // 盤面から「区名」を押して来たときは、その区を開く（?muni=setagaya&proc=tennyu）。
  // これが無いと、どの区を押しても同じ画面が出る。
  const q = new URLSearchParams(location.search);
  await loadProcedure(q.get('proc') || procs[0].id, q.get('muni'));
}

async function loadProcedure(id, muniId = null) {
  const p = procs.find((x) => x.id === id) || procs[0];
  data = await loadJson(`data/${p.file}`);

  document.querySelectorAll('.proc-tab').forEach((b) => {
    b.setAttribute('aria-selected', String(b.dataset.proc === p.id));
  });

  $('phase-note').textContent =
    `${data.phase}の${data.procedure}を、AIに読ませた結果です（${data.n_municipalities}自治体）`;
  $('proc-name').textContent = data.procedure;
  $('generated-at').textContent = (data.generated_at || '').slice(0, 10);

  renderHero();
  renderSummary();
  renderRanking();
  // 指定が無ければ一番低い区。「情報はあるのに、入口からたどり着けない」の実例
  const target = muniId && data.municipalities.some((m) => m.id === muniId) ? muniId : worstMuni().id;
  select(target);
}

function renderProcTabs() {
  $('proc-tabs').innerHTML = procs.map((p) => `
    <button type="button" class="proc-tab" role="tab" data-proc="${esc(p.id)}"
            aria-selected="false">${esc(p.name)}</button>`).join('');
  $('proc-tabs').addEventListener('click', (e) => {
    const b = e.target.closest('.proc-tab');
    if (b) loadProcedure(b.dataset.proc);
  });
}

// 回答できた項目が最少／最多の区。正しさ未検証の値を点数順にはしない。
// municipalities は書き出し側で「回答数の多い順 → ID昇順」に並べてある。
const bestMuni = () => data.municipalities[0];
const worstMuni = () => data.municipalities[data.municipalities.length - 1];

// 質問文はどの区でも同じにする（比較のため）。文は targets.json 側に持たせてある。
const question = (name) => (data.question || '{muni}について教えて。').replace('{muni}', name);

// 1項目ぶんの答え行。読めた→実測の実文／読めない→「分かりません」
function answerLine(f, maxLen) {
  if (answered(f)) {
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
  const worst = worstMuni();
  const best = bestMuni();
  if (!worst || !best || worst.id === best.id) { $('hero').hidden = true; return; }
  $('hero').hidden = false;

  $('hero').innerHTML = `
    <p class="chat__q hero-q"><span class="chat__who">住民</span>「${esc(question('◯◯区'))}」</p>
    <div class="hero-grid">
      <div class="hero-card" data-kind="ng">
        <p class="hero-card__title">${esc(worst.name)}のページを読んだAI</p>
        ${chatBlock(worst, { maxLen: 60, withQuestion: false })}
        <p class="hero-card__foot">情報が無いのではありません。<b>別のページにはあるのに、入口からAIがたどり着けない</b>のが原因です（下で詳しく）。</p>
      </div>
      <div class="hero-card" data-kind="ok">
        <p class="hero-card__title">${esc(best.name)}のページを読んだAI</p>
        ${chatBlock(best, { maxLen: 60, withQuestion: false })}
        <p class="hero-card__foot">同じ質問でも、このページからは<b>4項目の回答が返りました</b>。回答の正しさは4判定Evaluatorで別に検証します。</p>
      </div>
    </div>`;
}

function renderSummary() {
  const s = data.summary;
  const stats = [
    { label: '4項目すべて回答が返った区', value: s.answered_all_four, unit: '区', tone: 'green' },
    { label: '4項目とも回答が無い区', value: s.answered_zero, unit: '区', tone: 'red' },
    { label: '手数料が答えられない区', value: s.fee_missing, unit: '区', tone: 'orange' },
    { label: '4判定まで検証済み', value: s.evaluated, unit: '区', tone: '' },
  ];
  $('summary').innerHTML = stats.map((x) => `
    <div class="stat">
      <dt class="stat__label">${esc(x.label)}</dt>
      <dd class="stat__value" data-tone="${x.tone}">${esc(x.value)}<span class="stat__unit">${esc(x.unit)}</span></dd>
    </div>`).join('');
}

// 一覧は「自治体 / 回答が返った項目 / 到達」の3列に絞る。
// 内訳（どの項目に回答が無かったか）は記号を横に並べて1列に収め、
// 詳しい中身は区を選んだあとに出す（全体 → 部分）。
function renderRanking() {
  $('ranking-body').innerHTML = data.municipalities.map((m) => {
    const got = FIELDS.filter((k) => answered(fieldFor(m, k))).length;
    const marks = ITEMS.map((k) => {
      const field = fieldFor(m, k);
      if (field) {
        const ok = answered(field);
        const status = field.evaluation_status === 'pass' ? '検証済み' :
          field.evaluation_status === 'fail' ? '検証不合格' : '正しさ未検証';
        return `<span class="mark" data-tone="${ok ? 'green' : 'red'}" title="${esc(k)}: ${ok ? 'AI回答あり' : '回答なし'}／${status}">${ok ? '✓' : '✕'}</span>`;
      }
      const pt = m.breakdown[k] ?? 0;
      const mark = pt >= 20 ? '✓' : pt > 0 ? '△' : '✕';
      const t = pt >= 20 ? 'green' : pt > 0 ? 'orange' : 'red';
      return `<span class="mark" data-tone="${t}" title="${esc(k)}: 明示度 ${pt}/20">${mark}</span>`;
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

  const unread = m.fields.filter((f) => !answered(f)).length;

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
         <li><span class="gain">${esc(gainText(w))}</span><b>${esc(w.field)}</b>
             <span class="fixnote">${esc(w.reason)}</span></li>`).join('')}</ul>
       <p class="section-note">実測では、世田谷区のページ（手元の複製）に303文字を追記しただけで、
          4項目すべてが「分かりません」から実際の答えに変わりました
          （<a class="dads-link" href="${REPORT_URL}" target="_blank" rel="noopener">実験記録</a>）。
          値を埋めるのは職員さんです。AIが役所の情報を作り出さないよう、そこは埋めない設計にしています。
          実際の区のページは1文字も変更していません。</p>`
    : `<p class="allok">4項目とも回答が返りました。回答が正しいかは、下の4判定Evaluatorで別に確認します。</p>`;

  const score = m.total == null
    ? `<p class="scoreline">4判定による点数: <b>未検証</b>。回答が返っただけでは加点しません。</p>`
    : `<p class="scoreline">4判定による点数: <b data-tone="${tone(m.total)}">${esc(scoreText(m))}</b></p>`;

  $('detail').innerHTML = `
    <p class="detail-head">
      <b class="detail-name">${esc(m.name)}</b>
      <span class="detail-verdict" data-tone="${unread === 0 ? 'green' : 'red'}">
        ${unread === 0 ? '4項目ともAI回答あり' : `4項目中${4 - unread}項目にAI回答あり`}
      </span>
      <span class="detail-src">トップページから ${m.hops ?? '-'} クリックで到達
        ／ <a class="dads-link" href="${esc(m.page_url)}" target="_blank" rel="noopener">診断したページ</a></span>
    </p>
    <div class="chat">${chatBlock(m)}</div>
    ${why}
    ${fixes}
    ${score}`;
}

init().catch((e) => {
  $('detail').innerHTML =
    `<p class="err">${esc(e.message)}<br><code>data/scores.json</code> があるか確認してください。</p>`;
});
