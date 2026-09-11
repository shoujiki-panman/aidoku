import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const published = JSON.parse(await readFile(new URL('./data/demand.json', import.meta.url), 'utf8'));
for (const row of published.all) {
  if (!row.looking_for?.trim()) {
    assert.equal(row.answered_count, 0);
    assert.equal(row.unanswered_count, 0);
  }
}
const data = { totals: { asks: 14, answered: 0, unanswered: 0, undetermined: 5, unverified: 9 },
  by_agent: [{ agent: 'https://chatgpt.com', asks: 5, answered: 0, unanswered: 0 }],
  all: [{ authority: 'example.com', path: '/app.js', looking_for: null, count: 14,
    answered_count: 0, unanswered_count: 0, by_agent: { 'https://chatgpt.com': { asks: 5 } } }],
  unanswered: [], coverage: {}, generated_at: '2026-09-09T00:42:25.647Z' };
const code = await readFile(new URL('./assets/demand.js', import.meta.url), 'utf8');
const nodes = new Map();
const get = (id) => {
  if (!nodes.has(id)) nodes.set(id, { textContent: '', innerHTML: '', dataset: {}, remove() {} });
  return nodes.get(id);
};
vm.runInNewContext(code, {
  document: { getElementById: get, querySelector: get },
  location: { search: '' }, URLSearchParams, Intl, Date, console,
  fetch: async () => ({ ok: true, json: async () => data }),
});
await new Promise((resolve) => setImmediate(resolve));
assert.equal(data.totals.asks, 14);
assert.equal(data.totals.unanswered, 0);
assert.equal(data.totals.undetermined, 5);
assert.equal(get('real-visits').textContent, '5');
assert.match(get('totals').innerHTML, /判定対象外/);
assert.match(get('totals-note').innerHTML, /判定できる質問はまだありません/);
assert.doesNotMatch(get('agents').innerHTML, /手ぶら|1種類のこと/);
assert.equal(data.unanswered.length, 0);
console.log('PASS demand: corrected snapshot and unknown-query rendering');
