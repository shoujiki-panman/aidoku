// 担当者の「内容確認 → 公開 → AIが取得した結果」の画面配線。
//
// fix.js が区を描画したあと（aidoku:fix-rendered）、各手続きの .verify-slot に
// 確認フォームを差し込む。中身のロジックは verify-form.mjs（テスト対象）。
//
// 入力値はどこにも送信しない。ここで起きる通信は、公開済みデータ
// （既存の記録・実測の答え）の取得だけ。
import {
  checkEntry, mergeRecord, previewAsk, recordFileName, skeletonAnswer,
} from './verify-form.mjs';
import { urlKey } from '../../gatekeeper/verified_core.mjs';

const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

async function fetchJsonOrNull(path) {
  try {
    const r = await fetch(path);
    if (!r.ok) return null;
    return await r.json();
  } catch {
    return null;
  }
}

function formHtml(missing) {
  const rows = missing.map((f) => `
    <p class="verify__row">
      <label>${esc(f)}（区のページに書いてある実文）
        <input type="text" class="verify__value" data-field="${esc(f)}"></label>
      <label>条件（あれば。例: 窓口で届け出る場合）
        <input type="text" class="verify__cond" data-field="${esc(f)}"></label>
    </p>`).join('');
  return `
    <p class="verify__note">値を書けるのは担当者だけです（AI読は値を埋めません）。
      入力した値は<b>どこにも送信されません</b>。この場で、公開用の記録ファイルと
      「公開したらAIが取得する結果」の再現を作るだけです。</p>
    ${rows}
    <p class="verify__row"><label>確認者（部署名まで）
      <input type="text" class="verify__by" placeholder="例: 戸籍住民課"></label></p>
    <p><button type="button" class="dads-button verify__go">入力チェックして公開の準備</button></p>
    <div class="verify__out" aria-live="polite"></div>`;
}

function previewHtml(p) {
  const body = p.decided.body;
  const type = body?._meta?.response_type;
  if (type !== 'answer') {
    return `<li><b>${esc(p.question)}</b> → ${esc(type ?? '不明')}（公開後もこの項目は返りません）</li>`;
  }
  const v = body.results?.[0]?.verified_fields?.[p.field];
  return `<li><b>${esc(p.question)}</b> → answer:
    「${esc(v?.value ?? '')}」${v?.conditions ? `（条件: ${esc(v.conditions)}）` : ''}
    <span class="verify__prov">担当者確認済み・確認者 ${esc(v?.verified_by ?? '不明')}・第${esc(v?.version ?? '?')}版</span></li>`;
}

async function prepare(slot, out) {
  const cell = slot.dataset;
  const by = slot.querySelector('.verify__by').value;
  const entries = [...slot.querySelectorAll('.verify__value')]
    .filter((i) => i.value.trim())
    .map((i) => ({
      field: i.dataset.field,
      value: i.value,
      conditions: slot.querySelector(`.verify__cond[data-field="${CSS.escape(i.dataset.field)}"]`)?.value ?? '',
      verifiedBy: by,
    }));

  if (!entries.length) {
    out.innerHTML = '<p class="verify__ng">値がまだ入っていません。確認できた項目だけでかまいません。</p>';
    return;
  }
  const problems = entries.flatMap((e) => checkEntry(e).problems.map((p) => `${e.field}: ${p}`));
  if (problems.length) {
    out.innerHTML = `<p class="verify__ng">入力チェック: ${esc(problems.join(' / '))}</p>`;
    return;
  }

  const existing = await fetchJsonOrNull(`../gatekeeper/verified/${cell.muniId}-${cell.procId}.json`);
  const record = mergeRecord({
    existing,
    cell: { muniId: cell.muniId, muniName: cell.muniName, procId: cell.procId, procName: cell.procName, url: cell.url },
    entries,
    now: new Date(),
  });

  // 実測の答え（門番がKVに持つ形）。この手続きの分がまだ無ければ全null の骨組み
  const measuredFile = await fetchJsonOrNull(`../gatekeeper/answers/${cell.muniId}.json`);
  const measured = measuredFile && urlKey(measuredFile.source) === urlKey(cell.url)
    ? measuredFile
    : skeletonAnswer({ procName: cell.procName, muniName: cell.muniName, url: cell.url, generatedAt: cell.generated || null });

  const previews = entries.map((e) => previewAsk({ measured, record, field: e.field }));
  const json = `${JSON.stringify(record, null, 2)}\n`;
  const name = recordFileName(record);

  out.innerHTML = `
    <p class="verify__ok">入力チェック: ${entries.length} 項目の記入を確認しました。</p>
    <h4 class="dads-heading" data-size="xs">公開したらAIが取得する結果（この画面での再現）</h4>
    <ul class="verify__preview">${previews.map(previewHtml).join('')}</ul>
    <p class="verify__prov">実測（fields）はそのまま残り、確認済みは別の束（verified_fields）で返ります。
      実際の配信は、下のファイルを置いて反映してから始まります。</p>
    <h4 class="dads-heading" data-size="xs">公開のしかた</h4>
    <ol class="verify__steps">
      <li>このファイルを <code>gatekeeper/verified/${esc(name)}</code> としてリポジトリに置く（Pull Request）</li>
      <li><code>node gatekeeper/verified_sync.mjs</code> を実行（見張りとの突き合わせと answers/ への反映）</li>
      <li><code>gatekeeper/put_answers.sh</code> でKVへ。ここでAIの案内が変わります</li>
    </ol>
    <p class="verify__acts">
      <button type="button" class="dads-button verify__dl">記録ファイルを保存（${esc(name)}）</button>
      <button type="button" class="dads-button verify__copy">中身をコピー</button>
    </p>
    <pre class="verify__json"><code>${esc(json)}</code></pre>`;

  out.querySelector('.verify__dl').addEventListener('click', () => {
    const blob = new Blob([json], { type: 'application/json;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  });
  out.querySelector('.verify__copy').addEventListener('click', () => navigator.clipboard?.writeText(json));
}

function build(slot) {
  const missing = (slot.dataset.missing || '').split(',').filter(Boolean);
  if (!missing.length) return;
  slot.innerHTML = `
    <details class="verify">
      <summary>担当者として値を確認し、AIへ公開する</summary>
      ${formHtml(missing)}
    </details>`;
  const out = slot.querySelector('.verify__out');
  slot.querySelector('.verify__go').addEventListener('click', () => {
    prepare(slot, out).catch(() => {
      out.innerHTML = '<p class="verify__ng">データを読めませんでした。時間をおいてやり直してください。</p>';
    });
  });
}

function buildAll() {
  document.querySelectorAll('.verify-slot:not([data-built])').forEach((slot) => {
    slot.dataset.built = '1';
    build(slot);
  });
}

document.addEventListener('aidoku:fix-rendered', buildAll);
buildAll(); // このモジュールの読み込みより先に描画が済んでいた場合の拾い直し
