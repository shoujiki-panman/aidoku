// 門番が検証済みエージェントに返す「整った答え」を、23区の実測から作る。
//
//   extractor/out/extract_*_tennyu.json  →  gatekeeper/answers/*.json（KVに入れる形）
//
// 答えの中身は実測値そのまま。ここで文章を作らない（AIが役所の情報を作らない設計）。
// 読めなかった項目は null にして「答えが無い」ことを正直に返す。
//
// 実行: node gatekeeper/build_answers.mjs
import { readdir, readFile, writeFile, mkdir } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = join(HERE, '..');
const SRC = join(REPO, 'extractor', 'out');
const OUT = join(HERE, 'answers');

const FIELDS = {
  必要書類: 'required_documents',
  窓口オンライン可否: 'how_to_apply',
  期限: 'deadline',
  手数料: 'fee',
};

const files = (await readdir(SRC)).filter((f) => /^extract_.*_tennyu\.json$/.test(f));
await mkdir(OUT, { recursive: true });

const index = [];
for (const f of files) {
  const d = JSON.parse(await readFile(join(SRC, f), 'utf-8'));
  const url = d.page?.url;
  if (!url) continue;
  const { host, pathname } = new URL(url);

  const answer = {
    procedure: d.procedure ?? '転入届',
    municipality: d.municipality ?? '',
    source: url,
    measured_at: '2026-07-22',
    // 実測で読み取れた実文のみ。読めなかった項目は null（答えが無いことを隠さない）
    fields: Object.fromEntries(
      Object.entries(FIELDS).map(([jp, en]) => {
        const it = d.items?.[jp] ?? {};
        return [en, it.found ? (it.value ?? null) : null];
      }),
    ),
    online_clarity: d.online_clarity ?? '記載なし',
    note: 'デジタル庁OSS「源内」のAIアプリ仕様に準拠した第三者調査（AI読）による実測値です。行政機関の公式発表ではありません。',
  };

  const key = `${host}${pathname}`;
  await writeFile(join(OUT, `${d.municipality_id}.json`), JSON.stringify(answer, null, 2) + '\n');
  index.push({ key, file: `${d.municipality_id}.json`, municipality: d.municipality });
}

index.sort((a, b) => a.key.localeCompare(b.key));
await writeFile(join(OUT, '_index.json'), JSON.stringify(index, null, 2) + '\n');

const answered = index.length;
console.log(`${answered}件の答えを ${OUT} に書き出した`);
console.log('KVへの投入（招待が届いてから）:');
console.log('  for f in gatekeeper/answers/*.json; do');
console.log('    key=$(node -e "...")  # _index.json のキーを使う');
console.log('    npx wrangler kv key put --binding=ANSWERS "$key" --path "$f" --remote');
console.log('  done');
