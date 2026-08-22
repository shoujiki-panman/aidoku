// 盤面。埋まっているのは実測したマスだけで、あとはグレーのまま置いておく。
// Wheelmap（車椅子で入れる店の地図）が15年続いているのは、
// 「まだ調べられていない場所」がグレーで見えていて、埋める余地が残るから。

// 実測済みの手続きは data/procedures.json から読む。ここに手で書くと、
// 手続きを増やすたびに JS を直すことになる（書き出し側と二重管理になる）。
// 未調査の手続きは、まだデータが無いのでここに置く。グレーの列として出す。
const UNMEASURED = [
  { id: 'tenshutsu', name: '転出届' },
  { id: 'juminhyo', name: '住民票の写し' },
  { id: 'inkan', name: '印鑑登録' },
  { id: 'kokuho', name: '国民健康保険' },
];

// 項目名は data/fact-types.json が唯一の出どころ。ここに直書きしない。
// この画面が使うのは display_label（scores-*.json の breakdown のキー）。
let ITEMS = [];

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

async function loadJson(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`データを読めませんでした (${res.status}): ${path}`);
  return res.json();
}

// マスの状態: 4項目のうちいくつ届いているか
function cellState(m) {
  const got = ITEMS.filter((k) => (m.breakdown[k] ?? 0) >= 20).length;
  if (got === ITEMS.length) return { tone: 'full', label: '4/4', title: '4項目とも住民のAIに届く', got };
  if (got === 0) return { tone: 'none', label: '0/4', title: '4項目とも届かない', got };
  return { tone: 'part', label: `${got}/4`, title: `${got}項目だけ届く`, got };
}

const LEGEND = [
  { tone: 'full', text: '4項目とも届く' },
  { tone: 'part', text: '一部だけ届く' },
  { tone: 'none', text: '届かない' },
  { tone: 'gray', text: 'まだ調べていない' },
  { tone: 'stale', text: 'ページが変わった（測り直しが要る）' },
];

// 見張りが「変わった」と言ったマス。毎朝の確認で入れ替わるので、盤面はここだけ動く。
// ★これは「悪くなった」ではなく「測り直しが必要」の意味（site-status.json の _about）。
let STALE = new Set();
const staleKey = (muniId, procId) => `${muniId}:${procId}`;

async function loadStale() {
  try {
    const r = await fetch('data/site-status.json');
    if (!r.ok) return { set: new Set(), checkedAt: null };
    const d = await r.json();
    const set = new Set((d.items || [])
      .filter((i) => i && i.changed === true)
      .map((i) => staleKey(i.municipality_id, i.procedure_id)));
    return { set, checkedAt: d.checked_at || null };
  } catch {
    return { set: new Set(), checkedAt: null };
  }
}

// 盤面ぜんぶで、住民のAIに届いている項目の数。23区 × 3手続き × 4項目 が満点
function totalProgress(rows, procs) {
  let got = 0;
  let total = 0;
  for (const r of rows) {
    for (const p of procs) {
      const c = r.cells[p.id];
      if (!c) continue;
      got += c.got;
      total += ITEMS.length;
    }
  }
  return { got, total, pct: total ? Math.round((got / total) * 100) : 0 };
}

function renderProgress(rows, procs, checkedAt) {
  const pr = totalProgress(rows, procs);
  const stale = [...STALE].length;
  $('board-progress').innerHTML = `
    <div class="meter">
      <div class="meter__head">
        <b class="meter__num">${pr.pct}<span>%</span></b>
        <span class="meter__label">
          住民のAIに届いている項目 <b>${pr.got} / ${pr.total}</b>
          <span class="meter__sub">（23区 × 3手続き × 4項目）</span>
        </span>
      </div>
      <div class="meter__bar"><span style="width:${pr.pct}%"></span></div>
      ${stale ? `<p class="meter__quest">
          <b data-tone="amber">${stale}マス</b>が
          <b>測り直し待ち</b>です — 毎朝の見張りが「ページが変わった」と見つけたマス。
          <span class="meter__sub">盤面では枠が光っています。悪くなったという意味ではありません。</span>
        </p>` : ''}
    </div>`;
}

// 手続きごとの scores-*.json を、自治体IDで引ける形にまとめる。
// 手続きによって測った区が違っても崩れないよう、行は全手続きの和集合で作る。
function indexByMuni(procs, docs) {
  const rows = new Map(); // id -> { id, name, cells: {procId: state} }
  procs.forEach((p, i) => {
    for (const m of docs[i].municipalities) {
      const row = rows.get(m.id) || { id: m.id, name: m.name, cells: {} };
      row.cells[p.id] = cellState(m);
      rows.set(m.id, row);
    }
  });
  return [...rows.values()];
}

// 並びは「届いた項目の合計が多い順 → ID昇順」。
// 1手続きの点で並べると、その手続きが得意なだけの区が上に来てしまう。
function sortRows(rows, procs) {
  const score = (r) => procs.reduce((n, p) => n + (r.cells[p.id]?.got ?? 0), 0);
  return rows.sort((a, b) => score(b) - score(a) || (a.id < b.id ? -1 : 1));
}

function renderHead(procs) {
  $('board-head').innerHTML =
    '<th scope="col" class="board__corner">自治体</th>' +
    procs.map((p) => `<th scope="col">${esc(p.name)}</th>`).join('') +
    UNMEASURED.map((p) =>
      `<th scope="col" class="col-gray">${esc(p.name)}<span class="col-note">未調査</span></th>`).join('');
}

// マスを押すと、その区・その手続きの詳細が開く。
// 押した先が毎回同じ画面だと、盤面を見る意味がなくなる。
const detailUrl = (muniId, procId) =>
  `index.html?muni=${encodeURIComponent(muniId)}&proc=${encodeURIComponent(procId)}#detail-heading`;

function renderBody(rows, procs) {
  $('board-body').innerHTML = rows.map((r) => {
    const measured = procs.map((p) => {
      const s = r.cells[p.id];
      if (!s) return '<td><i class="cell" data-tone="gray" title="この区は測っていない"></i></td>';
      const stale = STALE.has(staleKey(r.id, p.id));
      const t = `${esc(r.name)}の${esc(p.name)}: ${esc(s.title)}`
        + (stale ? '｜ページが変わったので測り直しが要る' : '');
      return `<td><a class="cell" data-tone="${s.tone}"${stale ? ' data-stale="true"' : ''}
        href="${detailUrl(r.id, p.id)}" title="${t}"><span class="sr-only">${esc(r.name)}の${esc(p.name)}: </span>${s.label}</a></td>`;
    }).join('');
    const gray = UNMEASURED.map(() =>
      '<td><i class="cell" data-tone="gray" title="まだ調べていない"></i></td>').join('');
    return `<tr><th scope="row"><a class="dads-link" href="${detailUrl(r.id, procs[0].id)}">${esc(r.name)}</a></th>${measured}${gray}</tr>`;
  }).join('');
}

// 表を目で追わなくても中身が分かる要約（デジタル庁チェックリスト 25「代替テキスト」）。
// 画面にも出すので、読み上げの人だけでなく、ざっと見たい人にも効く。
function renderSummary(rows, procs) {
  const lines = procs.map((p) => {
    const c = { full: 0, part: 0, none: 0 };
    for (const r of rows) if (r.cells[p.id]) c[r.cells[p.id].tone]++;
    return `<li><b>${esc(p.name)}</b>：` +
      `<b data-tone="green">4項目とも届く ${c.full}区</b>／` +
      `<b data-tone="orange">一部だけ ${c.part}区</b>／` +
      `<b data-tone="red">1つも届かない ${c.none}区</b></li>`;
  }).join('');
  $('board-summary').innerHTML = `<ul class="board-summary__list">${lines}</ul>`;
}

function renderNote(rows, procs) {
  const cols = procs.length + UNMEASURED.length;
  const total = cols * rows.length;
  const done = procs.reduce((n, p) => n + rows.filter((r) => r.cells[p.id]).length, 0);
  $('board-note').innerHTML =
    `埋まっているのは <strong>${done} / ${total} マス</strong>（${rows.length}区 × ${cols}手続き）。` +
    `残りがグレーなのは、AIが読めなかったからではなく、<strong>まだ測っていないから</strong>です。<br>` +
    `グレーを埋めるには、その手続きで「住民が知らないと困ること」を人が決める必要があります。` +
    `そこはAIに任せられないので、マスは自動では埋まりません。`;
}

async function init() {
  const ft = await loadJson('data/fact-types.json');
  ITEMS = ft.fact_types.map((f) => f.display_label);

  const procs = (await loadJson('data/procedures.json')).procedures;
  const docs = await Promise.all(procs.map((p) => loadJson(`data/${p.file}`)));

  // データの更新日を出す（デジタル庁チェックリスト 16）。手続きごとに測った日が違うので、
  // 一番古いものを出す。新しい方を出すと、古い列まで新しく見える。
  const gen = $('generated-at');
  if (gen) gen.textContent = docs.map((d) => (d.generated_at || '').slice(0, 10)).sort()[0];

  $('legend').innerHTML = LEGEND.map((l) =>
    `<span class="legend__item"><i class="cell" data-tone="${l.tone}"></i>${esc(l.text)}</span>`).join('');

  const st = await loadStale();
  STALE = st.set;

  const rows = sortRows(indexByMuni(procs, docs), procs);
  renderProgress(rows, procs, st.checkedAt);
  renderHead(procs);
  renderBody(rows, procs);
  renderSummary(rows, procs);
  renderNote(rows, procs);
  renderVisits();
}

// 門番が集める「どのAIが来たか」。まだ門番を自治体サイトの前に立てていないので、
// ここは全部グレー。実データが入ったら差し替える（憶測の数字は置かない）。
const AGENTS = [
  { name: 'ChatGPT', origin: 'chatgpt.com', note: '公開鍵を配布中（確認済み）' },
  { name: 'Claude', origin: 'claude.com', note: '未確認' },
  { name: 'Perplexity', origin: 'perplexity.ai', note: '未確認' },
  { name: 'Gemini', origin: 'google.com', note: '未確認' },
];

function renderVisits() {
  $('visit').innerHTML = AGENTS.map((a) => `
    <div class="visit-card" data-state="gray">
      <p class="visit-card__name">${esc(a.name)}</p>
      <p class="visit-card__count">— 回</p>
      <p class="visit-card__note">まだ来ていません<br><span class="visit-card__sub">${esc(a.note)}</span></p>
    </div>`).join('');
}

init().catch((e) => {
  $('board-note').innerHTML = `<span class="err">${esc(e.message)}</span>`;
});
