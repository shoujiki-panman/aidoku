// 「今やる1件」の選定と依頼文のテスト。DOM無しで回る（web/assets/next-action.js のみ）。
// 実行: node web/test_next_action.mjs
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { pickNextAction, buildRequestText, buildRecheckCommand } =
  require('./assets/next-action.js');

let pass = 0;
let fail = 0;
function check(name, cond, detail = '') {
  if (cond) {
    pass++;
    console.log(`  PASS  ${name}`);
  } else {
    fail++;
    console.log(`  FAIL  ${name}  ${detail}`);
  }
}

// data/fact-types.json と同じ並び（fact_types → extra_measures）
const ORDER = ['必要書類', '窓口/オンライン可否', '期限', '手数料', 'オンライン明示'];

// --- pickNextAction: 正常系 ---

{
  const got = pickNextAction(
    [{ field: '手数料', gain: 20, reason: '額を書く' }], ORDER);
  check('1件だけならその1件', got !== null && got.field === '手数料');
}

{
  const got = pickNextAction([
    { field: 'オンライン明示', gain: 10, reason: 'r1' },
    { field: '手数料', gain: 20, reason: 'r2' },
  ], ORDER);
  check('gain が大きい方が勝つ（並び順に依存しない）', got.field === '手数料');
}

// --- 同点 ---

{
  const got = pickNextAction([
    { field: '手数料', gain: 20, reason: 'r1' },
    { field: '必要書類', gain: 20, reason: 'r2' },
  ], ORDER);
  check('同点は fact-types 定義順が先（必要書類 < 手数料）', got.field === '必要書類');
}

{
  const got = pickNextAction([
    { field: 'zz未知の項目', gain: 20, reason: 'r1' },
    { field: '手数料', gain: 20, reason: 'r2' },
  ], ORDER);
  check('定義に無い項目名は既知の項目より後ろ', got.field === '手数料');
}

{
  const got = pickNextAction([
    { field: 'b未知', gain: 20, reason: 'r1' },
    { field: 'a未知', gain: 20, reason: 'r2' },
  ], ORDER);
  check('未知同士は field の文字列順で決定的', got.field === 'a未知');
}

{
  const a = pickNextAction([
    { field: '期限', gain: 20, reason: 'r1' },
    { field: '必要書類', gain: 20, reason: 'r2' },
  ], ORDER);
  const b = pickNextAction([
    { field: '必要書類', gain: 20, reason: 'r2' },
    { field: '期限', gain: 20, reason: 'r1' },
  ], ORDER);
  check('入力の並びを逆にしても同じ1件（決定的）', a.field === b.field);
}

// --- 欠損・空配列 ---

check('空配列は null（架空の1件を作らない）', pickNextAction([], ORDER) === null);
check('undefined は null', pickNextAction(undefined, ORDER) === null);
check('null は null', pickNextAction(null, ORDER) === null);

// --- 不正型 ---

check('配列でない improvements は null',
  pickNextAction({ field: '手数料', gain: 20 }, ORDER) === null);

{
  const got = pickNextAction(
    [null, 'x', 42, [], { gain: 20 }, { field: '', gain: 20 }], ORDER);
  check('壊れた行だけなら null（例外も出さない）', got === null);
}

{
  const got = pickNextAction([
    null,
    { field: '手数料', gain: 20, reason: 'r' },
    'x',
  ], ORDER);
  check('壊れた行が混ざっても正常な行から選ぶ', got !== null && got.field === '手数料');
}

{
  const got = pickNextAction([
    { field: '期限', gain: 'たくさん', reason: 'r1' },
    { field: '手数料', gain: 20, reason: 'r2' },
  ], ORDER);
  check('gain が数値でない行は 0 扱い（数値の行が勝つ）', got.field === '手数料');
}

{
  const got = pickNextAction([
    { field: '期限', gain: NaN, reason: 'r1' },
    { field: '手数料', gain: 10, reason: 'r2' },
  ], ORDER);
  check('gain が NaN でも比較が壊れない', got.field === '手数料');
}

{
  const got = pickNextAction(
    [{ field: '手数料', gain: 20, reason: 'r' }], '定義順ではない文字列');
  check('factOrder が配列でなくても落ちない', got !== null && got.field === '手数料');
}

{
  const input = [
    { field: '手数料', gain: 20, reason: 'r1' },
    { field: '必要書類', gain: 10, reason: 'r2' },
  ];
  const before = JSON.stringify(input);
  pickNextAction(input, ORDER);
  check('入力の配列を並べ替えない（Pure）', JSON.stringify(input) === before);
}

// --- buildRequestText ---

const PARTS = {
  muniName: '足立区',
  procedureName: '転入届',
  field: '手数料',
  reason: '手数料の額を書く。無料なら「無料」と書く',
  pageUrl: 'https://www.city.adachi.tokyo.jp/koseki/kurashi/todokede/h-tennyu.html',
  gain: 20,
};

{
  const t = buildRequestText(PARTS);
  check('依頼文に自治体名・手続き・項目・URL・直し方が入る',
    t.includes('足立区') && t.includes('転入届') && t.includes('手数料') &&
    t.includes(PARTS.pageUrl) && t.includes(PARTS.reason));
  check('依頼文は見込みであることを明示する（未検証を隠さない）',
    t.includes('見込') && t.includes('再測定'));
  check('「必ず直る」と書かない', !t.includes('必ず'));
}

{
  const t = buildRequestText({ ...PARTS, gain: undefined });
  check('gain が無ければ点の行を出さない（数字を作らない）',
    t !== '' && !t.includes('+') && !t.includes('点の改善'));
}

check('必須の文字列が欠けたら空文字（架空の依頼文を作らない）',
  buildRequestText({ ...PARTS, pageUrl: '' }) === '');
check('引数が object でなければ空文字', buildRequestText(null) === '');

// --- buildRecheckCommand ---

{
  const c = buildRecheckCommand('adachi', 'tennyu');
  check('再確認コマンドに自治体IDと手続きIDが入る',
    c.includes('-m adachi') && c.includes('-p tennyu') &&
    c.includes('scores-tennyu.json'));
}

check('IDが想定外の形ならコマンドを出さない（画面への混入防止）',
  buildRecheckCommand('adachi; rm -rf /', 'tennyu') === '' &&
  buildRecheckCommand('adachi', '../etc') === '' &&
  buildRecheckCommand(undefined, 'tennyu') === '');

// --- 実データとの突き合わせ（scores-*.json の improvements がこの関数で選べる形か） ---

import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const dataDir = join(here, 'data');
const ft = JSON.parse(readFileSync(join(dataDir, 'fact-types.json'), 'utf8'));
const order = [
  ...ft.fact_types.map((f) => f.display_label),
  ...ft.extra_measures.map((m) => m.display_label),
];

for (const file of readdirSync(dataDir).filter((f) => /^scores-.*\.json$/.test(f))) {
  const d = JSON.parse(readFileSync(join(dataDir, file), 'utf8'));
  let broken = 0;
  for (const m of d.municipalities) {
    const picked = pickNextAction(m.improvements, order);
    const should = Array.isArray(m.improvements) &&
      m.improvements.some((e) => e && typeof e.field === 'string' && e.field !== '');
    if (should !== (picked !== null)) broken++;
    if (picked !== null &&
        (typeof picked.reason !== 'string' || picked.reason === '')) broken++;
  }
  check(`実データ ${file}: 改善案のある自治体すべてで1件選べて reason も付く`, broken === 0,
    `broken=${broken}`);
}

// --- 結果 ---
console.log(`\n${pass} PASS / ${fail} FAIL`);
if (fail > 0) process.exit(1);
