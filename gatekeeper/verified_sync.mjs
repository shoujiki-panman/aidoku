// 担当者が確認した情報（gatekeeper/verified/）を、門番の答え（answers/*.json）へ反映する。
//
// やることは2つ。順番も固定（差し戻しを先にやらないと、変わったページの古い値を公開してしまう）:
//   ① 差し戻し: 見張り（web/data/site-status.json）が「公開後に元ページが変わった／消えた」と
//      言っていたら、その項目を published → needs_review に戻す（verified/*.json を書き換える）。
//      確認案件に戻った項目は、担当者が見直して再公開するまで門番からは出ない。
//   ② 反映: published の項目だけを answers/*.json の verified_fields に書き込む。
//      実測（fields）は1文字も触らない。実測と確認済みは別の束のまま門番が両方返す。
//      どの記録にも紐づかない verified_fields が answers に残っていたら消す（孤児を配信し続けない）。
//
// 再公開の手順（担当者・運用者）:
//   verified/<区>-<手続き>.json の該当項目を直す → status を "published" に戻し、
//   version を +1、verified_at / published_at を今に更新 → このスクリプトを再実行。
//
// ★見張りの changed はラッチ式。見張りは測定時のキャッシュと比べるだけで基準を更新しない
//   （測り直しは別の工程）ので、一度変わったページは測り直すまで毎朝 changed:true が出続ける。
//   そのため「検出済みの変化（review_detected_at）より後に再公開された項目」は戻さない。
//   毎朝戻すと、担当者の再公開が翌朝黙って取り消される。測り直しで基準が更新されて
//   changed:false に戻ったら検出の印を消す＝その後の changed は新しい変化として扱う。
//
// 判定の中身は verified_core.mjs（純粋関数）。担当者画面のプレビューも同じものを使う。
//
// 実行: node gatekeeper/verified_sync.mjs
//   （KVへ上げるのは従来どおり put_answers.sh。これはリポジトリ内の answers/ を作るまで）
//   差し戻しの判定ができない・反映先が見つからない等、公開の安全が言えないときは
//   何も書かずに（または書けた分を報告して）終了コード1で落ちる。黙って成功にしない。
import { readdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { KNOWN_FIELDS } from './demand.mjs';
import { hasPublished, publishInto, reviewAgainstWatch, unknownFields, urlKey } from './verified_core.mjs';

// 既存の呼び出し側（テスト等）が verified_sync から引き続き import できるように再輸出する
export { parseTime, urlKey, unknownFields, reviewAgainstWatch, publishInto } from './verified_core.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const VERIFIED_DIR = join(HERE, 'verified');
const ANSWERS_DIR = join(HERE, 'answers');
const SITE_STATUS = join(HERE, '..', 'web', 'data', 'site-status.json');

async function readJson(path) {
  return JSON.parse(await readFile(path, 'utf-8'));
}

const writeJson = (path, obj) => writeFile(path, `${JSON.stringify(obj, null, 2)}\n`);

async function main() {
  let files = [];
  try {
    files = (await readdir(VERIFIED_DIR)).filter((f) => f.endsWith('.json'));
  } catch {
    console.log('verified/ がまだ無い。反映するものなし。');
    return;
  }

  // 見張りが読めなければ差し戻しの判定ができない＝公開の安全が言えない。
  // 冒頭コメントの「差し戻しが先」を守り、何も書かずに落ちる。
  let statusItems;
  try {
    statusItems = (await readJson(SITE_STATUS)).items ?? [];
  } catch {
    console.error('★見張りの結果（web/data/site-status.json）が読めない。差し戻し判定ができないので、何も反映せず終了する。');
    process.exitCode = 1;
    return;
  }

  const index = await readJson(join(ANSWERS_DIR, '_index.json'));
  // record が紐づいた answers ファイル。ここに無いのに verified_fields を持つ answers は孤児
  const claimed = new Set();

  for (const f of files) {
    const path = join(VERIFIED_DIR, f);
    const record = await readJson(path);

    const bad = unknownFields(record);
    if (bad.length) {
      console.error(`★語彙に無い項目名: ${f} → ${bad.join(', ')}（公開できるのは ${KNOWN_FIELDS.join(' / ')}）。この項目は公開しない。`);
      process.exitCode = 1;
    }

    const { watched, demoted, cleared } = reviewAgainstWatch(record, statusItems);
    if (demoted.length || cleared.length) {
      await writeJson(path, record);
      if (demoted.length) console.log(`確認案件に戻した: ${f} → ${demoted.join(', ')}（見張りが変化を検出）`);
      if (cleared.length) console.log(`検出の印を消した: ${f} → ${cleared.join(', ')}（測り直しで基準が更新された）`);
    }
    if (!watched && hasPublished(record)) {
      // 見張りに相手がいない記録は、元ページが消えても永遠に戻せない。公開を止めて直させる
      console.error(`★見張りに相手がいない: ${f}（source: ${record.source ?? '無し'}）。公開中の項目があるのに変化を検出できない。`);
      process.exitCode = 1;
    }

    const key = urlKey(record.source);
    if (!key) {
      console.error(`★出典URLが読めない: ${f}（source: ${record.source ?? '無し'}）。飛ばす。`);
      if (hasPublished(record)) process.exitCode = 1;
      continue;
    }
    const row = index.find((r) => r.key === key);
    if (!row) {
      console.error(`★answers に相手がいない: ${f}（key: ${key}）。飛ばす。`);
      if (hasPublished(record)) process.exitCode = 1;
      continue;
    }

    claimed.add(row.file);
    const answerPath = join(ANSWERS_DIR, row.file);
    const answer = publishInto(await readJson(answerPath), record);
    await writeJson(answerPath, answer);
    const n = Object.keys(answer.verified_fields ?? {}).length;
    console.log(`反映: ${row.file} ← ${f}（公開中 ${n} 項目）`);
  }

  // 孤児の掃除。build_answers.mjs は前版の verified_fields を持ち越すので、
  // 記録の source が変わった・記録が消えた等で紐が切れた answers に古い確認済みが残り得る。
  // どの記録にも紐づかない verified_fields は配信し続けず、ここで消す。
  for (const row of index) {
    if (claimed.has(row.file)) continue;
    const answerPath = join(ANSWERS_DIR, row.file);
    let answer;
    try {
      answer = await readJson(answerPath);
    } catch {
      continue;
    }
    if (answer.verified_fields) {
      delete answer.verified_fields;
      await writeJson(answerPath, answer);
      console.log(`孤児を消した: ${row.file}（どの verified/ 記録にも紐づかない verified_fields）`);
    }
  }

  if (process.exitCode === 1) {
    console.error('★上の問題を直してから再実行する。KVへは上げない。');
  } else {
    console.log('完了。KVへ上げるには gatekeeper/put_answers.sh を実行する。');
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await main();
}
