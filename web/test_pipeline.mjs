// 「この数字はどう作られたか」の言い方のテスト。DOM無しで回る。
// 実行: node web/test_pipeline.mjs
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
const require = createRequire(import.meta.url);
const P = require('./assets/pipeline-list.js');

let pass = 0, fail = 0;
function check(name, cond, detail = '') {
  if (cond) { pass++; console.log(`  PASS  ${name}`); }
  else { fail++; console.log(`  FAIL  ${name}  ${detail}`); }
}

const LAYERS = [
  { dir: 'crawler', lines: 1000 },
  { dir: 'web/assets', lines: 3000 },
];

// --- 見出し ---
{
  const h = P.headline(LAYERS);
  check('合計行数を言う', h.includes('4,000行'), h);
  check('画面の割合を言う', h.includes('75%'), h);
  check('★画面が何割かを言い切る（ここが指摘の答え）', h.includes('残りは測るための仕組み'), h);
  check('層が無ければ空', P.headline([]) === '');
  check('引数無しでも落ちない', typeof P.headline() === 'string');
  check('割合の計算', P.screenShare(LAYERS) === 75);
  check('画面が無ければ割合も出さない', P.screenShare([{ dir: 'crawler', lines: 10 }]) === null);
}

// --- 対照実験 ---
{
  const exp = { trials: 5, variants: [
    { key: 'before', all_four: 0 }, { key: 'after', all_four: 5 }] };
  const line = P.experimentLine(exp);
  check('前後の回数を言う', line.includes('5回中0回') && line.includes('5回中5回'), line);
  check('試行回数が無ければ何も言わない', P.experimentLine({ variants: exp.variants }) === '');
  check('引数無しでも落ちない', P.experimentLine() === '');
}

// --- 反実仮想。ここが「読んでいる」の根拠 ---
{
  const cf = { changed: '期限 14日→37日', returned_original: 0, returned_modified: 5 };
  const line = P.counterfactualLine(cf);
  check('書き換えた側を返した回数を言う', line.includes('5回のうち5回'), line);
  check('元の値を返した回数も言う', line.includes('元の値を返したのは0回'), line);
  check('★回数から推測せず、実数から言う（0回も出す）', line.includes('0回'), line);
  check('数が無ければ何も言わない', P.counterfactualLine({ changed: 'あれ' }) === '');
  check('引数無しでも落ちない', P.counterfactualLine() === '');
}

// --- 較正。無いものを「無い」と言う ---
{
  const cal = { by_procedure: { a: { rows: 12, municipalities: 3 }, b: { rows: 0, municipalities: 0 } },
                missing: ['b'] };
  const line = P.calibrationLine(cal);
  check('あるぶんの件数を言う', line.includes('3自治体・12行'), line);
  check('★無い手続きがあることを隠さない', line.includes('残り1手続きには正解データがなく'), line);
  check('★区別できないと明言する', line.includes('区別できません'), line);
  check('正解データが無ければ、無いと言う',
    P.calibrationLine({ by_procedure: {} }).includes('まだありません'));
  check('引数無しでも落ちない', typeof P.calibrationLine() === 'string');
}

// --- 測定条件 ---
{
  check('条件の数を言う', P.conditionLine(['a', 'b']).includes('2項目'));
  check('比較を拒否すると言う', P.conditionLine(['a']).includes('比較を拒否'));
  check('空なら何も言わない', P.conditionLine([]) === '');
}

// --- 公開データ ---
{
  const doc = JSON.parse(readFileSync(new URL('./data/pipeline.json', import.meta.url), 'utf8'));
  check('層が並んでいる', Array.isArray(doc.layers) && doc.layers.length >= 5);
  check('★行数は実ファイル由来（0行の層が無い）', doc.layers.every((l) => l.lines > 0));
  check('取得層がある', doc.layers.some((l) => l.dir === 'crawler'));
  check('★測定条件は measurement.py と同じ数', doc.condition_keys.length === 12,
    String(doc.condition_keys.length));
  check('★link_order が入っている（今日足した条件）', doc.condition_keys.includes('link_order'));
  check('対照実験の3条件がある', doc.experiment.variants.length === 3);
  check('反実仮想の実数がある', typeof doc.counterfactual.returned_modified === 'number');
  check('★較正の穴を隠していない', (doc.calibration.missing || []).length > 0);

  // ★当てにならない数字を出さないと決めた。テスト件数は静的に数えると実行時と合わない
  check('★テスト件数は公開しない', doc.layers.every((l) => !('test_cases' in l)));
}

// --- 画面から行けること ---
{
  const data = readFileSync(new URL('./reference/data.html', import.meta.url), 'utf8');
  check('調べ方とデータから行ける', data.includes('reference/how.html'));
  const index = readFileSync(new URL('./index.html', import.meta.url), 'utf8');
  check('住民の画面のフッターからも行ける', index.includes('reference/how.html'));
}

console.log(`\n  ${pass} PASS / ${fail} FAIL`);
process.exit(fail === 0 ? 0 : 1);
