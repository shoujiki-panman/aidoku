// 道のりマップの組み立てテスト。DOM無しで回る（web/assets/journey.js のみ）。
// 実行: node web/test_journey.mjs
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { parseStep, nearlySame, buildStages, whyLines } = require('./assets/journey.js');

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

// --- 4項目そろった回。ここを間違えると画面の上下で矛盾する ---
// ★本人の指摘:「港区の場合、届けられたのでは？」
//   4項目そろっているのに 赤い✖・「ここで力尽きた」・
//   「このページの本文に4項目が書かれていなかった」を出していた。
{
  const done = whyLines({ got: 4, total: 4, blame: 'site' });
  check('★そろった回は見出しを変える', done.title === 'どうやってそろえたか', done.title);
  const t = done.steps.map((s) => s.text).join('|');
  check('★「書かれていなかった」と言わない', !t.includes('書かれていなかった'), t);
  check('書かれていたと言う', t.includes('4項目とも書かれていた'), t);
  check('★「手続きの名前が無かった」も言わない', !t.includes('手続きの名前が無かった'), t);

  const half = whyLines({ got: 2, total: 4, blame: 'site' });
  check('力尽きた回は見出しがそのまま', half.title === 'どうやって力尽きたか');
  check('★足りない数を実際の数で言う',
    half.steps.some((s) => s.text.includes('2項目が書かれていなかった')),
    half.steps.map((s) => s.text).join('|'));

  const ours = whyLines({ got: 0, total: 4, blame: 'ours',
    missed_with_strong_word: [{ link_text: '転入届の手続き', score: 30 }] });
  check('こちらの都合なら、選ばなかったリンクを出す',
    ours.steps.some((s) => s.whose === 'ours' && s.text.includes('転入届の手続き')));
  check('その場合「手続きの名前が無かった」は出さない',
    !ours.steps.map((s) => s.text).join('|').includes('手続きの名前が無かった'));

  check('点数が不明でも落ちない', typeof whyLines({}).title === 'string');
  check('引数が無くても落ちない', Array.isArray(whyLines().steps));
  check('観察記録はそのまま持つ', whyLines({ got: 4, total: 4 }, 'メモ').notes === 'メモ');
}

// --- そろった回の見た目と再生 ---
{
  const cell = { got: 4, total: 4, fields: [
    { name: '必要書類', ok: true }, { name: '窓口/オンライン可否', ok: true },
    { name: '期限', ok: true }, { name: '手数料', ok: true }] };
  const stages = buildStages({ failure: { observed_at_url: 'https://x.example/a.html', path: [] } }, cell);
  const node = stages.find((s) => s.kind === 'done' || s.kind === 'stop');
  check('★そろった回は stop ではない', node.kind === 'done', node.kind);
  check('ラベルもそろえた側', node.label === 'AIはここで4項目そろえた');

  const { buildTimeline } = require('./assets/journey.js');
  const tl = buildTimeline(stages, cell.fields);
  const kinds = tl.map((b) => b.type);
  check('★そろった回でも4項目を1つずつ読む', kinds.filter((k) => k === 'read').length === 4, kinds.join(','));
  check('★そろった回に「力尽きた」の演出を出さない',
    !kinds.includes('exhausted') && !kinds.includes('blocked'), kinds.join(','));
  check('再生はちゃんと終わる', kinds[kinds.length - 1] === 'end');
}

console.log(`\n  ${pass} PASS / ${fail} FAIL（台本を含む）`);
process.exit(fail === 0 ? 0 : 1);
