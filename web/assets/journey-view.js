// 道のりマップの描画。組み立ては journey.js（Pure）が済ませている。
// ここは DOM に置くだけで、数字を作らない。
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  const ICON = { start: '▶', stop: '✖', unreached: '·', goal: '★' };
  const KIND_LABEL = {
    start: 'スタート', stop: 'ここで力尽きた', unreached: '辿り着けなかった', goal: 'ゴール',
  };

  async function loadJson(p) {
    const r = await fetch(p);
    if (!r.ok) throw new Error(`${r.status}: ${p}`);
    return r.json();
  }

  const shortUrl = (u) => {
    if (!u) return '';
    try {
      const x = new URL(u);
      return x.pathname === '/' ? x.host : x.pathname;
    } catch { return u; }
  };

  // AIがその場で見ていた選択肢と、点の内訳。★歩く様子ではなく「判断」を見せる。
  function choicesPanel(j) {
    if (!j || !j.choices || !j.choices.length) return '';
    const rows = j.choices.map((c) => {
      const bits = (c.reasons || []).map((r) =>
        `<span class="rz" data-kind="${esc(r.kind)}">${esc(r.why)} <b>${r.points > 0 ? '+' : ''}${r.points}</b></span>`).join('');
      return `<li class="choice" data-chosen="${c.chosen}">
        <div class="choice__head">
          <span class="choice__rank">${c.rank}位</span>
          <span class="choice__score">${c.score}点</span>
          <span class="choice__text">「${esc(c.link_text)}」</span>
          ${c.chosen ? '<span class="choice__tag">これを選んだ</span>' : ''}
        </div>
        <div class="choice__why">${bits || '<span class="rz">手がかりなし</span>'}</div>
      </li>`;
    }).join('');
    const missed = (j.missed_with_strong_word || [])[0];
    return `<div class="choices" id="choices" hidden>
        <p class="choices__lead">AIはトップページで<strong>${j.choices.length}つの入口</strong>を見て、
          文言とURLから点を付けて並べました。</p>
        <p class="choices__rule">${esc(window.__JOURNEY_SCORING__ || '')}</p>
        <ol class="choices__list">${rows}</ol>
        ${missed ? `<p class="choices__missed">
          <strong>「${esc(missed.link_text)}」</strong>は手続き名そのもの（strong語）で <b>+10</b> を取っていましたが、
          URLの手がかりを積んだ1位に <b>${j.choices[0].score - missed.score}点差</b> で負けました。
          <strong>AIは正しい扉の隣を選びました。</strong></p>` : ''}
      </div>`;
  }

  function stageNode(s, i) {
    const url = s.url
      ? `<a class="stage__url" href="${esc(s.url)}" target="_blank" rel="noopener">${esc(shortUrl(s.url))}</a>`
      : '';
    const fields = (s.fields || []).length
      ? `<div class="stage__items">${s.fields.map((f) =>
          `<span class="stage__item" data-ok="${f.ok}">${f.ok ? '✓' : '✕'} ${esc(f.name)}</span>`).join('')}</div>`
      : '';
    const score = s.score ? `<span class="stage__score">${esc(s.score)}</span>` : '';
    const why = s.why ? `<div class="why">
        <p class="why__title">どうやって力尽きたか</p>
        <ol class="why__steps">${s.why.steps.map((w) =>
          `<li data-whose="${w.whose}"><b>${esc(w.whose === 'ours' ? 'こちらの都合' : '区のページ')}</b>${esc(w.text)}</li>`).join('')}</ol>
        ${s.why.notes ? `<p class="why__notes"><b>判定AIの観察記録</b>${esc(s.why.notes)}</p>` : ''}
      </div>` : '';
    return `<li class="stage__node" data-kind="${s.kind}">
      <div class="stage__badge" aria-hidden="true">${ICON[s.kind] || '·'}</div>
      <div class="stage__body">
        <p class="stage__kind">${esc(KIND_LABEL[s.kind] || '')}${score}</p>
        <p class="stage__label">${esc(s.label || '')}</p>
        ${url}
        ${fields}
        ${s.kind === 'start' ? `
          <button type="button" class="dads-button choices__btn" data-variant="solid"
                  id="show-choices" aria-expanded="false" aria-controls="choices">
            ▶ AIが何を見て、どう選んだか
          </button>
          ${choicesPanel(window.__JOURNEY__)}` : ''}
        ${why}
      </div>
    </li>`;
  }

  function connector(s) {
    // 通れた道は実線、通れなかった道は点線。文言はリンクの看板。
    const dashed = s.kind === 'unreached' || s.kind === 'goal';
    const trap = s.trap
      ? `<p class="stage__trap"><b>罠</b>：ひとつ前の看板と<strong>一字違い</strong>
           — 「${esc(s.trap.prev)}」 と 「${esc(s.trap.now)}」</p>`
      : '';
    return `<li class="stage__link" data-dashed="${dashed}">
      <span class="stage__arrow" aria-hidden="true"></span>
      ${s.via ? `<span class="stage__via">「${esc(s.via)}」を押す</span>` : ''}
      ${trap}
    </li>`;
  }

  function renderExplorer(ex, note) {
    return `<div class="explorer" data-family="${esc(ex.family)}">
      <span class="explorer__mark" aria-hidden="true">${esc(ex.mark)}</span>
      <span class="explorer__body">
        <b>この道を歩いたAI</b>
        <span class="explorer__model">${esc(ex.model || '記録なし')}</span>
        <span class="explorer__vendor">${esc(ex.vendor)}</span>
      </span>
      <span class="explorer__note">${esc(note)}</span>
    </div>`;
  }

  // ── 再生 ──────────────────────────────────────────────
  // 動きを見せないと、AIに慣れていない人には伝わらない。
  // ただし動きが唯一の手段にはしない: 再生し終わった状態＝いつもの静止画で、
  // prefers-reduced-motion のときは最初から最後の状態にする。
  let timers = [];
  const clearTimers = () => { timers.forEach(clearTimeout); timers = []; };
  const prefersStill = () =>
    window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function setStep(el, on) {
    if (el) el.dataset.played = String(on);
  }

  function resetPlayback(root, on) {
    // on=false: 再生前（全部伏せる） / on=true: 再生後（全部出す）
    root.querySelectorAll('.stage__node, .stage__link').forEach((el) => setStep(el, on));
    root.querySelectorAll('.stage__item').forEach((el) => setStep(el, on));
    const tok = $('token');
    if (tok) tok.dataset.at = on ? 'end' : '0';
  }

  function playTimeline(tl, root) {
    clearTimers();
    resetPlayback(root, false);
    const nodes = [...root.querySelectorAll('.stage__node')];
    const links = [...root.querySelectorAll('.stage__link')];
    const items = [...root.querySelectorAll('.stage__item')];
    const tok = $('token');

    for (const beat of tl) {
      timers.push(setTimeout(() => {
        if (beat.type === 'enter') {
          setStep(nodes[beat.index], true);
          if (tok && nodes[beat.index]) {
            // 歩いている印を、着いたマスの高さへ動かす
            tok.style.transform = `translateY(${nodes[beat.index].offsetTop}px)`;
          }
        } else if (beat.type === 'sign' || beat.type === 'walk') {
          setStep(links[Math.max(beat.index - 1, 0)], true);
        } else if (beat.type === 'read') {
          setStep(items[beat.order], true);
        } else if (beat.type === 'exhausted') {
          root.dataset.state = 'exhausted';
        } else if (beat.type === 'blocked') {
          root.dataset.state = 'blocked';
        } else if (beat.type === 'reveal-goal') {
          links.forEach((l) => setStep(l, true));
          nodes.forEach((nd) => setStep(nd, true));
          items.forEach((it) => setStep(it, true));
          root.dataset.state = 'goal';
        } else if (beat.type === 'end') {
          root.dataset.state = 'end';
        }
      }, beat.at));
    }
  }

  function renderMap(stages, barrier, ex) {
    const html = [];
    stages.forEach((s, i) => {
      if (i > 0) html.push(connector(s));
      html.push(stageNode(s, i));
    });
    $('map').innerHTML = renderExplorer(ex,
      '各社の公式ロゴは使っていません（自前の記号です）。モデル名は測定条件の実測値です。')
      + `<div class="stage__wrap">
           <span class="stage__token" id="token" aria-hidden="true">${esc(ex.mark)}</span>
           <ol class="stage__list">${html.join('')}</ol>
         </div>`;

    const clicks = barrier?.failure?.clicks_to_official_page;
    $('map-note').innerHTML =
      `<strong>${esc(barrier.municipality)}・${esc(barrier.procedure)}</strong>。` +
      (clicks ? `答えのあるページまで<strong>${clicks}クリック</strong>。` : '') +
      `AIが採点したのは、その手前の目次ページでした。`;
  }

  function renderProof(barrier) {
    const c = barrier?.counterfactual;
    if (!c) { $('proof').innerHTML = ''; return; }
    $('proof').innerHTML = `
      <div class="proof">
        <p class="proof__what">${esc(c.changed || '')}</p>
        <div class="proof__cols">
          <div class="proof__col"><b>${c.returned_original_14 ?? '-'}</b><span>元の値を返した回</span></div>
          <div class="proof__col" data-hit="true"><b>${c.returned_modified_37 ?? '-'}</b><span>書き換えた値を返した回</span></div>
        </div>
        <p class="proof__conc">${esc(c.conclusion || '')}</p>
        <p class="proof__note">${esc(c.purpose || '')}</p>
      </div>`;
  }

  function renderSame(barrier) {
    const p = barrier?.prevalence;
    if (!p) { $('same').innerHTML = ''; return; }
    const cells = (p.cells || []).map((c) =>
      `<li><b>${esc(c.municipality)}</b>・${esc(c.procedure)}
         <span class="same__hops">${esc(String(c.hops))}クリック目で止まった</span></li>`).join('');
    $('same').innerHTML = `
      <p class="section-note">同じ段差（目次で止まる）が見つかったマス:
        <strong>${esc(String(p.same_barrier_cells))} / ${esc(String(p.total_cells))}</strong>
        （0点だった${esc(String(p.zero_score_cells))}マスのうち ${esc(p.share_of_zeros)}）</p>
      <ul class="same__list">${cells}</ul>
      <p class="section-note">${esc(p.caveat || '')}</p>`;
  }

  async function init() {
    try {
      const [bs, sc, ft, jj] = await Promise.all([
        loadJson('data/barriers.json'),
        loadJson('data/scores-tennyu.json'),
        loadJson('data/fact-types.json'),
        loadJson('data/journeys.json').catch(() => ({ journeys: [] })),
      ]);
      // 描くときに読むので、先に置く
      window.__JOURNEY__ = (jj.journeys || [])[0] || null;
      window.__JOURNEY_SCORING__ = jj.scoring || '';
      const barrier = (bs.barriers || [])[0];
      if (!barrier) { $('map').innerHTML = '<p>記録がありません。</p>'; return; }

      const names = ft.fact_types.map((f) => f.display_label);
      const muni = (sc.municipalities || []).find((m) => m.name === barrier.municipality);
      const cell = muni ? {
        got: names.filter((n) => (muni.breakdown[n] ?? 0) >= 20).length,
        total: names.length,
        fields: names.map((n) => ({ name: n, ok: (muni.breakdown[n] ?? 0) >= 20 })),
      } : null;

      const run = (sc.measurement?.runs || [])
        .find((r) => r.municipality_id === (muni && muni.id));
      const ex = AidokuJourney.explorer(
        run?.model_version || barrier.measurement?.model, run?.model);

      const stages = AidokuJourney.buildStages(barrier, cell);
      // 「力尽きた」の中身。どこがこちらの都合かを分けて書く（区のせいだけに見せない）
      const stop = stages.find((s) => s.kind === 'stop');
      if (stop) {
        stop.why = {
          notes: muni?.notes || '',
          steps: [
            { whose: 'ours', text: '：探索が候補を集め、この目次ページを1位に選んだ' },
            { whose: 'ours', text: `：採点のとき、本文とリンク一覧（上限40件）だけをAIに渡した` },
            { whose: 'site', text: '：本文に4項目が無く、目次に関連ページ名の文字だけが見えた' },
            { whose: 'ours', text: '：そのURLが渡した40件に入っておらず（地域ナビで埋まっていた）、AIは追えなかった' },
          ],
        };
      }
      renderMap(stages, barrier, ex);

      const root = $('map').querySelector('.stage__wrap');
      const tl = AidokuJourney.buildTimeline(stages, cell ? cell.fields : []);
      resetPlayback(root, true);
      root.dataset.state = 'end';

      // ★ボタンはスタートのマスの中。前は上に離して置いていて気付けなかった。
      //   押すと「何を見て、どう選んだか」が開き、続けて道のりを再生する。
      const btn = $('show-choices');
      const panel = $('choices');
      if (btn) {
        btn.addEventListener('click', () => {
          const open = btn.getAttribute('aria-expanded') === 'true';
          btn.setAttribute('aria-expanded', String(!open));
          if (panel) panel.hidden = open;
          btn.textContent = open ? '▶ AIが何を見て、どう選んだか' : '▼ 判断を閉じる';
          if (!open && !prefersStill()) {
            root.dataset.state = 'playing';
            playTimeline(tl, root);
          }
        });
      }
      renderProof(barrier);
      renderSame(barrier);
      const g = $('generated-at');
      if (g) g.textContent = (bs.generated_at || '').slice(0, 10);
    } catch (e) {
      $('map').innerHTML = '<p>データを読めませんでした。</p>';
      console.error(e);
    }
  }
  init();
})();
