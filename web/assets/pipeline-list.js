// 「この数字はどう作られたか」の言い方。DOMに触らない Pure Function だけを置く。
//
// ★数字はここで作らない。pipeline.json（実ファイルを数えた値）をそのまま言葉にする。
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.AidokuPipeline = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);

  function totalLines(layers) {
    return (layers || []).reduce((a, l) => a + (num(l.lines) || 0), 0);
  }

  // 画面に出ているのは全体の何割か。「ただのサイト」に見える理由そのもの
  function screenShare(layers) {
    const total = totalLines(layers);
    const screen = (layers || []).find((l) => l.dir === 'web/assets');
    if (!total || !screen || !num(screen.lines)) return null;
    return Math.round((screen.lines / total) * 100);
  }

  function headline(layers) {
    const total = totalLines(layers);
    const share = screenShare(layers);
    if (!total) return '';
    if (share === null) return `全体で${total.toLocaleString('en-US')}行あります。`;
    return `全体で${total.toLocaleString('en-US')}行。`
         + `そのうち画面は${share}%で、残りは測るための仕組みです。`;
  }

  // 対照実験の結論。回数から言う。数を書き換えない
  function experimentLine(exp) {
    if (!exp || !Array.isArray(exp.variants)) return '';
    const by = {};
    exp.variants.forEach((v) => { by[v.key] = num(v.all_four); });
    const n = num(exp.trials);
    if (by.before === null || by.after === null || !n) return '';
    return `同じページの写しで、書き足す前は${n}回中${by.before}回、`
         + `書き足したあとは${n}回中${by.after}回、4項目そろいました。`;
  }

  // 反実仮想。ここが「読んでいる」の根拠。
  // ★回数は barriers.json の実数（returned_modified / returned_original）から取る。
  //   4項目そろった回数から「書き換えた値を返した」を推測しない。
  function counterfactualLine(cf) {
    if (!cf) return '';
    const mod = num(cf.returned_modified);
    const orig = num(cf.returned_original);
    if (mod === null || orig === null) return '';
    const total = mod + orig;
    return `${cf.changed || '期限'}に書き換えた写しで測ると、${total}回のうち${mod}回が`
         + `書き換えた側の値を返しました（元の値を返したのは${orig}回）。`
         + 'AIは知識ではなく、そのページを読んでいます。';
  }

  // 較正の穴。あるものだけでなく、無いものを言う
  function calibrationLine(cal) {
    const by = (cal || {}).by_procedure || {};
    const has = Object.keys(by).filter((k) => num(by[k].rows));
    const missing = (cal || {}).missing || [];
    if (!has.length) return '正解データはまだありません。';
    const first = by[has[0]];
    const head = `正解データは${has.length}手続きぶんだけです`
               + `（${first.municipalities}自治体・${first.rows}行）。`;
    return missing.length
      ? head + `残り${missing.length}手続きには正解データがなく、`
             + '点が動いても「サイトが変わった」と「判定器が変わった」を区別できません。'
      : head;
  }

  function conditionLine(keys) {
    const n = (keys || []).length;
    if (!n) return '';
    return `測定条件は${n}項目。1つでも違うと署名が変わり、前後の比較を拒否します。`;
  }

  return { totalLines, screenShare, headline, experimentLine,
           counterfactualLine, calibrationLine, conditionLine };
});
