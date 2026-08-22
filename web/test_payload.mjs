// 「AIに渡して調べる」がURLに載るかを、23区ぶん全部で確かめる。
//
// ★上限を超えると、この仕組みは黙ってクリップボード経由に落ちる。
//   画面は同じに見えるのに、**本人が手で貼らないとAIが動かない**状態になる。
//   区を1つ足したり、指示文を1行足したりで越えるので、機械で見張る。
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const read = (f) => readFileSync(join(here, f), 'utf8');
const data = (f) => JSON.parse(read(join('data', f)));

let pass = 0, fail = 0;
const ok = (name, cond, detail) => {
  if (cond) { pass++; return; }
  fail++;
  console.log(`FAIL ${name}${detail ? ` — ${detail}` : ''}`);
};

// 上限は index.html の data-max-url-chars（未指定なら本体の既定 8000）
const tag = read('index.html').match(/<script[^>]*ask-ai-button\.js[\s\S]*?><\/script>/)[0];
const limit = Number((tag.match(/data-max-url-chars="(\d+)"/) || [])[1] || 8000);
ok('上限を読めた', limit > 0, String(limit));

// 指示文の長さは本体から読む。ここが伸びたら本文の余地が減る
const lib = read('ask-ai-button.js');
const block = lib.match(/procedure: \{[\s\S]*?prompt: \[([\s\S]*?)\]\.join/);
ok('procedure の指示文がある', !!block);
const head = block[1].split('\n').map((l) => (l.match(/"(.*)"/) || [, ''])[1]).join('\n');
const headCost = encodeURIComponent(head).length;
ok('指示文が上限の7割を超えていない', headCost < limit * 0.7, `${headCost} / ${limit}`);

// 本文を app.js と同じ形で組み立てて、23区ぶん測る
const FIELDS = ['必要書類', '窓口/オンライン可否', '期限', '手数料'];
const BASE = 'https://shoujiki-panman.github.io/aidoku/web/';
const tops = new Map(data('municipalities.json').municipalities.map((m) => [m.id, m]));
// AIが選ばなかった扉のURLも渡すようになったので、その分も測る
const missed = new Map(data('journeys.json').journeys
  .filter((j) => j.blame === 'ours' && j.missed_with_strong_word.length)
  .map((j) => [`${j.municipality_id}/${j.procedure_id}`, j.missed_with_strong_word[0].url]));
const byWard = new Map();
for (const p of data('procedures.json').procedures) {
  for (const m of data(p.file).municipalities) {
    if (!byWard.has(m.id)) byWard.set(m.id, []);
    byWard.get(m.id).push({ proc: p.name, url: m.page_url || '', bd: m.breakdown || {},
      near: missed.get(`${m.id}/${p.id}`) || '' });
  }
}
ok('23区ぶんある', byWard.size === 23, String(byWard.size));

const over = [];
let worst = 0, worstName = '';
for (const [id, rows] of byWard) {
  const t = tops.get(id) || {};
  const lines = rows.map((r) => {
    const got = FIELDS.filter((k) => (r.bd[k] ?? 0) >= 20);
    const miss = FIELDS.filter((k) => (r.bd[k] ?? 0) < 20);
    return `- ${r.proc}｜区の公式ページ ${r.url}｜読み取れた: ${got.join('・') || 'なし'}`
      + `｜読み取れなかった: ${miss.join('・') || 'なし'}`
      + (r.near ? `｜同じ画面に出ていた別の入口（未確認）: ${r.near}` : '');
  }).join('\n');
  const body = `# AI読の実測\n対象: ${t.name || ''}（区の公式サイト ${t.top_url || ''}）\n${lines}\n`
    + '「読み取れなかった」＝その項目が区のページに書かれていない。埋めないこと。\n'
    + `項目ごとの直し方と見込み点は、次のデータにあります。\n`
    + `- ${BASE}data/index.json — 目次\n- ${BASE}skill/SKILL.md — 使い方\n`;
  const total = headCost + encodeURIComponent(body).length;
  if (total > worst) { worst = total; worstName = t.name || id; }
  if (total > limit) over.push(`${t.name || id}=${total}`);
}
ok('全区がURLに載る', over.length === 0, over.join(' '));
// 余裕が無いと、次に1行足したときに黙って落ちる
ok('余裕が1割以上ある', worst < limit * 0.9, `最大 ${worstName} ${worst} / 上限 ${limit}`);
console.log(`  （最大 ${worstName} ${worst} / 上限 ${limit}）`);

console.log(`${pass} PASS / ${fail} FAIL`);
process.exit(fail ? 1 : 0);
