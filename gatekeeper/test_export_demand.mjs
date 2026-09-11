// 集計エクスポート（export_demand.mjs）のテスト。
// 実行: node gatekeeper/test_export_demand.mjs
//
// 確かめたいことは1つ。**見本を実データとして公開できてしまわないか。**
// （READMEもデッキも「見本を本物として見せない」を約束している。ここが最後の関所）
import { validateExport } from './export_demand.mjs';
import { aggregate, isAnswered, normalizeDemandSnapshot } from './demand.mjs';

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
  check('旧記録の質問なしfalseを判定対象外に補正', data.totals.unanswered === 0 && data.totals.undetermined === 1 && data.unanswered.length === 0);
  check('エージェント別・ページ別にも失敗を残さない', data.by_agent[0].unanswered === 0 && data.all[0].unanswered_count === 0);
}

for (const q of [null, '', '　 ', 'こんにちは']) {
  check(`質問を特定できない場合はnull: ${q}`, isAnswered(null, q) === null && isAnswered({ fields: { fee: '無料' } }, q) === null);
}
check('指定項目が無ければfalse', isAnswered(null, '手数料') === false);
check('指定項目があればtrue', isAnswered({ fields: { fee: '無料' } }, '手数料') === true);
{
  const old = { totals: { asks: 3, answered: 1, unanswered: 1, undetermined: 0, unverified: 1 }, by_agent: [{ agent: 'a', asks: 2, answered: 1, unanswered: 1 }], all: [
    { looking_for: null, count: 2, answered_count: 0, unanswered_count: 1, by_agent: { a: { asks: 1, answered: 0, unanswered: 1 } } },
    { looking_for: '手数料', count: 1, answered_count: 1, unanswered_count: 0, by_agent: { a: { asks: 1, answered: 1, unanswered: 0 } } },
  ] };
  const fixed = normalizeDemandSnapshot(old);
  check('集計訂正は件数と既知の質問を保持する', fixed.totals.asks === 3 && fixed.totals.unverified === 1 && fixed.totals.answered === 1 && fixed.totals.unanswered === 0 && fixed.totals.undetermined === 1);
  check('訂正は元データを変更しない', old.totals.unanswered === 1);
  check('訂正を繰り返しても増減しない', JSON.stringify(fixed) === JSON.stringify(normalizeDemandSnapshot(fixed)));
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
