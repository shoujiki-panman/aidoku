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
// 要素が無くても落とさない。画面から節を外したときに JS が道連れにならないようにする
const setText = (id, text) => { const el = $(id); if (el) el.textContent = text; };
const setHtml = (id, html) => { const el = $(id); if (el) el.innerHTML = html; };
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
        <a class="dads-link" href="${esc(i.url ?? '')}" target="_blank" rel="noopener">区の公式ページ</a>
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
    ${rows ? `<details class="site-status__more">
                <summary>どのページが変わったか（${s.items.length}件）</summary>
                <ul class="site-status__list">${rows}</ul>
              </details>` : ''}`;
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
  initLookup();
}

async function loadProcedure(id, muniId = null) {
  const p = procs.find((x) => x.id === id) || procs[0];
  data = await loadJson(`data/${p.file}`);

  document.querySelectorAll('.proc-tab').forEach((b) => {
    b.setAttribute('aria-selected', String(b.dataset.proc === p.id));
  });

  // 手続きタブは「まとめて見る」のときしか出さない。ここで
  // 「転入届の結果です」と言い切ると、別の手続きを開いたときに嘘になる。
  $('phase-note').textContent =
    `${data.phase}を、住民のAIに読ませて測った結果です（${data.n_municipalities}自治体）`;
  setText('proc-name', data.procedure);
  $('generated-at').textContent = (data.generated_at || '').slice(0, 10);

  renderHero();
  renderSummary();
  renderRanking();
  // 指定が無ければ一番低い区。「情報はあるのに、入口からたどり着けない」の実例
  // ★押していないのに「押した区」と書くと嘘になる。どちらなのかを言い分ける
  const chosen = muniId && data.municipalities.some((m) => m.id === muniId);
  const target = chosen ? muniId : worstMuni().id;
  setHtml('na-scope', chosen ? '選んだ区について、'
    : 'この手続きで<strong>いちばん点が低い区</strong>を例として出しています。');
  setHtml('detail-scope', chosen ? '選んだ区の、' : '例として出している区の、');
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
  // ①23区の一覧は画面から外した（盤面が上位互換）。要素が無ければ何もしない
  if (!$('ranking-body')) return;
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
          <span class="next-action__chip" data-kind="ours">原因はAI読側</span>
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
          <summary>測り直す手順（開発者向け）</summary>
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
    ? `<h3 class="dads-heading" data-size="s">区のページをこう直すと、AIの答えが変わる<span class="forwhom">自治体の担当者向け</span></h3>
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
        ${unread === 0 ? '4項目とも読み取れました' : `4項目のうち読み取れたのは${4 - unread}項目です`}
      </span>
      <span class="detail-src">トップページから ${m.hops ?? '-'} クリックで到達
        ／ <a class="dads-link" href="${esc(m.page_url)}" target="_blank" rel="noopener">採点したページ</a></span>
    </p>
    <div class="chat">${chatBlock(m)}</div>
    ${why}
    ${fixes}
    <p class="scoreline">参考: 100点満点での点数 <b data-tone="${tone(m.total)}">${m.total}</b>/100点
      （4項目×20点＋オンライン明示20点。各項目は「読めた／読めない」の2値なので、判定が1つ変わると20点動きます）</p>`;
}

init().catch((e) => {
  $('detail').innerHTML =
    `<p class="err">結果を読めませんでした。時間をおいて開き直してください。</p>`;
});

// ---- 自分の区を調べる（#59 案2: 測定済みは即答、未測定は正直にそう言う）----
// ★ここで新しく判定はしない。判定は claude -p をローカルで呼ぶ設計で、
//   静的ホスティングからは動かせない。当てずっぽうを返さないことが仕様。
//   盤面のグレーと同じ約束 — 測っていないものを、測ったように見せない。
let lookupCells = null;
let muniTop = null;   // 区id → 区の公式サイト
let journeyOf = null; // 区id/手続きid → AIの道のり
let archiveByUrl = null;

// 過去の姿は Internet Archive / WARP が既に持っている（Issue #99）。
// こちらはコピーを持たず、「いつの版があるか」だけを出してリンクで渡す。
// ファイルが無くても画面は壊さない（提出前に生成していない場合がある）。
async function loadArchive() {
  if (archiveByUrl) return archiveByUrl;
  archiveByUrl = new Map();
  try {
    const r = await fetch('data/archive.json');
    if (r.ok) {
      const d = await r.json();
      for (const p of d.pages || []) if (p && p.url) archiveByUrl.set(p.url, p);
    }
  } catch { /* 無ければ出さないだけ */ }
  return archiveByUrl;
}

const ymd = (ts) => (typeof ts === 'string' && ts.length >= 8
  ? `${ts.slice(0, 4)}-${ts.slice(4, 6)}-${ts.slice(6, 8)}` : '');

function archiveLine(rec) {
  if (!rec) return '';
  if (!rec.snapshots) {
    return `<p class="fmp__line"><b>過去の姿</b>
      <span class="fmp__none">Internet Archive に版がありません</span></p>`;
  }
  return `<p class="fmp__line"><b>過去の姿</b>
      <b>${rec.snapshots}版</b>（${esc(ymd(rec.first))} 〜 ${esc(ymd(rec.last))}）
      <a class="dads-link" href="${esc(rec.wayback)}" target="_blank" rel="noopener">Internet Archive で見る</a>
      <span class="fmp__note">※ 残っているのはHTMLだけで、当時AIが読めたかは記録されていません</span></p>`;
}


// 前回からの差。★数字は出すが、原因の断定は測定条件が一致するときだけ。
// いまの履歴は全部 legacy_unknown なので、必ず「原因は言えない」になる。それが正しい。

// 読めなかった項目の行き先は「区の公式サイト」しかない。
// AI読は答えの本文を持っていないので、ここを出さないと住民は手ぶらで終わる。
async function loadMuniTop() {
  if (muniTop) return muniTop;
  try {
    const d = await loadJson('data/municipalities.json');
    muniTop = new Map(d.municipalities.map((m) => [m.id, m]));
  } catch {
    muniTop = new Map();   // 出せないだけで、他は動かす
  }
  return muniTop;
}

// ★AIが選ばなかった扉。区に直してもらうのを待たなくても、
//   こちらが「本当の入口はこちらかもしれません」と出せる。
async function loadJourneys() {
  if (journeyOf) return journeyOf;
  try {
    const d = await loadJson('data/journeys.json');
    journeyOf = new Map(d.journeys.map((j) => [`${j.municipality_id}/${j.procedure_id}`, j]));
  } catch {
    journeyOf = new Map();
  }
  return journeyOf;
}

async function loadLookupCells() {
  if (lookupCells) return lookupCells;
  await Promise.all([loadMuniTop(), loadJourneys()]);
  const per = await Promise.all(procs.map(async (p) => {
    const d = await loadJson(`data/${p.file}`);
    return d.municipalities.map((m) => ({
      procId: p.id, procName: p.name, muniId: m.id, muniName: m.name,
      total: m.total, url: m.page_url, breakdown: m.breakdown, pageStatus: m.page_status,
      // 項目ごとに「どこに何を書くか」を出すために持つ
      improvements: m.improvements || [],
      notes: m.notes || '',
      generatedAt: (d.generated_at || '').slice(0, 10),
      fields: m.fields || [],
      lgCode: m.lg_code || null,
    }));
  }));
  lookupCells = per.flat();
  return lookupCells;
}

const gotCount = (c) => FIELDS.filter((k) => ((c.breakdown || {})[k] ?? 0) >= 20).length;

// 住民が次にやること。ここが無いと、画面に残るのは職員向けの助言だけになる。
// 電話番号は持っていないので作らない。案内先は区の公式サイトまで。
function nextStepForResident(c) {
  const top = muniTop && muniTop.get(c.muniId);
  const page = c.url
    ? `<li>区の<a class="dads-link" href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.procName)}のページ</a>を見る</li>`
    : '';
  if (gotCount(c) === FIELDS.length) {
    return `<div class="nextstep"><p class="nextstep__title">あなたが次にやること</p>
      <ol class="nextstep__list">${page}</ol></div>`;
  }
  // AIが同じ画面で見落としたリンク。区の修正を待たずに、ここで渡せる
  const j = journeyOf && journeyOf.get(`${c.muniId}/${c.procId}`);
  const near = j && j.blame === 'ours' && j.missed_with_strong_word[0];
  const shortcut = near
    ? `<li><b>AIが選ばなかったページを見る</b> —
        同じ画面に<a class="dads-link" href="${esc(near.url)}" target="_blank" rel="noopener">「${esc(near.link_text)}」</a>
        が出ていました。<b>こちらが本当の入口かもしれません</b></li>`
    : '';
  const ask = top
    ? `<li><b>書かれていない項目は、区に直接たしかめる</b> —
        <a class="dads-link" href="${esc(top.top_url)}" target="_blank" rel="noopener">${esc(top.name)}の公式サイト</a>の問い合わせ先へ。
        金額・期限・持ち物は、間違えると窓口で差し戻されます</li>`
    : '<li><b>書かれていない項目は、区に直接たしかめてください</b></li>';
  return `<div class="nextstep">
      <p class="nextstep__title">あなたが次にやること</p>
      <ol class="nextstep__list">
        ${shortcut}
        ${page}
        ${ask}
        <li>右下の<b>「AIに渡す」</b>で、自分のAIに持ち物リストを作らせる</li>
      </ol>
    </div>`;
}

// ── AIに渡す中身 ────────────────────────────────────────
// ★右下のボタンは「画面のDOMにあるもの」を渡す。だから画面から細かい判定を
//   外したぶんは、ここに（人には見せない形で）置く。
//   ただし全部は持たせない。長くなるとURLに載らず、クリップボード経由になって
//   **本人が手で貼らないと動かない**（実測 10,354字 → エンコード後 46,361）。
//   事実は最小限にして、詳細は AI読 のデータURLを渡し、AIに取りに行かせる。
const DATA_BASE = new URL('data/', location.href).href;
const SKILL_URL = new URL('skill/SKILL.md', location.href).href;

function payloadDoc(inner) {
  return `<h1>AI読の実測</h1>
    ${inner}
    <p>項目ごとの直し方と見込み点は、次のデータにあります。</p>
    <ul>
      <li>${esc(DATA_BASE)}index.json — 目次</li>
      <li>${esc(SKILL_URL)} — 使い方</li>
    </ul>`;
}

function renderAiPayload(res) {
  const box = $('ai-payload');
  if (!box) return;
  if (!res || res.kind !== 'ward' || !res.cells.length) {
    box.innerHTML = payloadDoc('<p>まだ区が選ばれていません。</p>');
    return;
  }
  const top = muniTop && muniTop.get(res.cells[0].muniId);
  const rows = res.cells.map((c) => {
    const miss = FIELDS.filter((k) => ((c.breakdown || {})[k] ?? 0) < 20);
    const got = FIELDS.filter((k) => ((c.breakdown || {})[k] ?? 0) >= 20);
    const jj = journeyOf && journeyOf.get(`${c.muniId}/${c.procId}`);
    const nr = jj && jj.blame === 'ours' && jj.missed_with_strong_word[0];
    return `<li>${esc(c.procName)}｜区の公式ページ ${esc(c.url || '不明')}
      ｜読み取れた: ${esc(got.join('・') || 'なし')}
      ｜読み取れなかった: ${esc(miss.join('・') || 'なし')}${nr
        ? `｜同じ画面に出ていた別の入口（未確認）: ${esc(nr.url)}` : ''}</li>`;
  }).join('');
  box.innerHTML = payloadDoc(`
    <p>対象: ${esc(res.muniName)}${top ? `（区の公式サイト ${esc(top.top_url)}）` : ''}</p>
    <ul>${rows}</ul>
    <p>「読み取れなかった」＝その項目が区のページに書かれていない。埋めないこと。</p>`);
}



// 読めなかった項目を1行で言う。✕の札4つと開閉パネル4つの代わり。
function missingLine(c) {
  const miss = FIELDS.filter((k) => ((c.breakdown || {})[k] ?? 0) < 20);
  if (!miss.length) return `4項目とも、このページから読み取れました。`;
  return `このページからは <b>${esc(miss.join('・'))}</b> が読み取れませんでした。`;
}

function lookupCellRow(c) {
  const st = c.pageStatus;
  const unconfirmed = st !== null && typeof st === 'object' && st.code === 'target_unconfirmed';

  return `<li class="lookup__cell">
    <details class="cell">
      <summary class="cell__head">
        <span class="lookup__proc">${esc(c.procName)}</span>
        <span class="cell__state" data-missing="${FIELDS.length - gotCount(c)}">${
            esc(AidokuLookup.cellChip(FIELDS.length - gotCount(c), FIELDS.length))}</span>
        <span class="cell__chev" aria-hidden="true">▾</span>
      </summary>
      <div class="cell__body">
        <p class="cell__miss">${missingLine(c)}</p>
        ${unconfirmed ? `<p class="lookup__warn">${esc(st.label)}</p>` : ''}
        ${nextStepForResident(c)}
        <p class="cell__more">
          <a class="dads-link" href="reference/journey.html?muni=${esc(c.muniId)}&proc=${esc(c.procId)}">AIがどう歩いたか</a>
        </p>
      </div>
    </details>
  </li>`;
}

// その区が住民のAIに届けられている項目の数。3手続き × 4項目 = 12 が満点
function wardProgress(cells) {
  const total = cells.length * FIELDS.length;
  const got = cells.reduce((a, c) => a + gotCount(c), 0);
  return { got, total, pct: total ? Math.round((got / total) * 100) : 0 };
}

function renderLookup(res) {
  const box = $('lookup-result');
  if (res.kind === 'page') {
    const c = res.cell;
    box.innerHTML = `
      <p class="lookup__title">このページは測ってあります — ${esc(c.muniName)}・${esc(c.procName)}</p>
      <ul class="lookup__list">${lookupCellRow(c)}</ul>
      <p class="lookup__src">読んだページ: ${esc(c.url)}</p>`;
    return;
  }
  if (res.kind === 'ward') {
    const via = res.matchedBy === 'url-host'
      ? `貼られたページそのものは測っていませんが、<strong>${esc(res.muniName)}</strong>は測ってあります。`
      : `<strong>${esc(res.muniName)}</strong>で測ってある手続きです。`;
    box.innerHTML = `
      <p class="lookup__title">${esc(res.muniName)}</p>
      <p class="lookup__sub">${via}</p>
      <!-- 推移は reference/trends.html に置く。ここに出すと、区を押した直後に
           「この差の原因は言えない」と日付が並んで、手続きを探す邪魔になる。 -->
      <p class="lookup__do">
        手続きを開くと、<strong>区の公式ページ</strong>と、読み取れなかった項目が出ます。
        <strong>右下の「AIに渡す」</strong>で、自分のAIが<strong>当日の持ち物</strong>を作ります。
      </p>
      <p class="lookup__miss">${esc(AidokuLookup.missingSummary(
        wardProgress(res.cells).total - wardProgress(res.cells).got,
        res.cells.length, FIELDS.length))}</p>
      <ul class="lookup__list">${res.cells.map(lookupCellRow).join('')}</ul>`;
    return;
  }
  if (res.reason === 'empty') {
    box.innerHTML = `<p class="lookup__sub">区名か、手続きページのURLを入れてください。</p>`;
    return;
  }
  box.innerHTML = `
    <div class="lookup__none">
      <p class="lookup__title">まだ測っていません</p>
      <p class="lookup__sub">
        調べてあるのは<strong>東京23区 × 3手続き（転入届・児童手当の申請・粗大ごみ収集の申込）の69件</strong>だけです。
        多摩26市や、ここに無い手続きは未測定です。<br>
        これは<strong>「AIに読めない」という意味ではありません。「まだ調べていない」</strong>です。
      </p>
      <p class="lookup__sub"><a href="board.html">調べた範囲を一覧で見る</a></p>
    </div>`;
}

// 画面の段階。ここを通らずに #results が見えることは無い。
//   empty  … 地図だけ
//   ward   … 押した区の3手続き（#results はまだ出さない）
//   detail … その区・その手続きの結果だけ（23区ぜんぶの話は出さない）
//   all    … 「23区ぶんの結果をまとめて見る」を押したとき
function setStage(stage) {
  const m = $('main');
  if (m) m.dataset.stage = stage;
}

// ★押したのに画面が動かないと、何も起きていないように見える。
//   地図は縦に大きく、結果は画面の外に出るので必ず送る。
//   キーボードで来た人のために、読み上げ位置も結果へ移す。
function goToResult() {
  const box = $('lookup-result');
  if (!box) return;
  const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  box.scrollIntoView({ behavior: still ? 'auto' : 'smooth', block: 'start' });
  box.setAttribute('tabindex', '-1');
  box.focus({ preventScroll: true });
}

async function runLookup(q) {
  $('lookup-result').innerHTML = '<p class="lookup__sub">探しています…</p>';
  try {
    const [cells] = await Promise.all([loadLookupCells(), loadArchive()]);
    const res = AidokuLookup.lookup(q, cells, procs.map((p) => p.id));
    renderLookup(res);
    renderAiPayload(res);
    // 当たったときだけ結果を出す。外したのに全部出てきたら、元の「最初から全部見える」に戻る
    if (res.kind === 'page' || res.kind === 'ward') {
      setStage('ward');
      goToResult();
    }
  } catch (err) {
    $('lookup-result').innerHTML =
      '<p class="lookup__sub">データを読めませんでした。時間をおいて試してください。</p>';
    console.error(err);
  }
}

// ── 23区の地図 ──────────────────────────────────────────────
// ★URLや区名を打たせない。押すのが一番速い。
//   地図ライブラリは足していない（SVGパスは analysis/export_map.py が用意済み）。
async function renderWardMap() {
  const box = $('wardmap');
  if (!box || typeof AidokuWardMap === 'undefined') return;
  let doc;
  try {
    const r = await fetch('data/tokyo23.json');
    if (!r.ok) throw new Error(String(r.status));
    doc = await r.json();
  } catch {
    box.remove();          // 地図が無くても、下の検索で使える
    return;
  }
  const cells = await loadLookupCells();
  const wards = AidokuWardMap.decorate(doc.wards, AidokuWardMap.wardProgress(cells, FIELDS));
  const paths = wards.map((w) => `
    <path d="${esc(w.d)}" data-name="${esc(w.name)}" data-tone="${esc(w.tone)}"
          tabindex="0" role="button" aria-label="${esc(w.label)}">
      <title>${esc(w.label)}</title>
    </path>`).join('');
  // 区名。押す対象は path なので、文字はクリックを透過させる（pointer-events: none）
  const labels = wards.filter((w) => w.lx != null).map((w) => `
    <text class="wardmap__name" x="${w.lx}" y="${w.ly}" data-tone="${esc(w.tone)}"
          text-anchor="middle" aria-hidden="true">${esc(w.short)}</text>`).join('');
  box.innerHTML = `
    <svg viewBox="${esc(doc.viewBox)}" class="wardmap__svg" role="group">${paths}${labels}</svg>
    <p class="wardmap__scale">${esc(AidokuWardMap.scaleLine(wards))}</p>
    <p class="wardmap__credit">境界: <a class="dads-link" href="${esc(doc.source_url)}">${esc(doc.source)}</a>（${esc(doc.license)}）</p>`;

  const pick = (el) => {
    if (!el || !el.dataset.name) return;
    box.querySelectorAll('path').forEach((p) => p.removeAttribute('aria-current'));
    el.setAttribute('aria-current', 'true');
    runLookup(el.dataset.name);
  };
  box.addEventListener('click', (e) => pick(e.target.closest('path')));
  box.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(e.target.closest('path')); }
  });
}


function initLookup() {
  if (typeof AidokuLookup === 'undefined') return;
  // 入力欄は廃止した（地図とプルダウンで選ぶ）。残っている場合だけつなぐ。
  const form = $('lookup-form');
  if (form) {
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      runLookup($('lookup-input').value);
    });
  }
  $('lookup-result').addEventListener('click', async (e) => {
    const b = e.target.closest('.lookup__open');
    if (!b) return;
    setStage('detail');
    await loadProcedure(b.dataset.proc, b.dataset.muni);
    $('detail-heading').scrollIntoView({ behavior: 'smooth', block: 'start' });
  });

  // 手続きを開いたとき、中身が画面の外に出ることがある。
  // 「あなたが次にやること」まで見えるように送る。
  $('lookup-result').addEventListener('toggle', (e) => {
    const cell = e.target.closest && e.target.closest('.cell');
    if (!cell || !cell.open) return;
    const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    cell.scrollIntoView({ behavior: still ? 'auto' : 'smooth', block: 'nearest' });
  }, true);

  renderAiPayload(null);
  renderWardMap();

  // 区名が分からない人の逃げ道。押したら全部出す（従来どおりの画面になる）
  const showAll = $('show-all');
  if (showAll) {
    showAll.addEventListener('click', () => {
      setStage('all');
      $('phase-note').scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }

  // ?q=世田谷区 で結果を直接開く。区が自分のリンクをブックマークできる。
  const q0 = new URLSearchParams(location.search).get('q');
  if (q0) {
    runLookup(q0);
  }
  // 盤面から ?muni=&proc= で来た人は、その区を見に来ているので最初から結果を出す
  if (new URLSearchParams(location.search).get('muni')) setStage('detail');
}
