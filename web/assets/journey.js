// AIがどこから入って、どこでつまづいたか ── 道のりのマップ。
//
// データは data/barriers.json だけ。新しい書き出しは要らない。
//   failure.observed_at_url      … AIが実際に採点したページ（＝止まった場所）
//   failure.path[]               … そこから本体ページまでの導線（リンク文言 → URL）
//   failure.clicks_to_official_page … 本体まで何クリックか
//   evidence.official_page       … 4項目がそろっている本体ページ（＝ゴール）
//   counterfactual               … ページを読んでいることの裏取り
//
// ★ここで数字を作らない。すべて barriers.json と scores-*.json の実測値。
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.AidokuJourney = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // "住所や世帯を変更したときの届け出 → /kurashi/kosekijuumin/category/12307.html"
  // を { text, href } に割る。矢印が無い行は、全部を文言として扱う（落とさない）。
  function parseStep(line, origin) {
    if (typeof line !== 'string') return null;
    const i = line.lastIndexOf('→');
    if (i === -1) return { text: line.trim(), href: null };
    const text = line.slice(0, i).trim();
    const path = line.slice(i + 1).trim();
    const href = /^https?:\/\//.test(path) ? path
      : (origin && path.startsWith('/') ? origin.replace(/\/$/, '') + path : null);
    return { text, href };
  }

  const originOf = (url) => {
    try { return new URL(url).origin; } catch { return null; }
  };

  // 隣り合う導線の文言が「ほぼ同じ」か。世田谷の「届け出」/「届出」を拾うため。
  // 記号と空白を落として比べ、1〜2文字しか違わなければ罠とみなす。
  function nearlySame(a, b) {
    const norm = (s) => String(s || '').replace(/[\s・･、。「」（）()]/g, '');
    const x = norm(a);
    const y = norm(b);
    if (!x || !y || x === y) return false;
    const [s, l] = x.length <= y.length ? [x, y] : [y, x];
    if (l.length - s.length > 2) return false;
    // 短いほうが長いほうの「部分列」なら、一字二字の増減だけ。
    // includes だと途中の1文字挿入を拾えない（「届出」⊂「届け出」が false になる）。
    let i = 0;
    for (const ch of l) if (i < s.length && ch === s[i]) i += 1;
    return i === s.length;
  }

  // マップ1本ぶんのステージ列を組み立てる
  function buildStages(barrier, cell) {
    const stopUrl = barrier?.failure?.observed_at_url || null;
    const origin = originOf(stopUrl);
    const steps = (barrier?.failure?.path || [])
      .map((l) => parseStep(l, origin)).filter(Boolean);
    const goal = barrier?.evidence?.official_page || null;

    const stages = [];
    stages.push({ kind: 'start', label: '区のトップページ', url: origin ? origin + '/' : null });
    stages.push({
      kind: 'stop',
      label: 'AIはここで力尽きた',
      url: stopUrl,
      via: null,
      score: cell ? `${cell.got}/${cell.total}` : null,
      fields: cell ? cell.fields : [],
    });
    steps.forEach((s, i) => {
      const last = i === steps.length - 1;
      stages.push({
        kind: last ? 'goal' : 'unreached',
        label: last ? '4項目がそろっている本体ページ' : '未踏',
        url: last && goal ? goal : s.href,
        via: s.text,
        trap: i > 0 && nearlySame(steps[i - 1].text, s.text)
          ? { prev: steps[i - 1].text, now: s.text } : null,
      });
    });
    // 導線の1本目は「止まった場所」から出ているので、via を止まった側に移す
    if (stages[2] && stages[2].via) stages[1].exitVia = stages[2].via;
    return stages;
  }

  // 道を歩いた探索者。どのAIで測ったかで見た目を変える。
  //
  // ★各社の公式ロゴ画像は使わない。公開する作品に他社の商標をそのまま置くと
  //   「公認である」と読まれかねないため。ここでは自前の記号と色で系統を示し、
  //   モデル名は文字でそのまま出す（measurement.model_version の実測値）。
  const EXPLORERS = [
    { test: /claude/, family: 'claude', mark: '✳', vendor: 'Anthropic Claude' },
    { test: /gpt|openai|^o\d/, family: 'gpt', mark: '◉', vendor: 'OpenAI GPT' },
    { test: /gemini|palm/, family: 'gemini', mark: '◆', vendor: 'Google Gemini' },
    { test: /llama/, family: 'llama', mark: '▲', vendor: 'Meta Llama' },
  ];

  function explorer(modelVersion, model) {
    const v = String(modelVersion || model || '').toLowerCase();
    const hit = EXPLORERS.find((e) => e.test.test(v));
    return {
      family: hit ? hit.family : 'unknown',
      mark: hit ? hit.mark : '?',
      vendor: hit ? hit.vendor : '不明なモデル',
      // 実測値をそのまま出す。ここで整形しない
      model: modelVersion || model || null,
    };
  }

  return { parseStep, nearlySame, buildStages, explorer };
});
