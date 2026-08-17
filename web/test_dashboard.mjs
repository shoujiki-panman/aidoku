import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

function loadBrowserFunctions(path, names) {
  const source = fs.readFileSync(path, 'utf8').replace(
    /\ninit\(\)\.catch\([\s\S]*$/,
    '',
  );
  const context = { URLSearchParams };
  vm.createContext(context);
  vm.runInContext(
    `${source}\nglobalThis.__test = { ${names.join(', ')}, setItems: (values) => { ITEMS = values; }, setFields: (values) => { FIELDS = values; } };`,
    context,
    { filename: path },
  );
  return context.__test;
}

const app = loadBrowserFunctions('web/assets/app.js', [
  'answered',
  'gainText',
  'scoreText',
]);

assert.equal(app.answered({ answered: true, verdict: '読めない' }), true);
assert.equal(app.answered({ answered: false, verdict: '読めた' }), false);
assert.equal(app.answered({ verdict: '読めた' }), true);
assert.equal(app.scoreText({ total: null }), '未検証');
assert.equal(app.scoreText({ total: 0 }), '0/100点');
assert.equal(app.scoreText({ total: 100 }), '100/100点');
app.setFields(['必要書類']);
assert.equal(app.gainText({ field: '必要書類', gain: null }), '点数未検証');
assert.equal(app.gainText({ field: '必要書類', gain: 20 }), '+20点');
assert.equal(app.gainText({ field: 'オンライン明示', gain: 20 }), '明示度 +20点');

const board = loadBrowserFunctions('web/assets/board.js', ['cellState']);
board.setItems(['a', 'b', 'c', 'd']);
const fields = (count) => ['a', 'b', 'c', 'd'].map((field, index) => ({
  field,
  answered: index < count,
  verdict: index < count ? '読めた' : '読めない',
}));

// breakdownに旧20点が残っていても、盤面は回答観測だけを見る。
const full = board.cellState({ fields: fields(4), breakdown: { a: 0 } });
const none = board.cellState({
  fields: fields(0),
  breakdown: { a: 20, b: 20, c: 20, d: 20 },
});
const part = board.cellState({ fields: fields(2), breakdown: {} });
assert.equal(full.got, 4);
assert.equal(full.label, '4/4');
assert.equal(none.got, 0);
assert.equal(none.label, '0/4');
assert.equal(part.got, 2);
assert.equal(part.label, '2/4');

console.log('dashboard: 15 PASS');
