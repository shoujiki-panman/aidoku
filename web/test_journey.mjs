// 道のりマップの組み立てテスト。DOM無しで回る（web/assets/journey.js のみ）。
// 実行: node web/test_journey.mjs
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { parseStep, nearlySame, buildStages } = require('./assets/journey.js');

let pass = 0, fail = 0;
const check = (n, c, d = '') => c ? (pass++, console.log(`  PASS  ${n}`))
                                  : (fail++, console.log(`  FAIL  ${n}  ${d}`));

// --- parseStep ---
const s1 = parseStep('住所や世帯を変更したときの届け出 → /a/b.html', 'https://x.lg.jp');
check('文言とURLに割れる', s1.text === '住所や世帯を変更したときの届け出' && s1.href === 'https://x.lg.jp/a/b.html');
check('絶対URLはそのまま', parseStep('a → https://y.jp/z', 'https://x.jp').href === 'https://y.jp/z');
check('矢印が無ければ文言だけ', parseStep('ただの文字', 'https://x.jp').href === null);
check('originが無ければhrefはnull', parseStep('a → /b', null).href === null);
check('文字列でなければnull', parseStep(null, 'https://x.jp') === null);

// --- nearlySame（世田谷の「届け出」/「届出」を拾えること）---
check('★一字違いを罠として拾う',
  nearlySame('住所や世帯を変更したときの届け出', '住所や世帯を変更したときの届出'));
check('同一は罠ではない', !nearlySame('あいうえお', 'あいうえお'));
check('大きく違うものは拾わない', !nearlySame('転入届についてはこちら', '粗大ごみの出し方'));
check('3文字以上違えば拾わない', !nearlySame('あいうえお', 'あいうえおかきく'));
check('空文字は拾わない', !nearlySame('', 'あ'));
check('記号と空白の差は無視する', nearlySame('住所や世帯を変更したときの届け出', '住所や世帯を変更したときの届出（）'));

// --- buildStages ---
const barrier = {
  failure: {
    observed_at_url: 'https://www.city.setagaya.lg.jp/kurashi/kosekijuumin/11531.html',
    path: [
      '住所や世帯を変更したときの届け出 → /kurashi/kosekijuumin/category/12307.html',
      '住所や世帯を変更したときの届出 → /02233/82.html',
      '転入届についてはこちら → /02233/88.html',
    ],
  },
  evidence: { official_page: 'https://www.city.setagaya.lg.jp/02233/88.html' },
};
const st = buildStages(barrier, { got: 0, total: 4, fields: [] });
check('スタート→止まった場所→…→ゴール', st.map((x) => x.kind).join(',') === 'start,stop,unreached,unreached,goal');
check('スタートは区のトップ', st[0].url === 'https://www.city.setagaya.lg.jp/');
check('止まった場所は採点したページ', st[1].url.endsWith('/11531.html'));
check('止まった場所に点数が乗る', st[1].score === '0/4');
check('ゴールは本体ページ', st[4].url.endsWith('/02233/88.html'));
check('★2歩目に罠の印が付く', st[3].trap !== null, JSON.stringify(st[3].trap));
check('罠は前後の文言を持つ', st[3].trap && st[3].trap.prev.includes('届け出') && st[3].trap.now.includes('届出'));
check('止まった場所から出る導線が分かる', st[1].exitVia === '住所や世帯を変更したときの届け出');

// 壊れた入力
check('barrierが空でも落ちない', buildStages(null, null).length === 2);
check('pathが無くても落ちない', buildStages({ failure: {} }, null).length === 2);

// --- explorer（どのAIで測ったかで見た目を変える）---
{
  const { explorer } = require('./assets/journey.js');
  const c = explorer('claude-sonnet-5', 'claude-cli');
  check('★Claudeを判別する', c.family === 'claude' && c.mark === '✳');
  check('モデル名は実測値をそのまま出す', c.model === 'claude-sonnet-5');
  check('GPTを判別する', explorer('gpt-4o').family === 'gpt');
  check('o系も GPT 扱い', explorer('o3-mini').family === 'gpt');
  check('Geminiを判別する', explorer('gemini-2.0-pro').family === 'gemini');
  check('Llamaを判別する', explorer('llama-3.3-70b').family === 'llama');
  check('知らないモデルは unknown', explorer('mystery-1').family === 'unknown');
  check('空でも落ちない', explorer(null, null).family === 'unknown');
  check('model しか無いときはそれを使う', explorer(null, 'claude-cli').family === 'claude');
}

// --- buildTimeline（再生の台本）---
{
  const { buildTimeline, BEAT } = require('./assets/journey.js');
  const F = [
    { name: '必要書類', ok: false }, { name: '窓口', ok: false },
    { name: '期限', ok: false }, { name: '手数料', ok: false },
  ];
  const st = buildStages(barrier, { got: 0, total: 4, fields: F });
  const tl = buildTimeline(st, F);
  const types = tl.map((t) => t.type);

  check('★スタートから始まる', types[0] === 'enter' && tl[0].index === 0);
  check('★歩いてから着く', types.indexOf('walk') < types.indexOf('enter', 1));
  check('★項目を1つずつ読む', types.filter((t) => t === 'read').length === 4);
  check('読む順は項目の順', tl.filter((t) => t.type === 'read').map((t) => t.field).join(',')
    === '必要書類,窓口,期限,手数料');
  check('★読み切ったあとに力尽きる', types.indexOf('exhausted') > types.lastIndexOf('read'));
  check('★力尽きたあとに進めなくなる', types.indexOf('blocked') > types.indexOf('exhausted'));
  check('★最後にゴールを見せる', types.indexOf('reveal-goal') > types.indexOf('blocked'));
  check('end で終わる', types[types.length - 1] === 'end');
  check('時刻は単調に増える', tl.every((t, i) => i === 0 || t.at >= tl[i - 1].at));
  check('止まった先へは歩かない',
    !tl.some((t) => t.type === 'walk' && st[t.index] && st[t.index].kind === 'unreached'));
  check('全体が短い（10秒以内）', tl[tl.length - 1].at <= 10000, `${tl[tl.length - 1].at}ms`);
  check('間隔は定数から来る', BEAT.move > 0 && BEAT.read > 0 && BEAT.pause > 0);
  check('stagesが空なら台本も空', buildTimeline([], F).length === 0);
  check('配列でなければ空', buildTimeline(null, F).length === 0);
  check('項目が無くても落ちない', buildTimeline(st, null).length > 0);
}

console.log(`\n  ${pass} PASS / ${fail} FAIL（台本を含む）`);
process.exit(fail === 0 ? 0 : 1);
