// 見張り状態の画面表示のテスト。DOM無しで回る（web/assets/site-status.js のみ）。
// 実行: node web/test_site_status.mjs
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const { describe, formatCheckedAt } = require('./assets/site-status.js');

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

const item = (o) => ({
  municipality: '港区', procedure: '転入届', url: 'https://example.lg.jp/a.html',
  changed: false, gone: false, reason: '304', ...o,
});

const report = (items, summary = {}) => ({
  checked_at: '2026-08-17T00:00:00+00:00',
  summary: { total: items.length, unchanged: items.filter((i) => i.changed === false).length, ...summary },
  items,
});

// --- level の決まり方（重い順に勝つ） ---

check('全部変わっていなければ ok',
  describe(report([item({}), item({})])).level === 'ok');

check('変わったページがあれば changed',
  describe(report([item({}), item({ changed: true })])).level === 'changed');

check('消えたページがあれば gone（変わったページより優先）',
  describe(report([item({ changed: true }), item({ changed: true, gone: true })])).level === 'gone');

check('判定できないページだけなら unknown',
  describe(report([item({}), item({ changed: null })])).level === 'unknown');

check('消えたページは変わったページより先に出す',
  describe(report([item({ changed: true, gone: true })])).level === 'gone');

// --- 文言 ---

{
  const d = describe(report([item({ changed: true })]));
  check('変わったときは「悪くなった意味ではない」と書く', d.detail.includes('悪くなった'));
  check('変わったときは測り直しが必要と書く', d.detail.includes('測り直し'));
}

{
  const d = describe(report([item({ changed: true, gone: true })]));
  check('消えたときは根拠URLが切れたと書く', d.detail.includes('根拠URL'));
  check('消えたときの見出しに件数が入る', d.headline.includes('1ページが無くなりました'));
}

check('変化なしのときは詳細を出さない（静かにする）',
  describe(report([item({})])).detail === '');

// --- データが無いとき（数字を作らない） ---

for (const [name, value] of [['null', null], ['undefined', undefined],
  ['配列でないitems', { items: {} }], ['itemsが無い', { summary: {} }],
  ['文字列', 'まだ']]) {
  const d = describe(value);
  check(`${name} なら「まだ確認していない」`, d.level === 'none' && d.items.length === 0);
}

check('summaryが壊れていても落ちない',
  describe({ checked_at: 'x', summary: 'こわれた', items: [item({})] }).level === 'ok');

check('itemsにnullが混ざっても落ちない',
  describe({ checked_at: 'x', summary: {}, items: [null, item({ changed: true })] }).level === 'changed');

// --- 一覧に出すもの ---

{
  const d = describe(report([item({ changed: true, gone: true, municipality: '消区' }),
    item({ changed: true, municipality: '変区' }), item({})]));
  check('消えた＋変わったの両方を一覧に出す', d.items.length === 2);
  check('消えたページを先頭にする', d.items[0].municipality === '消区');
}

check('変化なしのときは一覧を空にする',
  describe(report([item({}), item({})])).items.length === 0);

// --- 確認時刻の見せ方 ---

const now = new Date('2026-08-17T12:00:00Z');
check('1時間以内は分で出す',
  formatCheckedAt('2026-08-17T11:30:00Z', now) === '30分前');
check('1日以内は時間で出す',
  formatCheckedAt('2026-08-17T06:00:00Z', now) === '6時間前');
check('1日以上は日で出す',
  formatCheckedAt('2026-08-15T12:00:00Z', now) === '2日前');
check('不正な値は空文字（推測しない）',
  formatCheckedAt('こわれた', now) === '' && formatCheckedAt(null, now) === '' &&
  formatCheckedAt('', now) === '');
check('未来の時刻は「〜前」と言わない',
  !formatCheckedAt('2026-08-18T12:00:00Z', now).includes('前'));

// --- 実データとの突き合わせ ---

const here = dirname(fileURLToPath(import.meta.url));
try {
  const real = JSON.parse(readFileSync(join(here, 'data', 'site-status.json'), 'utf8'));
  const d = describe(real);
  check('実データ site-status.json を読める', ['ok', 'changed', 'gone', 'unknown'].includes(d.level),
    `level=${d.level}`);
  check('実データから確認時刻を出せる', typeof d.checkedAt === 'string' && d.checkedAt.length > 0);
} catch (e) {
  check('実データ site-status.json を読める', false, e.message);
}

console.log(`\n${pass} PASS / ${fail} FAIL`);
if (fail > 0) process.exit(1);
