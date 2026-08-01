// 門番が集めたデータの画面。
//
// 出す順番は、デジタル庁「ダッシュボードデザインの実践ガイドブック」に合わせて
// 左上から右下へ、全体 → 部分 → いちばん詳しいところ（定義・入手）。
//
// いちばん上に置くのは「本物のAIはまだ来ていない」という事実。
// 見本の数字を本物に見せない。これは消せないラベルとして常に出す。
//
// ?src=https://... を付けると、公開した門番の /_aidoku/demand を直接読む。

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const nf = new Intl.NumberFormat('ja-JP');

function jstDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return new Intl.DateTimeFormat('ja-JP', {
    year: 'numeric', month: 'long', day: 'numeric',
    hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Tokyo',
  }).format(d);
}

// 見本のときは、こちらで作ったエージェント名をそのまま出さない
const agentLabel = (origin, isSample) =>
  isSample ? `見本のAI（${esc(String(origin).replace(/^https?:\/\//, ''))}）` : esc(origin);

function renderSampleBanner(data) {
  if (data.is_sample) {
    $('sample-note').textContent = String(data.sample_note ?? '').replace(/^⚠️ /, '');
    return;
  }
  // 本物のデータを読んでいるとき
  $('sample-heading').textContent = '公開中の門番から読み込んだ実データです';
  $('sample-note').textContent =
    '署名で身元が確認できたAIエージェントの来訪だけを記録しています。人（ブラウザ）のアクセスは記録していません。';
  document.querySelector('.dads-notification-banner').dataset.type = 'info';
}

function renderHeadline(data) {
  const real = data.is_sample ? 0 : (data.totals?.asks ?? 0);
  $('real-visits').textContent = nf.format(real);
  if (real === 0) {
    $('headline').dataset.state = 'empty';
    $('headline-note').textContent = data.is_sample
      ? '門番はまだ公開していません。公開すると、ここに実際の来訪が入ります。'
      : '公開していますが、まだ署名つきのAIは来ていません。';
  } else {
    $('headline').dataset.state = 'has';
    $('headline-note').textContent = 'すべて署名で身元を確かめた来訪です。';
  }
}

const STATS = [
  { key: 'asks', label: 'AIが聞きに来た', unit: '回' },
  { key: 'answered', label: '答えを持ち帰れた', unit: '回' },
  { key: 'unanswered', label: '取れずに帰った', unit: '回', star: true },
  { key: 'undetermined', label: '聞き返した', unit: '回' },
  { key: 'unverified', label: '検証に失敗', unit: '回' },
  { key: 'agents', label: '来たAI', unit: '体' },
];

function renderTotals(data) {
  const t = data.totals ?? {};
  $('totals').innerHTML = STATS.map((s) => `
    <div class="stat"${s.star ? ' data-star="true"' : ''}>
      <dt>${esc(s.label)}</dt>
      <dd>${nf.format(t[s.key] ?? 0)}<span class="unit">${esc(s.unit)}</span></dd>
    </div>`).join('');

  const rate = t.asks ? Math.round((t.unanswered / t.asks) * 100) : 0;
  $('totals-note').innerHTML =
    `聞きに来た <strong>${nf.format(t.asks ?? 0)}回</strong> のうち、` +
    `<strong>${nf.format(t.unanswered ?? 0)}回（${rate}%）</strong>が答えを見つけられずに帰りました。`;
}

function renderUnanswered(data) {
  const rows = data.unanswered ?? [];
  if (!rows.length) {
    $('unanswered-body').innerHTML =
      '<tr><td colspan="4">取れずに帰った記録はまだありません。</td></tr>';
    $('unanswered-note').textContent = '';
    return;
  }
  // 回数の多い順。同数なら自治体名で安定させる
  const sorted = [...rows].sort(
    (a, b) => b.unanswered_count - a.unanswered_count || String(a.authority).localeCompare(String(b.authority)),
  );
  $('unanswered-body').innerHTML = sorted.map((x) => `
    <tr>
      <td><span class="mark" data-tone="miss">✕ 取れず</span></td>
      <td class="q">${esc(x.looking_for ?? '（言葉が記録されていません）')}</td>
      <td class="site">
        ${esc(x.authority)}<br>
        <span class="path">${esc(x.path)}</span>
      </td>
      <td class="num">${nf.format(x.unanswered_count)}</td>
    </tr>`).join('');
  // どの探し物が、全体で何回取れなかったか（自治体をまたいで足す）
  const byQuestion = new Map();
  for (const x of sorted) {
    const k = x.looking_for ?? '（言葉なし）';
    byQuestion.set(k, (byQuestion.get(k) ?? 0) + x.unanswered_count);
  }
  const top = [...byQuestion.entries()].sort((a, b) => b[1] - a[1]);

  $('unanswered-note').innerHTML =
    `${sorted.length} 種類（自治体×探し物）。` +
    '「✕ 取れず」は色だけでなく記号でも示しています。<br>' +
    '<strong>自治体をまたいで足すと:</strong> ' +
    top.map(([q, n]) => `${esc(q)} <strong>${nf.format(n)}回</strong>`).join('／');
}

function renderAgents(data) {
  const list = data.by_agent ?? [];
  if (!list.length) {
    $('agents').innerHTML =
      '<p class="agent-empty">まだ来ていません。<span>署名で身元を確かめられたAIだけがここに並びます。</span></p>';
    return;
  }
  $('agents').innerHTML = list.map((a) => {
    const rate = a.asks ? Math.round((a.unanswered / a.asks) * 100) : 0;
    return `
    <div class="agent-card">
      <p class="agent-card__name">${agentLabel(a.agent, data.is_sample)}</p>
      <p class="agent-card__count">${nf.format(a.asks)}<span class="unit">回 聞きに来た</span></p>
      <p class="agent-card__note">
        持ち帰れた ${nf.format(a.answered)}回 ／
        <strong>手ぶら ${nf.format(a.unanswered)}回（${rate}%）</strong>
      </p>
    </div>`;
  }).join('');
}

function renderCoverage(data) {
  const c = data.coverage ?? {};
  $('coverage').innerHTML = c.truncated
    ? `⚠️ 記録が上限（${nf.format(c.limit)}件）を超えたため、<strong>直近の${nf.format(c.limit)}件だけ</strong>を集計しています（${esc(jstDate(c.from))} 〜 ${esc(jstDate(c.to))}）。古いものから外れます。`
    : `記録は全部読めています（${esc(jstDate(c.from))} 〜 ${esc(jstDate(c.to))}）。打ち切りはありません。`;
}

async function init() {
  const src = new URLSearchParams(location.search).get('src');
  const url = src ? `${src.replace(/\/$/, '')}/_aidoku/demand` : 'data/demand.json';
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) throw new Error(`データを読めませんでした (${res.status})`);
  const data = await res.json();

  renderSampleBanner(data);
  renderHeadline(data);
  renderTotals(data);
  renderUnanswered(data);
  renderAgents(data);
  renderCoverage(data);
  $('generated-at').textContent = jstDate(data.generated_at);
}

init().catch((e) => {
  $('totals-note').innerHTML = `<span class="err">${esc(e.message)}</span>`;
});
