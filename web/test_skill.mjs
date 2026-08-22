// SKILL.md が「実際にあるデータ」だけを指しているかを見る。
// スキルは AI に読ませる指示書なので、書いてあるファイル名やフィールド名が
// 1つでもズレていると、AI は黙って推測に戻る。そこを機械で止める。
import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const skill = readFileSync(join(here, 'skill/SKILL.md'), 'utf8');
const dataDir = join(here, 'data');
const load = (f) => JSON.parse(readFileSync(join(dataDir, f), 'utf8'));

let pass = 0, fail = 0;
const ok = (name, cond, detail) => {
  if (cond) { pass++; return; }
  fail++;
  console.log(`FAIL ${name}${detail ? ` — ${detail}` : ''}`);
};

// --- frontmatter ---
const fm = skill.match(/^---\n([\s\S]*?)\n---\n/);
ok('frontmatter がある', !!fm);
if (fm) {
  ok('name がある', /^name: \S/m.test(fm[1]));
  const desc = fm[1].match(/^description: (.+)$/m);
  ok('description がある', !!desc);
  // description は呼び出すかどうかの判断材料。短すぎると呼ばれない
  ok('description が具体的', !!desc && desc[1].length >= 40, desc && `${desc[1].length}字`);
}

// --- 手続きIDが procedures.json と合っているか ---
const procIds = load('procedures.json').procedures.map((p) => p.id);
const inSkill = [...skill.matchAll(/`(tennyu|jidouteate|sodaigomi)`/g)].map((m) => m[1]);
for (const id of procIds) ok(`手続き ${id} がスキルに載っている`, inSkill.includes(id));
for (const id of new Set(inSkill)) ok(`スキルの ${id} は実在する`, procIds.includes(id));

// --- 参照しているデータファイルが実在するか ---
const files = new Set([...skill.matchAll(/`?([a-z0-9-]+\.json)`?/g)].map((m) => m[1]));
for (const f of files) {
  const real = f.replace('<procId>', 'tennyu').replace('scores-.json', 'scores-tennyu.json');
  ok(`${f} が実在する`, existsSync(join(dataDir, real)), real);
}

// --- スキルが読ませるフィールドが本当にあるか ---
const one = load('scores-tennyu.json');
ok('generated_at がある', typeof one.generated_at === 'string');
const m0 = one.municipalities[0];
for (const k of ['name', 'page_url', 'breakdown', 'fields']) {
  ok(`municipalities[].${k} がある`, k in m0);
}
ok('fields[].verdict がある', 'verdict' in m0.fields[0]);
// スキルは配点を表で説明している。実データとズレたら指示が嘘になる
const four = ['必要書類', '窓口/オンライン可否', '期限', '手数料'];
const fourPts = new Set(one.municipalities.flatMap((m) => four.map((k) => m.breakdown[k])));
ok('4項目は 0 か 20 の2値', [...fourPts].every((v) => v === 0 || v === 20), [...fourPts].join(','));
// オンライン明示だけ 10（曖昧）を取りうる。スキルはそれを名指しで書いている
const onlinePts = new Set(one.municipalities.map((m) => m.breakdown['オンライン明示']));
ok('オンライン明示は 0/10/20', [...onlinePts].every((v) => [0, 10, 20].includes(v)), [...onlinePts].join(','));
ok('スキルが曖昧=10 を説明している', /オンライン明示[\s\S]{0,200}10 = 曖昧/.test(skill));
// verdict と点が食い違っていないか（スキルはこの対応を前提に書いている）
const bad = one.municipalities.flatMap((m) =>
  m.fields.filter((f) => (f.verdict === '読めた') !== (m.breakdown[f.field] === 20))
    .map((f) => `${m.name}/${f.field}`));
ok('verdict と点が一致', bad.length === 0, bad.slice(0, 3).join(' '));

// --- barriers.json の引き方が実際に通るか ---
const bars = load('barriers.json').barriers;
for (const k of ['municipality', 'procedure', 'failure']) {
  ok(`barriers[].${k} がある`, k in bars[0]);
}
ok('failure.summary がある', 'summary' in bars[0].failure);
// スキルは municipality + procedure で引けと書いている。名前が突き合うか
const names = new Set(one.municipalities.map((m) => m.name));
const orphan = bars.filter((b) => b.procedure === '転入届' && !names.has(b.municipality));
ok('barriers の区名が実測と突き合う', orphan.length === 0, orphan.map((b) => b.municipality).join(','));

// --- 出典URLが Pages の実体を指しているか ---
const urls = [...skill.matchAll(/https:\/\/shoujiki-panman\.github\.io\/aidoku\/([^\s`)>]*)/g)]
  .map((m) => m[1]).filter((p) => p.endsWith('.json'));
for (const u of urls) ok(`公開URL ${u} が実体を持つ`, existsSync(join(here, u)), u);

// --- 推測を止める指示が消えていないか（このスキルの存在理由） ---
ok('推測を禁じる記述がある', /埋めない|推測/.test(skill));
ok('公式発表ではないと書いてある', /公式発表ではない/.test(skill));
ok('測った日を言えと書いてある', /測った日|generated_at/.test(skill));

console.log(`${pass} PASS / ${fail} FAIL`);
process.exit(fail ? 1 : 0);
