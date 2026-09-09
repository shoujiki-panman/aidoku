// 集計エクスポート（export_demand.mjs）のテスト。
// 実行: node gatekeeper/test_export_demand.mjs
//
// 確かめたいことは1つ。**見本を実データとして公開できてしまわないか。**
// （READMEもデッキも「見本を本物として見せない」を約束している。ここが最後の関所）
import { validateExport } from './export_demand.mjs';
import { aggregate } from './demand.mjs';

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

console.log('テスト:');

// 本物の集計（aggregate の実物の出力）は通る
{
  const store = [
    { name: 'ask:1:a', metadata: { ts: '2026-09-09T00:26:00Z', authority: 'x', path: '/p', looking_for: null, answered: false, verified: true, agent: 'https://chatgpt.com' } },
  ];
  const env = { DEMAND: { list: async () => ({ keys: store, list_complete: true }) } };
  const data = await aggregate(env);
  check('aggregate の実物の出力が通る', validateExport(data).length === 0, JSON.stringify(validateExport(data)));
}

// 見本（is_sample）は絶対に通らない
{
  const sample = { is_sample: true, generated_at: 'x', totals: { asks: 56 }, by_agent: [] };
  const problems = validateExport(sample);
  check('見本は拒否される', problems.some((p) => p.includes('見本')), JSON.stringify(problems));
}

// 形が崩れたものは理由つきで全部拒否
{
  const problems = validateExport({});
  check('集計の形でないものは拒否される', problems.length >= 3, JSON.stringify(problems));
  check('JSONでないものも落ちない', validateExport(null).length === 1);
}

console.log(`\n結果: ${pass} PASS / ${fail} FAIL`);
if (fail > 0) process.exit(1);
