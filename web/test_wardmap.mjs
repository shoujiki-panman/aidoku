// 23区の地図のテスト。DOM無しで回る（web/assets/wardmap.js のみ）。
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { tone, wardProgress, decorate } = require('./assets/wardmap.js');

let pass = 0, fail = 0;
const check = (n, c, d = '') => c ? (pass++, console.log(`  PASS  ${n}`))
                                  : (fail++, console.log(`  FAIL  ${n}  ${d}`));
const F = ['a', 'b', 'c', 'd'];
const cell = (name, id, got) => ({
  muniName: name, muniId: id,
  breakdown: Object.fromEntries(F.map((f, i) => [f, i < got ? 20 : 0])),
});

check('満点に近ければ high', tone(9, 12) === 'high');
check('半分なら mid', tone(6, 12) === 'mid');
check('少しなら low', tone(2, 12) === 'low');
check('ゼロは zero', tone(0, 12) === 'zero');
check('測っていなければ unknown', tone(0, 0) === 'unknown');

{
  const p = wardProgress([cell('港区', 'minato', 4), cell('港区', 'minato', 3)], F);
  check('★同じ区の手続きを合算する', p.get('港区').got === 7 && p.get('港区').total === 8);
  check('区IDを持つ', p.get('港区').id === 'minato');
}
check('壊れた行は落とす', wardProgress([null, { muniName: '' }, cell('港区', 'minato', 1)], F).size === 1);
check('空でも落ちない', wardProgress(null, F).size === 0);

{
  const wards = [{ code: '13103', name: '港区', d: 'M0,0Z' }, { code: '13112', name: '世田谷区', d: 'M1,1Z' }];
  const out = decorate(wards, wardProgress([cell('港区', 'minato', 4)], F));
  check('測った区は数字を持つ', out[0].got === 4 && out[0].total === 4);
  check('★測っていない区は unknown（0点にしない）', out[1].tone === 'unknown' && out[1].got === null);
  check('測っていない区はそう書く', out[1].label.includes('測っていません'));
  check('パスはそのまま渡す', out[0].d === 'M0,0Z');
  check('区の数は減らない', out.length === 2);
}
check('wardsが空でも落ちない', decorate(null, new Map()).length === 0);

console.log(`\n  ${pass} PASS / ${fail} FAIL`);
process.exit(fail === 0 ? 0 : 1);
