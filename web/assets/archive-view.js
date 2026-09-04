// 調査データ一覧の画面。組み立ては archive-list.js（純関数）に置き、ここはDOMだけ。
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const A = window.AidokuArchive;

  async function loadJson(path) {
    const r = await fetch(path);
    if (!r.ok) throw new Error(`${path}: ${r.status}`);
    return r.json();
  }

  function procRow(p) {
    return `<tr>
      <th scope="row">${esc(p.procedure)}</th>
      <td>${esc(String(p.municipalities))}自治体</td>
      <td>${esc(A.averageText(p))}</td>
      <td>${esc(String(p.full_marks ?? '-'))}</td>
      <td>${esc(String(p.zero ?? '-'))}</td>
    </tr>`;
  }

  function runCard(run, index) {
    const note = A.repeatNote(run);
    // 最初に開いておくのは、値が違う最新の回だけ。3回ぶん開くと読めない
    const open = !run.same_as_previous ? ' open' : '';
    return `<details class="survey"${open}>
      <summary class="survey__head">
        <span class="survey__date">${esc(A.exportedLabel(run))}</span>
        <span class="survey__sub">${esc(A.runSummary(run))}</span>
        <span class="survey__right">
          ${run.same_as_previous ? '<span class="survey__tag">前回と同じ値</span>' : ''}
          <span class="survey__chev" aria-hidden="true">▾</span>
        </span>
      </summary>
      <div class="survey__body">
        ${note ? `<p class="survey__note">${esc(note)}</p>` : ''}
        <p class="survey__meta">${esc(A.measuredLabel(run))}<br>
          記録した日: ${esc(run.recorded_on.map(A.jpDate).join('、'))}<br>
          ${esc(A.conditionLabel(run.recording_status))}</p>
        <table class="survey__table">
          <caption class="dads-u-visually-hidden">第${index + 1}回の調査結果</caption>
          <thead><tr><th scope="col">手続き</th><th scope="col">測った範囲</th>
            <th scope="col">平均点</th><th scope="col">満点の自治体</th>
            <th scope="col">0点の自治体</th></tr></thead>
          <tbody>${run.procedures.map(procRow).join('')}</tbody>
        </table>
      </div>
    </details>`;
  }

  function fileRow(f) {
    return `<li><a class="dads-link" href="${esc(f.path)}">${esc(f.label)}</a></li>`;
  }

  async function init() {
    try {
      const doc = await loadJson('data/surveys.json');
      $('runs-note').textContent = A.headline(doc);
      // 新しい回を上に出す
      const runs = doc.runs.slice().reverse();
      $('runs').innerHTML = runs.map((r, i) => runCard(r, doc.runs.length - 1 - i)).join('');
      $('files').innerHTML = doc.files.map(fileRow).join('');
      // フッタの見出しは「データ生成日」。出すのは書き出し日であって測定日ではない
      const last = doc.runs[doc.runs.length - 1];
      $('generated-at').textContent = last ? last.exported_on : '';
    } catch (err) {
      $('runs-note').textContent = '調査一覧を読み込めませんでした。';
      console.error(err);
    }
  }

  document.addEventListener('DOMContentLoaded', init);
})();
