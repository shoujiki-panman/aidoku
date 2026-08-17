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

// 点の色分け。満点／読める／一部／読めない
const tone = (n) => (n >= 100 ? 'green' : n >= 60 ? 'blue' : n > 0 ? 'orange' : 'red');

let data = null;
let procs = [];

async function loadJson(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`データを読めませんでした (${res.status}): ${path}`);
  return res.json();
}

// サイトの見張り状態。無ければ黙って出さない（数字を作らない）。
// 判定は assets/site-status.js の Pure Function（テスト: web/test_site_status.mjs）。
async function renderSiteStatus() {
  const box = $('site-status');
  let report = null;
  try {
    const res = await fetch('data/site-status.json');
    if (res.ok) report = await res.json();
  } catch {
    report = null;
  }
  const s = AidokuSiteStatus.describe(report);
  if (s.level === 'none') { box.hidden = true; return; }

  const when = AidokuSiteStatus.formatCheckedAt(s.checkedAt);
  const rows = s.items.slice(0, 10).map((i) => `
    <li><b>${esc(i.municipality ?? '')}</b>・${esc(i.procedure ?? '')}
        <a class="dads-link" href="${esc(i.url ?? '')}" target="_blank" rel="noopener">ページ</a>
        <span class="site-status__why">${esc(i.reason ?? '')}</span></li>`).join('');

  box.hidden = false;
  box.dataset.level = s.level;
  box.innerHTML = `
    <p class="site-status__line">
      <span class="site-status__badge">サイトの見張り</span>
      <b>${esc(s.headline)}</b>
      ${when ? `<span class="site-status__when">最終確認 ${esc(when)}</span>` : ''}
    </p>
    ${s.detail ? `<p class="site-status__detail">${esc(s.detail)}</p>` : ''}
    ${rows ? `<ul class="site-status__list">${rows}</ul>` : ''}`;
}

async function init() {
  renderSiteStatus();
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

// 一番低い区／一番高い区。手続きが変わると入れ替わるので、IDを固定しない。
// municipalities は書き出し側で「点の高い順 → ID昇順」に並べてある。
const bestMuni = () => data.municipalities[0];
const worstMuni = () => data.municipalities[data.municipalities.length - 1];

// 質問文はどの区でも同じにする（比較のため）。文は targets.json 側に持たせてある。
const question = (name) => (data.question || '{muni}について教えて。').replace('{muni}', name);

// 1項目ぶんの答え行。読めた→実測の実文／読めない→「分かりません」
//
// 実文（agent_value）は各区のサイトの文なので、利用許諾の整理が済むまで公開データに
// 載せていない（quote_withheld・Issue #100）。そのときは「読み取れた」ことだけを出す。
// **読めた／読めないの判定と点数は変わらない。**
function answerLine(f, maxLen) {
  if (f.verdict === '読めた') {
    if (f.quote_withheld || !f.agent_value) {
      return `<li class="ans__item" data-ok="true"><b>${esc(f.field)}</b>
        <span class="withheld">読み取れました（本文は区の公式ページでご覧ください）</span></li>`;
    }
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

// 「今やる1件」。点数の閲覧で終わらせず、選んだ区について次の一手を1つだけ出す。
// 選ぶのは assets/next-action.js の Pure Function（テスト: web/test_next_action.mjs）。
// 文中の事実（項目・直し方・点・URL・時刻）はすべて JSON の値。ここで作らない。
function renderNextAction(m) {
  const box = $('next-action');
  const decided = AidokuNextAction.decideNextAction(m, ITEMS);
  const recheckCmd = AidokuNextAction.buildRecheckCommand(m.id, data.procedure_id);

  // 4項目が1つも読めない区。区のページに書かれていないのか、こちらが別のページを
  // 採点したのかを区別できない。区へ依頼を出さず、こちら側の一手を出す（#86）
  if (decided.kind === 'remeasure') {
    box.innerHTML = `
      <div class="next-action" data-kind="remeasure">
        <p class="next-action__head">
          <span class="next-action__chip" data-kind="ours">こちら側の一手</span>
          <span class="next-action__where"><b>${esc(m.name)}</b>・${esc(data.procedure)}</span>
        </p>
        <p class="next-action__what">このページが${esc(data.procedure)}のページか確かめて、<b>測り直す</b></p>
        <p class="next-action__why">${esc(m.page_status?.detail ?? '')}
          <br><b>区への改善依頼は出しません。</b>こちらの到達失敗を、区の不備として通知しないためです。</p>
        <dl class="next-action__facts">
          <div><dt>採点したページ</dt><dd><a class="dads-link" href="${esc(m.page_url)}" target="_blank" rel="noopener">${esc(m.page_url)}</a></dd></div>
          <div><dt>トップページからの到達</dt><dd>${esc(m.hops ?? '-')} クリック</dd></div>
        </dl>
        ${m.notes ? `
        <div class="whybox">
          <p class="whybox__title">判定したAIの観察記録</p>
          <p class="whybox__body">${esc(m.notes)}</p>
        </div>` : ''}
        ${recheckCmd ? `
        <details class="next-action__recheck">
          <summary>測り直しのコマンド</summary>
          <pre class="next-action__cmd"><code>${esc(recheckCmd)}</code></pre>
        </details>` : ''}
      </div>`;
    return;
  }

  const picked = decided.item;

  if (!picked) {
    // 全項目読めた区。架空の改善案を出さない
    box.innerHTML = `
      <div class="next-action" data-empty="true">
        <p class="next-action__none"><b>${esc(m.name)}</b>の${esc(data.procedure)}ページに、今やる1件はありません。4項目とも住民のAIに伝わっています。</p>
      </div>`;
    return;
  }

  const hasGain = typeof picked.gain === 'number' && Number.isFinite(picked.gain);
  const runs = Array.isArray(data.measurement?.runs) ? data.measurement.runs : [];
  const run = runs.find((r) => r.municipality_id === m.id);
  // legacy_unknown の測定は実行時刻が残っていない。推測で埋めず「記録なし」と出す
  const measuredAt = run?.run_at
    ? run.run_at.slice(0, 16).replace('T', ' ')
    : '記録なし（測定条件の記録を始める前の測定です）';

  const request = AidokuNextAction.buildRequestText({
    muniName: m.name,
    procedureName: data.procedure,
    field: picked.field,
    reason: picked.reason ?? '',
    pageUrl: m.page_url ?? '',
    gain: picked.gain,
  });
  const recheck = recheckCmd;

  box.innerHTML = `
    <div class="next-action">
      <p class="next-action__head">
        <span class="next-action__chip">未検証の提案</span>
        <span class="next-action__where"><b>${esc(m.name)}</b>・${esc(data.procedure)}</span>
      </p>
      <p class="next-action__what">「<b>${esc(picked.field)}</b>」をページに書き足す — ${esc(picked.reason ?? '')}</p>
      <p class="next-action__why">なぜこの1件: 読めなかった項目のうち、見込み効果が最大だからです${hasGain ? `（+${esc(picked.gain)}点）` : ''}。</p>
      <dl class="next-action__facts">
        <div><dt>現在</dt><dd>${esc(m.total)}/100点</dd></div>
        ${hasGain ? `<div><dt>直すと（見込み）</dt><dd>${esc(m.total + picked.gain)}/100点 — 実ページの再測定までは未検証</dd></div>` : ''}
        <div><dt>対象ページ</dt><dd><a class="dads-link" href="${esc(m.page_url)}" target="_blank" rel="noopener">${esc(m.page_url)}</a></dd></div>
        <div><dt>測定日時</dt><dd>${esc(measuredAt)}</dd></div>
      </dl>
      ${request ? `
      <div class="next-action__request">
        <p class="next-action__request-title"><b>担当部署へ渡せる依頼文</b>（コピーして使えます。こちらから自動では送りません）</p>
        <textarea class="next-action__text" id="request-text" readonly rows="10">${esc(request)}</textarea>
        <p class="next-action__request-foot">
          <button type="button" class="next-action__copy" id="copy-request">依頼文をコピー</button>
          <span id="copy-done" role="status" aria-live="polite"></span>
        </p>
      </div>` : ''}
      ${recheck ? `
      <details class="next-action__recheck">
        <summary>直したあとの再確認のしかた</summary>
        <p class="section-note">直しても、同じ条件で再測定するまでは「改善確認済み」と言いません。再測定のコマンド:</p>
        <pre class="next-action__cmd"><code>${esc(recheck)}</code></pre>
      </details>` : ''}
    </div>`;

  const btn = $('copy-request');
  if (btn) {
    btn.addEventListener('click', async () => {
      const ta = $('request-text');
      try {
        await navigator.clipboard.writeText(ta.value);
      } catch {
        ta.select();
        document.execCommand('copy');
      }
      $('copy-done').textContent = 'コピーしました';
    });
  }
}

function select(id) {
  const m = data.municipalities.find((x) => x.id === id);
  if (!m) return;
  document.querySelectorAll('.muni-link').forEach((b) =>
    b.setAttribute('aria-current', b.dataset.id === id ? 'true' : 'false'));

  renderNextAction(m);

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
      （4項目×20点＋オンライン明示20点。各項目は「読めた／読めない」の2値なので、判定が1つ変わると20点動きます）</p>`;
}

init().catch((e) => {
  $('detail').innerHTML =
    `<p class="err">${esc(e.message)}<br><code>data/scores.json</code> があるか確認してください。</p>`;
});
