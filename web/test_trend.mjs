// 前回からの差のテスト。DOM無しで回る（web/assets/trend.js のみ）。
// 実行: node web/test_trend.mjs
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { parseJsonl, attribution, wardSeries, lastChange, watchSeries } = require('./assets/trend.js');

let pass = 0, fail = 0;
const check = (n, c, d = '') => c ? (pass++, console.log(`  PASS  ${n}`))
                                  : (fail++, console.log(`  FAIL  ${n}  ${d}`));

const F = ['必要書類', '窓口/オンライン可否', '期限', '手数料'];
const snap = (at, id, got, { sig = 'S1', rec = 'recorded', proc = 'tennyu' } = {}) => ({
  generated_at: at, procedure_id: proc, measurement_signature: sig, recording_status: rec,
  municipalities: [{ id, name: `${id}区`, breakdown: Object.fromEntries(F.map((f, i) => [f, i < got ? 20 : 0])) }],
});

// --- parseJsonl ---
check('1行1件で読む', parseJsonl('{"a":1}\n{"a":2}').length === 2);
check('空行を飛ばす', parseJsonl('{"a":1}\n\n  \n{"a":2}').length === 2);
check('壊れた行を飛ばして続ける', parseJsonl('{"a":1}\nこわれ\n{"a":2}').length === 2);
check('配列の行は入れない', parseJsonl('[1,2]\n{"a":1}').length === 1);
check('文字列でなければ空', parseJsonl(null).length === 0);

// --- attribution（この機能の芯）---
check('★条件が同じで記録済みならサイト側',
  attribution({ measurement_signature: 'S', recording_status: 'recorded' },
              { measurement_signature: 'S', recording_status: 'recorded' }).how === 'site');
check('★条件が違えば原因は言えない',
  attribution({ measurement_signature: 'A', recording_status: 'recorded' },
              { measurement_signature: 'B', recording_status: 'recorded' }).how === 'unknown');
check('★条件未記録なら原因は言えない',
  attribution({ measurement_signature: 'S', recording_status: 'legacy_unknown' },
              { measurement_signature: 'S', recording_status: 'legacy_unknown' }).how === 'unknown');
check('片方が無ければ unknown', attribution(null, {}).how === 'unknown');

// --- wardSeries ---
{
  const s = wardSeries([snap('2026-08-01', 'a', 1), snap('2026-08-05', 'a', 3)], 'a', F);
  check('時刻順に並ぶ', s.map((x) => x.got).join(',') === '1,3');
  check('満点は項目数', s[0].total === 4);
}
{
  // 同じ時刻の複数手続きは合算する（12項目のメーターと同じ数え方）
  const s = wardSeries([
    snap('2026-08-05', 'a', 2, { proc: 'tennyu' }),
    snap('2026-08-05', 'a', 1, { proc: 'sodaigomi' }),
  ], 'a', F);
  check('★同じ時刻の手続きを合算する', s.length === 1 && s[0].got === 3 && s[0].total === 8);
}
check('居ない区は空', wardSeries([snap('2026-08-01', 'a', 1)], 'zzz', F).length === 0);

// --- lastChange ---
{
  const c = lastChange(wardSeries([snap('2026-08-01', 'a', 1), snap('2026-08-05', 'a', 3)], 'a', F));
  check('直近の差を出す', c.delta === 2);
  check('条件が同じならサイト側と言える', c.how === 'site');
}
{
  const c = lastChange(wardSeries([
    snap('2026-08-01', 'a', 1, { rec: 'legacy_unknown' }),
    snap('2026-08-05', 'a', 3, { rec: 'legacy_unknown' }),
  ], 'a', F));
  check('★条件未記録でも数字は出す', c.delta === 2);
  check('★ただし原因は言わない', c.how === 'unknown');
}
{
  const c = lastChange(wardSeries([snap('2026-08-01', 'a', 2), snap('2026-08-05', 'a', 2)], 'a', F));
  check('動いていなければ0（「変化なし」も情報）', c.delta === 0);
}
check('1点しかなければ null', lastChange(wardSeries([snap('2026-08-01', 'a', 1)], 'a', F)) === null);
check('配列でなければ null', lastChange(null) === null);

// --- watchSeries ---
{
  const w = watchSeries([
    { checked_at: '2026-08-19', changed: [{ gone: false }, { gone: true }], summary: { total: 68 } },
    { checked_at: '2026-08-17', changed: [], summary: { total: 23 } },
  ]);
  check('見張りも時刻順', w.map((x) => x.at).join(',') === '2026-08-17,2026-08-19');
  check('変化数を数える', w[1].changed === 2);
  check('消えたページを別に数える', w[1].gone === 1);
  check('checked_at が無い行は落とす', watchSeries([{ changed: [] }]).length === 0);
}

console.log(`\n  ${pass} PASS / ${fail} FAIL`);
process.exit(fail === 0 ? 0 : 1);
