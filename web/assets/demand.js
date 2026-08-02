// 門番が集めたデータの画面。
// 並びはデジタル庁ガイドブックに合わせて 全体 → 部分 → 定義・入手。
// いちばん上に置くのは「本物のAIはまだ来ていない」という事実。見本を本物に見せない。
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
    year: 'numeric', month: 'numeric', day: 'numeric',
    hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Tokyo',
  }).format(d);
}

// 署名を配っているオリジンから、AIの種類が分かる。
// （Web Bot Auth で本番稼働しているのは ChatGPT / Claude / Perplexity / Common Crawl など）
const KNOWN_AGENTS = {
  'chatgpt.com': 'ChatGPT',
  'openai.com': 'OpenAI',
  'anthropic.com': 'Claude',
  'claude.com': 'Claude',
  'perplexity.ai': 'Perplexity',
  'google.com': 'Google',
  'googlebot.com': 'Google',
  'commoncrawl.org': 'Common Crawl',
};

function agentName(origin, isSample) {
  const host = String(origin ?? '').replace(/^https?:\/\//, '').replace(/\/$/, '');
  if (isSample) {
    // 見本でも1体ずつ見分けられるように（agent-a.example → 見本のAI A）
    const tag = (host.split('.')[0] ?? '').split('-').pop().toUpperCase();
    return { name: `見本のAI ${tag}`.trim(), sub: host };
  }
  const known = KNOWN_AGENTS[host] ?? KNOWN_AGENTS[host.replace(/^www\./, '')];
  return { name: known ?? host, sub: known ? host : '' };
}

function renderSampleBanner(data) {
  if (data.is_sample) {
    $('sample-note').textContent = String(data.sample_note ?? '').replace(/^⚠️ /, '');
    return;
  }
  $('sample-heading').textContent = '公開中の門番から読み込んだ実データです';
  $('sample-note').textContent =
    '署名で身元が確認できたAIエージェントの来訪だけを記録しています。人（ブラウザ）のアクセスは記録していません。';
  document.querySelector('.dads-notification-banner').dataset.type = 'info';
}

function renderHeadline(data) {
  const real = data.is_sample ? 0 : (data.totals?.asks ?? 0);
  $('real-visits').textContent = nf.format(real);
  $('headline').dataset.state = real === 0 ? 'empty' : 'has';
  $('headline-note').textContent = real === 0
    ? (data.is_sample
      ? '門番はまだ公開していません。公開すると、ここに実際の来訪が入ります。'
      : '公開していますが、まだ署名つきのAIは来ていません。')
    : 'すべて署名で身元を確かめた来訪です。';
}

const STATS = [
  { key: 'asks', label: '聞きに来た', unit: '回' },
  { key: 'answered', label: '持ち帰れた', unit: '回' },
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
    `聞きに来た <strong>${nf.format(t.asks ?? 0)}回</strong> のうち <strong>${nf.format(t.unanswered ?? 0)}回（${rate}%）</strong>が手ぶらで帰りました。`;
}

// 1行に「どのAIが取れずに帰ったか」を出す
function missedBy(x, isSample) {
  const names = Object.entries(x.by_agent ?? {})
    .filter(([, v]) => v.unanswered > 0)
    .map(([origin, v]) => `${agentName(origin, isSample).name}${v.unanswered > 1 ? `×${v.unanswered}` : ''}`);
  return names.length ? names.join('、') : '—';
}

function renderUnanswered(data) {
  const rows = data.unanswered ?? [];
  if (!rows.length) {
    $('unanswered-body').innerHTML = '<tr><td colspan="5">まだありません。</td></tr>';
    $('rollup').textContent = '';
    return;
  }
  const sorted = [...rows].sort(
    (a, b) => b.unanswered_count - a.unanswered_count || String(a.authority).localeCompare(String(b.authority)),
  );
  $('unanswered-body').innerHTML = sorted.map((x) => `
    <tr>
      <td><span class="mark" data-tone="miss">✕ 取れず</span></td>
      <td class="q">${esc(x.looking_for ?? '（言葉なし）')}</td>
      <td class="who">${esc(missedBy(x, data.is_sample))}</td>
      <td class="site">${esc(x.authority)}<br><span class="path">${esc(x.path)}</span></td>
      <td class="num">${nf.format(x.unanswered_count)}</td>
    </tr>`).join('');

  // 自治体をまたいで、どの探し物が何回取れなかったか
  const byQuestion = new Map();
  for (const x of sorted) {
    const k = x.looking_for ?? '（言葉なし）';
    byQuestion.set(k, (byQuestion.get(k) ?? 0) + x.unanswered_count);
  }
  $('rollup').innerHTML = [...byQuestion.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([q, n]) => `<span class="rollup__item">${esc(q)}<strong>${nf.format(n)}回</strong></span>`)
    .join('');
}

// エージェントごとの「何回来て・何ページ見て・いつからいつまで」を all から作る
function agentDetail(data) {
  const map = new Map();
  for (const x of data.all ?? []) {
    for (const [origin, v] of Object.entries(x.by_agent ?? {})) {
      const cur = map.get(origin) ?? { pages: new Set(), questions: new Set(), first: null, last: null };
      cur.pages.add(`${x.authority}${x.path}`);
      cur.questions.add(x.looking_for ?? '');
      if (!cur.first || x.first_seen < cur.first) cur.first = x.first_seen;
      if (!cur.last || x.last_seen > cur.last) cur.last = x.last_seen;
      map.set(origin, cur);
      void v;
    }
  }
  return map;
}

function renderAgents(data) {
  const list = data.by_agent ?? [];
  if (!list.length) {
    $('agents').innerHTML =
      '<p class="agent-empty">まだ来ていません。<span>署名で身元を確かめられたAIだけがここに並びます。</span></p>';
    return;
  }
  const detail = agentDetail(data);
  $('agents').innerHTML = list.map((a) => {
    const { name, sub } = agentName(a.agent, data.is_sample);
    const d = detail.get(a.agent) ?? { pages: new Set(), questions: new Set() };
    const rate = a.asks ? Math.round((a.unanswered / a.asks) * 100) : 0;
    return `
    <div class="agent-card">
      <p class="agent-card__name">${esc(name)}${sub ? `<span class="agent-card__origin">${esc(sub)}</span>` : ''}</p>
      <p class="agent-card__count">${nf.format(a.asks)}<span class="unit">回 来た</span></p>
      <p class="agent-card__note">
        ${nf.format(d.pages.size)}ページを見て、${nf.format(d.questions.size)}種類のことを聞いた<br>
        持ち帰れた ${nf.format(a.answered)}回 ／ <strong>手ぶら ${nf.format(a.unanswered)}回（${rate}%）</strong><br>
        <span class="agent-card__when">${esc(jstDate(d.first))} 〜 ${esc(jstDate(d.last))}</span>
      </p>
    </div>`;
  }).join('');
}

// どのページを見て行ったか（自治体×ページ単位にまとめ直す）
function renderPages(data) {
  const map = new Map();
  for (const x of data.all ?? []) {
    const key = `${x.authority}${x.path}`;
    const cur = map.get(key) ?? {
      authority: x.authority, path: x.path, count: 0, got: 0, missed: 0, questions: new Set(),
    };
    cur.count += x.count;
    cur.got += x.answered_count;
    cur.missed += x.unanswered_count;
    if (x.looking_for) cur.questions.add(x.looking_for);
    map.set(key, cur);
  }
  const rows = [...map.values()].sort((a, b) => b.missed - a.missed || b.count - a.count);
  if (!rows.length) {
    $('pages-body').innerHTML = '<tr><td colspan="5">まだありません。</td></tr>';
    return;
  }
  $('pages-body').innerHTML = rows.map((r) => `
    <tr>
      <td class="site">${esc(r.authority)}<br><span class="path">${esc(r.path)}</span></td>
      <td class="num">${nf.format(r.count)}</td>
      <td class="num">${nf.format(r.got)}</td>
      <td class="num${r.missed ? ' miss' : ''}">${r.missed ? `✕ ${nf.format(r.missed)}` : '0'}</td>
      <td class="q-list">${[...r.questions].map((q) => esc(q)).join('／')}</td>
    </tr>`).join('');
}

function renderCoverage(data) {
  const c = data.coverage ?? {};
  $('coverage').innerHTML = c.truncated
    ? `⚠️ 記録が上限（${nf.format(c.limit)}件）を超えたため、<strong>直近の${nf.format(c.limit)}件だけ</strong>を集計しています（${esc(jstDate(c.from))} 〜 ${esc(jstDate(c.to))}）。`
    : `集計の範囲: ${esc(jstDate(c.from))} 〜 ${esc(jstDate(c.to))}（打ち切りなし）。`;
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
  renderPages(data);
  renderCoverage(data);
  $('generated-at').textContent = jstDate(data.generated_at);
}

init().catch((e) => {
  $('totals-note').innerHTML = `<span class="err">${esc(e.message)}</span>`;
});
