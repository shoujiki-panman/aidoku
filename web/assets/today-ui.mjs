// 「今日直す1件」の画面配線。fix.html の入口（区を選ぶ、の上）に出す。
//
// fix.js がデータを組み終えた合図（aidoku:fix-cells）を受けて、見張りの結果と
// 確認済み情報の状態を取りに行き、優先度順の先頭1件と状態別の内訳を描く。
// 「この区を開く」で下の区選択に反映する。並べ方の中身は today.mjs（テスト対象）。
import { STATE, buildQueue, buildRemeasureIssueUrl, countByState } from './today.mjs';

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

function open(muniId) {
  const sel = document.getElementById('fix-ward');
  if (!sel) return;
  sel.value = muniId;
  sel.dispatchEvent(new Event('change'));
  sel.scrollIntoView({ block: 'start', behavior: 'smooth' });
}

function itemHtml(q, main) {
  const c = q.cell;
  const issueUrl = buildRemeasureIssueUrl(q);
  return `
    <p class="today__item${main ? ' today__item--main' : ''}">
      <span class="today__state" data-state="${esc(q.state)}">${esc(q.state)}</span>
      <b>${esc(c.muniName)}・${esc(c.procName)}</b>
      <span class="today__reason">${esc(q.reason)}</span>
      ${issueUrl ? `<a class="dads-button today__remeasure" href="${esc(issueUrl)}"
        target="_blank" rel="noopener">再測定を依頼</a>` : ''}
      <button type="button" class="dads-button today__open"${issueUrl ? ' data-variant="outline"' : ''}
        data-muni="${esc(c.muniId)}">この区を開く</button>
    </p>`;
}

async function render(cells) {
  const box = document.getElementById('fix-today');
  if (!box) return;

  const [status, verified] = await Promise.all([
    fetchJsonOrNull('data/site-status.json'),
    fetchJsonOrNull('data/verified-status.json'),
  ]);
  const queue = buildQueue({
    cells,
    statusItems: status?.items ?? [],
    verifiedRecords: verified?.records ?? [],
  });
  if (!queue.length) {
    box.innerHTML = '<p>いま直すべき課題は見つかっていません。</p>';
    return;
  }

  const counts = countByState(queue);
  const summary = Object.entries(counts).filter(([, n]) => n > 0)
    .map(([s, n]) => `${s} ${n}`).join('・');
  const rest = queue.slice(1, 8);
  const hasRemeasure = queue.some((q) => q.state === STATE.recheck);

  box.innerHTML = `
    ${itemHtml(queue[0], true)}
    <details class="today__rest">
      <summary>残りの課題（${queue.length - 1}件） — 全${queue.length}件の内訳: ${esc(summary)}</summary>
      ${rest.map((q) => itemHtml(q, false)).join('')}
      ${queue.length - 1 > rest.length ? `<p class="today__more">ほか ${queue.length - 1 - rest.length} 件は区を選んで確認してください。</p>` : ''}
    </details>
    ${hasRemeasure ? `<p class="today__note"><b>「再測定を依頼」について:</b>
      GitHubで依頼内容の下書きを開きます（アカウントが必要です）。内容を確認してIssueを送信してください。
      送信しても再測定は自動では始まりません。AI読側が確認して実行します。</p>` : ''}
    <p class="today__note">「要再確認」はページが変わったという意味で、悪化したとは限りません。
      「未確認」はこちらの調査がページに到達できたか確かめられていないもので、区が書いていないという意味ではありません。</p>`;

  box.querySelectorAll('.today__open').forEach((b) =>
    b.addEventListener('click', () => open(b.dataset.muni)));
}

function start(cells) {
  render(cells).catch(() => {
    const box = document.getElementById('fix-today');
    if (box) box.innerHTML = '<p>課題の一覧を読めませんでした。</p>';
  });
}

document.addEventListener('aidoku:fix-cells', (e) => start(e.detail.cells));
// このモジュールの読み込みより先にデータが揃っていた場合の拾い直し
if (window.__aidokuFixCells) start(window.__aidokuFixCells);
