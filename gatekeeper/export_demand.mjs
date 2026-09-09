// 本番の門番から「AIが何を探しに来て、取れたか／取れずに帰ったか」の集計を取り、
// 公開データ（web/data/demand.json）へ書き出す。
//
//   実行: DEMAND_URL=https://<門番>/_aidoku/demand DEMAND_TOKEN=<鍵> node gatekeeper/export_demand.mjs
//
// 経路の考え方（plans/demand-real-data.md）:
// - 画面から直接KVは読まない。集計口は鍵つきのまま（質問文の選別が無いため）
// - このエクスポートは**手で回す**（点数と同じ）。書き出しはPR経由＝コミット前に人が見る。
//   質問文（looking_for）が入り始めたら、公開してよい中身かをそこで確かめる
// - 見本（is_sample）を実データとして書き出すことは絶対にしない（検証して拒否する）
import { writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = join(HERE, '..', 'web', 'data', 'demand.json');

// 書き出してよいデータかの検査。だめな理由を全部返す（1つずつ突き返さない）。
export function validateExport(data) {
  const problems = [];
  if (!data || typeof data !== 'object') return ['JSONが読めない'];
  if (data.is_sample) problems.push('is_sample が付いている＝見本。実データとして書き出せない');
  if (!data.totals || typeof data.totals.asks !== 'number') problems.push('totals.asks が無い（集計の形ではない）');
  if (!data.generated_at) problems.push('generated_at が無い（いつの集計か言えない）');
  if (!Array.isArray(data.by_agent)) problems.push('by_agent が無い');
  return problems;
}

async function main() {
  const url = process.env.DEMAND_URL;
  const token = process.env.DEMAND_TOKEN;
  if (!url || !token) {
    console.error('★DEMAND_URL と DEMAND_TOKEN を環境変数で渡すこと。例:');
    console.error('  DEMAND_URL=https://<門番>/_aidoku/demand DEMAND_TOKEN=<鍵> node gatekeeper/export_demand.mjs');
    process.exitCode = 1;
    return;
  }

  const res = await fetch(url, { headers: { authorization: `Bearer ${token}` } });
  if (!res.ok) {
    console.error(`★集計口が ${res.status} を返した。URLと鍵を確認する。`);
    process.exitCode = 1;
    return;
  }
  const data = await res.json();

  const problems = validateExport(data);
  if (problems.length) {
    console.error(`★書き出せない: ${problems.join(' / ')}`);
    process.exitCode = 1;
    return;
  }

  await writeFile(OUT, `${JSON.stringify(data, null, 2)}\n`);
  const t = data.totals;
  console.log(`書き出した: web/data/demand.json（来訪 ${t.asks} / 取れずに帰った ${t.unanswered} / 検証済みエージェント ${t.agents}）`);
  console.log('コミットする前に、質問文（looking_for）に公開してはいけないものが無いか目で見る。');
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await main();
}
