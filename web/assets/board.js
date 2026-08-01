// 盤面。埋まっているのは実測したマスだけで、あとはグレーのまま置いておく。
// Wheelmap（車椅子で入れる店の地図）が15年続いているのは、
// 「まだ調べられていない場所」がグレーで見えていて、埋める余地が残るから。

// 手続きの一覧。転入届だけ実測済みで、あとは未調査（グレー）。
// ここを増やすには、まず「その手続きで住民が知らないと困ること」を人が決める必要がある。
const PROCEDURES = [
  { id: 'tennyu', name: '転入届', measured: true },
  { id: 'tenshutsu', name: '転出届', measured: false },
  { id: 'juminhyo', name: '住民票の写し', measured: false },
  { id: 'inkan', name: '印鑑登録', measured: false },
  { id: 'kokuho', name: '国民健康保険', measured: false },
  { id: 'jido', name: '児童手当', measured: false },
];

const ITEMS = ['必要書類', '窓口/オンライン可否', '期限', '手数料'];

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// マスの状態: 4項目のうちいくつ届いているか
function cellState(m) {
  const got = ITEMS.filter((k) => (m.breakdown[k] ?? 0) >= 20).length;
  if (got === ITEMS.length) return { tone: 'full', label: '4/4', title: '4項目とも住民のAIに届く' };
  if (got === 0) return { tone: 'none', label: '0/4', title: '4項目とも届かない' };
  return { tone: 'part', label: `${got}/4`, title: `${got}項目だけ届く` };
}

const LEGEND = [
  { tone: 'full', text: '4項目とも届く' },
  { tone: 'part', text: '一部だけ届く' },
  { tone: 'none', text: '届かない' },
  { tone: 'gray', text: 'まだ調べていない' },
];

async function init() {
  const res = await fetch('data/scores.json');
  if (!res.ok) throw new Error(`データを読めませんでした (${res.status})`);
  const data = await res.json();

  // データの更新日を出す（デジタル庁チェックリスト 16）
  const gen = $('generated-at');
  if (gen) gen.textContent = (data.generated_at || '').slice(0, 10);

  $('legend').innerHTML = LEGEND.map((l) =>
    `<span class="legend__item"><i class="cell" data-tone="${l.tone}"></i>${esc(l.text)}</span>`).join('');

  $('board-head').innerHTML =
    '<th scope="col" class="board__corner">自治体</th>' +
    PROCEDURES.map((p) =>
      `<th scope="col"${p.measured ? '' : ' class="col-gray"'}>${esc(p.name)}${
        p.measured ? '' : '<span class="col-note">未調査</span>'}</th>`).join('');

  // 実測が済んでいる区から順に（＝トップの並びのまま）
  $('board-body').innerHTML = data.municipalities.map((m) => {
    const cells = PROCEDURES.map((p) => {
      if (!p.measured) return '<td><i class="cell" data-tone="gray" title="まだ調べていない"></i></td>';
      const s = cellState(m);
      return `<td><i class="cell" data-tone="${s.tone}" title="${esc(m.name)}の${esc(p.name)}: ${esc(s.title)}">${s.label}</i></td>`;
    }).join('');
    return `<tr><th scope="row"><a class="dads-link" href="index.html#detail-heading" data-id="${esc(m.id)}">${esc(m.name)}</a></th>${cells}</tr>`;
  }).join('');

  const measured = PROCEDURES.filter((p) => p.measured).length;
  const total = PROCEDURES.length * data.municipalities.length;
  const done = measured * data.municipalities.length;

  // 表を目で追わなくても中身が分かる要約（デジタル庁チェックリスト 25「代替テキスト」）。
  // 画面にも出すので、読み上げの人だけでなく、ざっと見たい人にも効く。
  const counts = { full: 0, part: 0, none: 0 };
  for (const m of data.municipalities) counts[cellState(m).tone]++;
  $('board-summary').innerHTML =
    `${data.municipalities.length}区の${esc(PROCEDURES[0].name)}では、` +
    `<b data-tone="green">4項目とも届くのが${counts.full}区</b>、` +
    `<b data-tone="orange">一部だけ届くのが${counts.part}区</b>、` +
    `<b data-tone="red">1つも届かないのが${counts.none}区</b>。` +
    `他の${PROCEDURES.length - measured}手続きはまだ調べていません。`;
  $('board-note').innerHTML =
    `埋まっているのは <strong>${done} / ${total} マス</strong>（${data.n_municipalities}区 × ${measured}手続き）。` +
    `残りがグレーなのは、AIが読めなかったからではなく、<strong>まだ測っていないから</strong>です。<br>` +
    `グレーを埋めるには、その手続きで「住民が知らないと困ること」を人が決める必要があります。` +
    `そこはAIに任せられないので、マスは自動では埋まりません。`;

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
