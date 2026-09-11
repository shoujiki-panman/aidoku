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
import { normalizeDemandSnapshot } from './demand.mjs';

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
  if (!Array.isArray(data.all)) problems.push('all が無い');
  return problems;
}

export async function writeDemandFiles(data, out = OUT) {
  const problems = validateExport(data);
  if (problems.length) throw new Error(problems.join(' / '));
  const normalized = normalizeDemandSnapshot(data);
  normalized.note = '署名つきアクセスの集計です。署名なしは記録対象外です。' +
    'answered/unansweredは窓口側の対応情報の有無で、AIの最終回答や手続完了の成否ではありません。' +
    '質問のないアクセスはundetermined（判定対象外）に訂正しています。';
  const csvCell = (v) => `"${String(v ?? '').replaceAll('"', '""')}"`;
  const csv = [['サイト', 'ページ', '質問', 'アクセス回数', '対応情報あり', '対応情報なし', '最初', '最後'],
    ...normalized.all.map((r) => [r.authority, r.path, r.looking_for, r.count, r.answered_count, r.unanswered_count, r.first_seen, r.last_seen])]
    .map((row) => row.map(csvCell).join(',')).join('\n');
  const t = normalized.totals;
  const summary = `AI読 署名つきアクセスの集計\n集計日時: ${normalized.generated_at}\n` +
    `アクセス: ${t.asks}\n対応情報あり: ${t.answered}\n対応情報なし: ${t.unanswered}\n` +
    `判定対象外: ${t.undetermined ?? 0}\n署名検証失敗: ${t.unverified ?? 0}\n${normalized.note}\n`;
  await writeFile(out, `${JSON.stringify(normalized, null, 2)}\n`);
  await writeFile(join(dirname(out), 'demand.csv'), `${csv}\n`);
  await writeFile(join(dirname(out), 'demand-summary.txt'), summary);
  return normalized;
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

  const normalized = await writeDemandFiles(data);
  const t = normalized.totals;
  console.log(`書き出した: web/data/demand.json・CSV・要約（アクセス ${t.asks} / 対応情報なし ${t.unanswered} / 検証済みエージェント ${t.agents}）`);
  console.log('コミットする前に、質問文（looking_for）に公開してはいけないものが無いか目で見る。');
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await main();
}
