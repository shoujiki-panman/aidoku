// 担当者の確認フォーム（assets/verify-form.mjs）のテスト。
// 実行: node web/test_verify_form.mjs
//
// 確かめたいことは1つ。
// 画面の「内容確認 → 公開 → AIが取得した結果」が、門番の実物と同じ判定で作られるか。
//   - 入力から、gatekeeper/verified/ にそのまま置ける記録ファイルができるか
//   - 既存の記録に重ねると、触った項目だけ version が上がるか
//   - プレビューが門番の実物（decideAsk / publishInto）で作られ、出典・確認者・版が出るか
import {
  FIELD_MAP, FIELD_QUESTION, checkEntry, mergeRecord, previewAsk, recordFileName, skeletonAnswer,
} from './assets/verify-form.mjs';
import { KNOWN_FIELDS } from '../gatekeeper/demand.mjs';

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

// fix.js の FIELDS と同じ表記（ここがずれると画面の項目名が記録に変換できない）
const LABELS = ['必要書類', '窓口/オンライン可否', '期限', '手数料'];

const cell = {
  muniId: 'setagaya',
  muniName: '世田谷区',
  procId: 'tennyu',
  procName: '転入届',
  url: 'https://www.city.setagaya.lg.jp/kurashi/kosekijuumin/11531.html',
  generatedAt: '2026-08-31',
};

const NOW = new Date('2026-09-09T12:00:00+09:00');

console.log('テスト:');

// 画面の項目名 → 記録の項目名
check('画面の4項目が全部変換できる', LABELS.every((l) => KNOWN_FIELDS.includes(FIELD_MAP[l])), JSON.stringify(FIELD_MAP));
check('プレビューの聞き方が4項目そろっている', KNOWN_FIELDS.every((f) => FIELD_QUESTION[f]));

// 入力チェック（手元だけ・LLMなし）
check('値と確認者があれば通る', checkEntry({ field: '手数料', value: '無料', verifiedBy: '戸籍住民課' }).ok);
check('値が空だと通らない', !checkEntry({ field: '手数料', value: ' ', verifiedBy: '戸籍住民課' }).ok);
check('確認者が空だと通らない', !checkEntry({ field: '手数料', value: '無料', verifiedBy: '' }).ok);
check('不明な項目名は通らない', !checkEntry({ field: '営業時間', value: '9時', verifiedBy: '課' }).ok);

// 新規の記録
const entries = [{ field: '手数料', value: ' 無料 ', conditions: '窓口で届け出る場合', verifiedBy: '戸籍住民課' }];
const record = mergeRecord({ existing: null, cell, entries, now: NOW });
{
  const fee = record.fields.fee;
  check('記録が verified/ の形になる',
    record.municipality_id === 'setagaya' && record.procedure_id === 'tennyu' && record.source === cell.url,
    JSON.stringify(record).slice(0, 160));
  check('  └ 値は前後の空白を落として入る', fee.value === '無料');
  check('  └ 第1版・published・確認日と公開時刻つき',
    fee.version === 1 && fee.status === 'published' && fee.verified_at === '2026-09-09' && !!Date.parse(fee.published_at),
    JSON.stringify(fee));
  // 確認日は日本の日付。UTCに畳むと深夜0時台（例: 0:30 JST = 前日15:30 UTC）に1日ずれる
  const midnight = mergeRecord({ existing: null, cell, entries, now: new Date('2026-09-09T00:30:00+09:00') });
  check('  └ 深夜0時台でも確認日は日本の日付', midnight.fields.fee.verified_at === '2026-09-09',
    midnight.fields.fee.verified_at);
  check('  └ ファイル名は <区>-<手続き>.json', recordFileName(record) === 'setagaya-tennyu.json');
}

// 既存の記録に重ねる → 触った項目だけ version が上がる
{
  const existing = structuredClone(record);
  existing.fields.deadline = { value: '14日以内', verified_by: '課', verified_at: '2026-09-01', published_at: '2026-09-01T00:00:00Z', version: 3, status: 'published' };
  const merged = mergeRecord({ existing, cell, entries, now: NOW });
  check('触った項目だけ version +1', merged.fields.fee.version === 2, JSON.stringify(merged.fields.fee));
  check('  └ 触っていない項目はそのまま', merged.fields.deadline.version === 3 && merged.fields.deadline.value === '14日以内');
}

// 実測がまだ無い手続きの骨組み（値は作らない）
const skeleton = skeletonAnswer(cell);
check('骨組みは全項目 null（値を作らない）', Object.values(skeleton.fields).every((v) => v === null), JSON.stringify(skeleton.fields));

// プレビュー＝門番の実物の判定
{
  const p = previewAsk({ measured: skeleton, record, field: '手数料' });
  const body = p.decided.body;
  const v = body.results?.[0]?.verified_fields?.fee;
  check('公開後のプレビューが answer になる', body._meta?.response_type === 'answer', JSON.stringify(body).slice(0, 160));
  check('  └ 確認済みが別の束で、出典・確認者・版つき',
    v?.value === '無料' && v?.verified_by === '戸籍住民課' && v?.version === 1 && v?.source === cell.url,
    JSON.stringify(v));
  check('  └ 実測は null のまま（混ぜない）', body.results?.[0]?.fields?.fee === null);

  const q = previewAsk({ measured: skeleton, record, field: '期限' });
  check('確認していない項目は failure のまま', q.decided.body._meta?.response_type === 'failure', JSON.stringify(q.decided.body).slice(0, 120));
}

console.log(`\n結果: ${pass} PASS / ${fail} FAIL`);
if (fail > 0) process.exit(1);
