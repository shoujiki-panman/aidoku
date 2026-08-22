// data/barriers.json をそのまま縦1本の流れに描く。
// 主役は点数ではなく「何が起きて、何を変えたら、どうなったか」。
// 数字はすべて実測値。ここで文章を作らない（作ると測っていないことを書いてしまう）。

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// 項目名は data/fact-types.json が唯一の出どころ。ここに直書きしない。
// **この画面だけ extractor_key を使う**（barriers.json の per_field と
// ground_truth のキーが extractor 側の表記のため）。display_label ではない。
let FIELDS = [];

async function init() {
  const ftRes = await fetch('data/fact-types.json');
  if (!ftRes.ok) throw new Error(`fact-types.json を読めませんでした (${ftRes.status})`);
  FIELDS = (await ftRes.json()).fact_types.map((f) => f.extractor_key);

  const res = await fetch('data/barriers.json');
  if (!res.ok) throw new Error(`データを読めませんでした (${res.status})`);
  const doc = await res.json();
  const b = doc.barriers[0];

  $('generated-at').textContent = (doc.generated_at || '').slice(0, 10);
  $('banner-head').textContent =
    `${b.municipality}の${b.procedure} — 直したら 5回中5回 取れるようになりました`;
  $('banner-body').textContent = b.note;

  renderFlow(b, doc);
  renderHonest(b);
  renderData(b, doc);
}

// 4項目の○×を横に並べる小さい表示。before/after で同じ形にして見比べられるようにする
function fieldMarks(perField) {
  return FIELDS.map((f) => {
    const n = perField[f] ?? 0;
    return `<span class="mk" data-ok="${n > 0}"><b>${esc(f)}</b><i>${n}/5</i></span>`;
  }).join('');
}

function step({ n, kind, title, body }) {
  return `<li class="step" data-kind="${kind}">
    <div class="step__no">${n}</div>
    <div class="step__body">
      <h2 class="step__title">${title}</h2>
      ${body}
    </div>
  </li>`;
}

function renderFlow(b, doc) {
  const gt = b.evidence.ground_truth;
  const cf = b.counterfactual;
  const pv = b.prevalence;

  const steps = [
    step({
      n: 1, kind: 'ask', title: '住民がAIに聞く',
      body: `<p class="q">「${esc(b.municipality)}に引っ越します。${esc(b.procedure)}に必要なもの・期限・手数料を教えて。オンラインでできますか？」</p>`,
    }),
    step({
      n: 2, kind: 'ng', title: 'いまのページ — AIは答えられない',
      body: `<p class="big"><b>0</b><span>/5回しか4項目そろわない</span></p>
        <div class="marks">${fieldMarks(b.measurement.before.per_field)}</div>
        <p class="src">読んだページ: <a class="dads-link" href="${esc(b.failure.observed_at_url)}" target="_blank" rel="noopener">${esc(b.failure.observed_at_url)}</a></p>`,
    }),
    step({
      n: 3, kind: 'why', title: 'なぜ答えられないのか',
      body: `<p>${esc(b.failure.summary)}</p>
        <p class="tag">Failure Type: <code>${esc(b.failure.type)}</code></p>`,
    }),
    step({
      n: 4, kind: 'ok', title: '公式ページには、ちゃんと書いてある',
      body: `<p class="lead-note"><strong>情報が無いのではありません。</strong>本体ページは4項目すべてを専用の見出しで持っています。
          ただし<strong>${esc(b.failure.clicks_to_official_page)}クリック先</strong>です。</p>
        <dl class="gt">${FIELDS.map((f) => `<dt>${esc(f)}</dt><dd>${
          gt[f] ? esc(gt[f]) : '<span class="withheld">記載あり（本文は出典ページでご覧ください）</span>'
        }</dd>`).join('')}</dl>
        ${b.evidence.ground_truth_withheld
          ? `<p class="src">${esc(b.evidence.ground_truth_note || '')}</p>` : ''}
        <p class="src">出典: <a class="dads-link" href="${esc(b.evidence.official_page)}" target="_blank" rel="noopener">${esc(b.evidence.official_page)}</a>
          ／ ページ最終更新 ${esc(b.evidence.official_page_last_updated)}
          ／ 確認 ${esc((b.evidence.confirmed_at || '').slice(0, 10))}</p>`,
    }),
    step({
      n: 5, kind: 'fix', title: '直してみる',
      body: `<p>${esc(b.intervention_tested.what)}</p>`,
    }),
    step({
      n: 6, kind: 'ok', title: '直した版 — AIは答えられる',
      body: `<p class="big"><b>5</b><span>/5回とも4項目そろった</span></p>
        <div class="marks">${fieldMarks(b.measurement.after.per_field)}</div>
        <p class="src">${esc(b.measurement.trials_per_condition)}回ずつ測定 ／ モデル ${esc(b.measurement.model)}</p>`,
    }),
    step({
      n: 7, kind: 'proof', title: 'AIは本当にページを読んだのか',
      body: `<p class="lead-note">AIが正しく答えても、<strong>ページを読んだのか、もともと知っていたのか</strong>は分かりません。そこで確かめました。</p>
        <p>${esc(cf.changed)}</p>
        <p class="cf">
          <span class="cf__row"><b>「14日」を返した回</b><i data-zero="true">${cf.returned_original_14} / 5</i></span>
          <span class="cf__row"><b>「37日」を返した回</b><i>${cf.returned_modified_37} / 5</i></span>
        </p>
        <p class="lead-note">転入届の14日は法律で決まっていて、AIは学習で知っている値です。
          <strong>それでも5回とも、ありえない37日を返しました。</strong>${esc(cf.conclusion)}。</p>`,
    }),
    step({
      n: 8, kind: 'many', title: '同じ段差は、ほかにもあった',
      body: `<p class="big"><b>${pv.same_barrier_cells}</b><span>件。0点${pv.zero_score_cells}件のうち${esc(pv.share_of_zeros)}</span></p>
        <p class="lead-note">採点したページに<strong>手続きの名前が1度も出てこない</strong>ものを、既存の記録から数えました（新しく取りに行っていません）。</p>
        <ul class="cells">${pv.cells.map((c) =>
          `<li><b>${esc(c.municipality)}</b> ${esc(c.procedure)} <span>トップから${esc(c.hops)}クリック</span></li>`).join('')}</ul>`,
    }),
    step({
      n: 9, kind: 'open', title: '記録を公開する',
      body: `<p>ここまでの<strong>失敗・証拠・改善効果・再現方法</strong>をまとめて公開しています。
          点数だけでは、誰も直せません。</p>
        <p class="src"><a class="dads-link" href="data/barriers.json">barriers.json</a> ／
          再現: <code>${esc(b.measurement.reproduce)}</code></p>`,
    }),
  ];
  $('flow').innerHTML = steps.join('');
}

function renderHonest(b) {
  const items = [
    `<strong>${esc(b.municipality)}のサイトは1文字も変えていません。</strong>直したのは手元の複製です。`,
    `<strong>「目次に4項目を書く」が正しい直し方だとは言えません。</strong>${esc(b.intervention_tested.caveat)}`,
    `<strong>まだ誰も直していません。</strong>区への連絡も、実サイトでの改善も、その後の測定もしていません。`,
    `<strong>第三者が見ていません。</strong>確認したのは作った本人だけです。`,
    `反実仮想で確かめたのは<strong>「期限」1項目だけ</strong>です。他3項目は未検証です。`,
    `1自治体・1手続き・1モデル・1日の結果です。<strong>他に当てはめられる量ではありません。</strong>`,
    esc(b.prevalence.caveat),
  ];
  $('honest').innerHTML = items.map((t) => `<li>${t}</li>`).join('');
}

function renderData(b, doc) {
  $('datalist').innerHTML = [
    ['data/barriers.json', 'この画面が読んでいるデータ（失敗・証拠・改善効果・再現方法）'],
    [b.measurement.raw, '測定の生データ（5回ぶんの回答すべて）'],
    ['data/README.md', '列の意味・取りうる値・欠損の扱い'],
  ].map(([href, note]) =>
    `<li><a class="dads-link" href="${esc(href)}">${esc(href.split('/').pop())}</a> — ${esc(note)}</li>`).join('');

  const lic = doc.license || {};
  $('license-note').innerHTML =
    `ライセンス: <strong>${esc(lic.name)}</strong>（<a class="dads-link" href="${esc(lic.url)}" target="_blank" rel="noopener">${esc(lic.url)}</a>）。
     クレジットは <code>${esc(lic.attribution)}</code>。<br>
     ただし<strong>公式ページから引用した文は各自治体の著作物です。</strong>${esc(lic.not_covered)}`;
}

init().catch((e) => {
  $('flow').innerHTML = `<li class="err">${esc(e.message)}<br><code>data/barriers.json</code> があるか確認してください。</li>`;
});
