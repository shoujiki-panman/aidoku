// 調査データ一覧の言い方。DOMに触らない Pure Function だけを置く。
//
// ★「3回ぶんの記録がある」と「3回調べた」は違う。いまの履歴は、書き出しを
//   走らせた回を記録していて、345観測すべて値が同じ。ここで言い分けないと、
//   画面が勝手に「3回調べました」と言うことになる。
//
// ★日付も同じ。surveys.json が持つ exported_at は書き出しを走らせた時刻で、
//   measured_at（実際に測った時刻）は記録が無ければ null。**null を exported_at で
//   埋めない。** 埋めた表示が「3回調べました」の正体だった。
//   → plans/decisions/resident-vs-data.md
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.AidokuArchive = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // 「20260817T125614」ではなく「2026年8月17日 12:56」
  function jpDateTime(iso) {
    const s = String(iso || '');
    const m = s.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
    if (!m) return '';
    return `${m[1]}年${Number(m[2])}月${Number(m[3])}日 ${m[4]}:${m[5]}`;
  }

  function jpDate(iso) {
    const m = String(iso || '').match(/^(\d{4})-(\d{2})-(\d{2})/);
    return m ? `${m[1]}年${Number(m[2])}月${Number(m[3])}日` : '';
  }

  // 何回の調査があって、そのうち値が違うのは何回か
  function headline(doc) {
    const n = Number((doc || {}).n_runs) || 0;
    const d = Number((doc || {}).n_distinct) || 0;
    if (!n) return '記録された調査がまだありません。';
    if (n === d) return `${n}回の調査を記録しています。`;
    return `${n}回ぶんの記録がありますが、値が前回と違ったのは${d}回です。`
         + '同じ値の回は、書き出しをやり直したものです。';
  }

  // その回が何だったか。1行で言う
  function runSummary(run) {
    const procs = (run && run.procedures) || [];
    if (!procs.length) return '';
    const munis = Math.max(...procs.map((p) => Number(p.municipalities) || 0));
    return `${procs.length}手続き × ${munis}自治体`;
  }

  // 条件が記録されているか。記録が無いなら、無いと書く
  function conditionLabel(status) {
    if (status === 'recorded') return '測定条件を記録しています';
    if (status === 'legacy_unknown') return '測定条件を記録していない回です（前後の比較はできません）';
    if (status === 'mixed') return '手続きによって条件の記録有無が違います';
    return '測定条件は不明です';
  }

  // 同じ値の回につける但し書き
  function repeatNote(run) {
    return run && run.same_as_previous
      ? '前の回と値が同じです。測り直した結果ではなく、書き出しをやり直したものです。'
      : '';
  }

  function averageText(proc) {
    const a = (proc || {}).average;
    return typeof a === 'number' ? `${a}点` : '記録なし';
  }

  // その回の見出しに出す日時。★出せるのは「書き出した時刻」であって測定時刻ではない。
  // 以前はこれを「◯月◯日に測定」と書いていた。書き出しを流し直しただけの回まで
  // 「その日に測った」ことになるので、言い方を実態に合わせる。
  function exportedLabel(run) {
    const t = jpDateTime((run || {}).exported_at);
    return t ? `${t} に書き出し` : '書き出し時刻の記録なし';
  }

  // 実際に測った日時。記録が無いなら「無い」と書く。書き出し時刻で代用しない
  function measuredLabel(run) {
    const t = jpDateTime((run || {}).measured_at);
    if (t) return `測った日時: ${t}`;
    return '測った日時: 記録なし（この回の日付は書き出しを走らせた時刻です）';
  }

  return {
    jpDateTime, jpDate, headline, runSummary, conditionLabel, repeatNote, averageText,
    exportedLabel, measuredLabel,
  };
});
