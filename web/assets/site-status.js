// サイトの見張り状態を画面に出す。
//
// 出すのは「いつ確認したか」と「変わったか」だけ。点数の話はしない。
// 普段は静かに1行で、知らせることがあるときだけ大きくする（Mulmo Control と同じ考え方）。
//
// データは crawler/check_pages.py が書く web/data/site-status.json。
// 無い場合は「まだ確認していない」と出す。数字を作らない。
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.AidokuSiteStatus = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // 画面に出す形を決める Pure Function。DOMには触らない。
  // level: 'gone'（消えた）> 'changed'（変わった）> 'unknown'（判定できず）> 'ok'
  function describe(report) {
    if (!report || typeof report !== 'object' || !Array.isArray(report.items)) {
      return {
        level: 'none',
        headline: 'サイトの確認はまだ行っていません',
        detail: '確認すると、採点したページが前回から変わったかがここに出ます。',
        checkedAt: null,
        items: [],
      };
    }
    const s = report.summary && typeof report.summary === 'object' ? report.summary : {};
    const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : 0);
    const gone = report.items.filter((i) => i && i.gone === true);
    const edited = report.items.filter((i) => i && i.changed === true && !i.gone);
    const unknown = report.items.filter((i) => i && i.changed === null);

    if (gone.length) {
      return {
        level: 'gone',
        headline: `${gone.length}ページが無くなりました`,
        detail: '採点したページが返らなくなりました。公開している点数の根拠URLが切れています。',
        checkedAt: report.checked_at || null,
        items: gone.concat(edited),
      };
    }
    if (edited.length) {
      return {
        level: 'changed',
        headline: `${edited.length}ページが変わりました`,
        detail: '測り直しが必要という意味です。悪くなったという意味ではありません。',
        checkedAt: report.checked_at || null,
        items: edited,
      };
    }
    if (unknown.length) {
      return {
        level: 'unknown',
        headline: `${num(s.unchanged)}ページは変わっていません（${unknown.length}ページは判定できず）`,
        detail: '前回の記録が無い、通信に失敗した、などの理由で確かめられなかったページがあります。',
        checkedAt: report.checked_at || null,
        items: unknown,
      };
    }
    return {
      level: 'ok',
      headline: `${num(s.unchanged)}ページとも変わっていません`,
      detail: '',
      checkedAt: report.checked_at || null,
      items: [],
    };
  }

  // 確認時刻を「いつの話か」が分かる形にする。未来や不正な値は素直に出さない。
  function formatCheckedAt(iso, now) {
    if (typeof iso !== 'string' || !iso) return '';
    const t = Date.parse(iso);
    if (Number.isNaN(t)) return '';
    const base = now instanceof Date ? now.getTime() : Date.now();
    const minutes = Math.floor((base - t) / 60000);
    if (minutes < 0) return new Date(t).toLocaleString('ja-JP');
    if (minutes < 60) return `${minutes}分前`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}時間前`;
    return `${Math.floor(hours / 24)}日前`;
  }

  return { describe, formatCheckedAt };
});
