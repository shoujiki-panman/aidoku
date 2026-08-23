// 調査データ一覧の言い方。DOMに触らない Pure Function だけを置く。
//
// ★「3回ぶんの記録がある」と「3回調べた」は違う。いまの履歴は、書き出しを
//   走らせた回を記録していて、345観測すべて値が同じ。ここで言い分けないと、
//   画面が勝手に「3回調べました」と言うことになる。
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

  return { jpDateTime, jpDate, headline, runSummary, conditionLabel, repeatNote, averageText };
});
