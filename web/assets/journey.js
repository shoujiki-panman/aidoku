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
    const reached = cell && cell.got === cell.total;
    stages.push({
      // ★4項目そろった区に「力尽きた」の赤い✖を出していた（本人の指摘）。
      //   ラベルだけ直しても、印と見出しと理由の文が「力尽きた」のままだった。
      kind: reached ? 'done' : 'stop',
      label: reached ? 'AIはここで4項目そろえた' : 'AIはここで力尽きた',
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

  // ── 再生の台本 ────────────────────────────────────────────
  // ★AIに慣れていない人には「どうやって読んで、どこで読めなかったか」が
  //   静止画では伝わらない。歩く → 項目をひとつずつ試す → 進めずに止まる、を
  //   順番に見せる。台本はここで作り、動かすのは view 側。
  //
  //   at はミリ秒（先頭からの経過）。テストで順番と間隔を固定できるようにする。
  const BEAT = {
    move: 900,    // 1歩ぶん歩く
    read: 550,    // 1項目ぶん読む
    pause: 700,   // 溜め
  };

  function buildTimeline(stages, fields) {
    if (!Array.isArray(stages) || !stages.length) return [];
    const out = [];
    let at = 0;
    const push = (type, payload, hold) => {
      out.push({ at, type, ...payload });
      at += hold;
    };

    push('enter', { index: 0 }, BEAT.pause);

    for (let i = 1; i < stages.length; i += 1) {
      const s = stages[i];
      // 看板を読む → 歩く → 着く
      if (s.via || (stages[i - 1] && stages[i - 1].exitVia)) {
        push('sign', { index: i, text: s.via || stages[i - 1].exitVia }, BEAT.pause);
      }
      push('walk', { index: i, blocked: s.kind === 'unreached' || s.kind === 'goal' }, BEAT.move);
      push('enter', { index: i }, BEAT.pause);

      // ★4項目そろった回（done）も、ここで4項目を読む。
      //   以前は stop だけを見ていたので、そろった区は再生が何も起きずに終わっていた。
      if (s.kind === 'stop' || s.kind === 'done') {
        // 4項目をひとつずつ試す
        (fields || []).forEach((f, k) => {
          push('read', { index: i, field: f.name, ok: f.ok, order: k }, BEAT.read);
        });
        if (s.kind === 'stop') {
          push('exhausted', { index: i }, BEAT.pause);
          // ここから先へ行こうとして、行けない
          push('blocked', { index: i }, BEAT.pause);
          // 「この先に答えがあった」を最後に見せる。ここが一番効く
          const goal = stages.findIndex((x) => x.kind === 'goal');
          if (goal !== -1) push('reveal-goal', { index: goal }, BEAT.pause);
        }
        break;
      }
    }
    push('end', {}, 0);
    return out;
  }

  // その1件がどうなったかを、事実のまま並べる。
  // ★以前は結果によらず「このページの本文に4項目が書かれていなかった」を出していた。
  //   4項目そろった港区でもそう出るので、画面の上下で矛盾していた。
  function whyLines(journey, notes) {
    const j = journey || {};
    const got = Number(j.got);
    const total = Number(j.total);
    const known = Number.isFinite(got) && Number.isFinite(total) && total > 0;
    const reached = known && got === total;
    const missing = known ? total - got : null;
    const near = (j.missed_with_strong_word || [])[0];
    const steps = [
      { whose: 'ours', text: '：探索が候補を集め、このページを1位に選んだ' },
      { whose: 'ours', text: '：採点のとき、本文とリンク一覧（上限40件）だけをAIに渡した' },
    ];
    // 選ばれなかった候補に手続き名があったなら、原因はこちら側
    if (j.blame === 'ours' && near) {
      steps.push({ whose: 'ours',
        text: `：同じ画面に「${near.link_text}」（${near.score}点）が出ていたのに選ばなかった。道はあった` });
    } else if (!reached) {
      steps.push({ whose: 'site', text: '：見えていた候補のどれにも、手続きの名前が無かった' });
    }
    if (reached) {
      // ★良い知らせなので、区に赤い札を付けない
      steps.push({ whose: 'site', good: true,
                   text: '：このページの本文に、4項目とも書かれていた' });
    } else if (missing !== null) {
      steps.push({ whose: 'site', text: `：このページの本文に、${missing}項目が書かれていなかった` });
    } else {
      steps.push({ whose: 'site', text: '：このページの本文に、4項目が書かれていなかった' });
    }
    return {
      title: reached ? 'どうやってそろえたか' : 'どうやって力尽きたか',
      notes: notes || '',
      steps,
    };
  }

  return { parseStep, nearlySame, buildStages, explorer, buildTimeline, whyLines, BEAT };
});
