// 「今やる1件」の選定と依頼文の組み立て。DOMに触らない Pure Function だけを置く。
// ブラウザ（app.js）と node のテスト（web/test_next_action.mjs）の両方から読む。
//
// 選定規則は plans/feat-next-action.md で固定してある。ここで勝手に賢くしない。
//   1. gain 降順
//   2. 同点は factOrder（data/fact-types.json の定義順）
//   3. それでも同じなら field の文字列順
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.AidokuNextAction = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // improvements の1件が選定に使える形かどうか。壊れた行は落とす（例外にしない）。
  // gain が数値でない行は落とさず 0 扱いにする — 「候補から黙って消える」より
  // 「効果が読めない候補として最後に並ぶ」ほうが、データの穴に気づける。
  const isCandidate = (e) =>
    e !== null && typeof e === 'object' && !Array.isArray(e) &&
    typeof e.field === 'string' && e.field !== '';

  const gainOf = (e) =>
    typeof e.gain === 'number' && Number.isFinite(e.gain) ? e.gain : 0;

  function pickNextAction(improvements, factOrder) {
    if (!Array.isArray(improvements)) return null;
    const order = Array.isArray(factOrder) ? factOrder : [];
    // 定義順に無い項目名は既知の項目の後ろへ（データ側の項目追加で落ちないように）
    const rank = (field) => {
      const i = order.indexOf(field);
      return i === -1 ? order.length : i;
    };
    const sorted = improvements.filter(isCandidate).sort((a, b) =>
      gainOf(b) - gainOf(a) ||
      rank(a.field) - rank(b.field) ||
      (a.field < b.field ? -1 : a.field > b.field ? 1 : 0));
    return sorted.length ? sorted[0] : null;
  }

  // 担当部署へ渡せる短い依頼文。文はここで組み立てるが、事実（自治体名・項目・
  // 直し方・URL・点）はすべて呼び出し側が JSON から渡す。ここで数字を作らない。
  // 「必ず直る」とは書かない — 再測定していない提案は未検証のまま渡す。
  function buildRequestText(p) {
    if (!p || typeof p !== 'object') return '';
    const need = ['muniName', 'procedureName', 'field', 'reason', 'pageUrl'];
    for (const k of need) {
      if (typeof p[k] !== 'string' || p[k] === '') return '';
    }
    const gainLine =
      typeof p.gain === 'number' && Number.isFinite(p.gain) && p.gain > 0
        ? `この項目が読み取れるようになると、AI読の測定では +${p.gain}点の改善見込みです（実ページでの再測定はまだ行っていません）。\n`
        : '';
    return (
      `${p.muniName} ご担当者さま\n` +
      `\n` +
      `「${p.procedureName}」のページについて、記載追加のお願いです。\n` +
      `対象ページ: ${p.pageUrl}\n` +
      `\n` +
      `AIにこのページを読ませたところ、「${p.field}」が読み取れませんでした。\n` +
      `お願いしたい変更: ${p.reason}\n` +
      `\n` +
      gainLine +
      `これは個人による第三者調査「AI読（アイドク）」の実測にもとづく提案です。\n` +
      `測定方法と根拠: https://github.com/shoujiki-panman/aidoku\n`
    );
  }

  // 再確認（再測定）のコマンド。METHOD.md §5 の再現手順に ID を埋めるだけ。
  // 画面へ出す文字列なので、ID が想定外の形ならコマンドを出さない。
  const ID_RE = /^[a-z0-9_-]+$/;

  function buildRecheckCommand(muniId, procId) {
    if (typeof muniId !== 'string' || !ID_RE.test(muniId)) return '';
    if (typeof procId !== 'string' || !ID_RE.test(procId)) return '';
    return (
      `cd crawler   && python3 discover.py -m ${muniId} -p ${procId}\n` +
      `cd extractor && python3 extract.py  -m ${muniId} -p ${procId} --follow\n` +
      `python3 analysis/apply_evidence_check.py\n` +
      `cd analysis  && python3 export_dashboard.py -p ${procId} --out ../web/data/scores-${procId}.json`
    );
  }

  // 次の一手が「区への依頼」なのか「こちらの測り直し」なのかを決める（#86）。
  //
  // 4項目が1つも読めなかった区は、区のページに書かれていないのか、こちらが
  // 別のページを採点したのかを区別できない。区別できないものを区への依頼にしない。
  // 実データでは、4項目とも読めない18組のうち17組が、判定AI自身の観察記録で
  // 「別の手続きのページ」「索引ページ」と書かれていた。
  //
  // page_status を持たない古いデータは ward_request に倒さない。判定材料が無い以上、
  // 誤った依頼文を出すより、こちらで確かめる側へ倒す。
  function decideNextAction(muni, factOrder) {
    if (muni === null || typeof muni !== 'object' || Array.isArray(muni)) {
      return { kind: 'none', item: null };
    }
    const status = muni.page_status;
    const code = status !== null && typeof status === 'object' ? status.code : undefined;
    if (code !== 'facts_found') return { kind: 'remeasure', item: null };

    const item = pickNextAction(muni.improvements, factOrder);
    return item ? { kind: 'ward_request', item } : { kind: 'none', item: null };
  }

  return { pickNextAction, buildRequestText, buildRecheckCommand, decideNextAction };
});
