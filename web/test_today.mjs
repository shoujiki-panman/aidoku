// 「今日直す1件」（assets/today.mjs）のテスト。
// 実行: node web/test_today.mjs
//
// 確かめたいことは1つ。
// 見張りの「変わった43件」が数字のままではなく、状態で分かれて優先度順の1件になるか。
//   - 優先度: 確認案件 > 要再確認 > 欠落候補 > 未確認
//   - 未確認は欠落候補と混ざらない（「区が書いていない」と言わないため）
//   - 1セル1件。いちばん重い状態だけが出る
import { STATE, buildQueue, countByState } from './assets/today.mjs';

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

const FULL = { 必要書類: 20, '窓口/オンライン可否': 20, 期限: 20, 手数料: 20 };
const cell = (muniId, procId, over = {}) => ({
  muniId, procId, muniName: `${muniId}区`, procName: procId,
  url: `https://example.com/${muniId}/${procId}.html`,
  breakdown: { ...FULL }, pageStatus: 'facts_found', lgCode: `13${muniId.length}00`, ...over,
});

console.log('テスト:');

// 優先度の全段が同時にあるとき、順番どおりに並ぶ
{
  const cells = [
    cell('a', 'tennyu', { breakdown: { ...FULL, 手数料: 0 } }),               // 欠落1
    cell('b', 'tennyu', { breakdown: { 必要書類: 0, '窓口/オンライン可否': 0, 期限: 0, 手数料: 0 } }), // 欠落4
    cell('c', 'tennyu'),                                                       // 欠落なし・見張りが変化
    cell('d', 'tennyu', { breakdown: { ...FULL, 期限: 0 } }),                  // 確認案件
    cell('e', 'tennyu', { pageStatus: 'target_unconfirmed', breakdown: { 必要書類: 0, '窓口/オンライン可否': 0, 期限: 0, 手数料: 0 } }), // 未確認
  ];
  const statusItems = [
    { municipality_id: 'c', procedure_id: 'tennyu', changed: true, gone: false, checked_at: '2026-09-08T00:00:00+0000' },
  ];
  const verifiedRecords = [
    { municipality_id: 'd', procedure_id: 'tennyu', fields: { deadline: { status: 'needs_review', review_reason: '元ページが変わった' } } },
  ];
  const q = buildQueue({ cells, statusItems, verifiedRecords });

  check('先頭は確認案件（担当者の確認が宙に浮いている）', q[0]?.state === STATE.needsReview && q[0]?.cell.muniId === 'd',
    JSON.stringify(q.map((x) => [x.cell.muniId, x.state])));
  check('  └ 理由に項目名と配信停止が書かれる', q[0]?.reason.includes('期限') && q[0]?.reason.includes('配信が止まっています'), q[0]?.reason);
  check('2番目は要再確認（欠落が無くても、変わったら測り直し対象）', q[1]?.state === STATE.recheck && q[1]?.cell.muniId === 'c');
  check('  └ 「悪化したとは限らない」が理由に入る', q[1]?.reason.includes('悪化したとは限りません'), q[1]?.reason);
  check('欠落候補は多い順（4つ → 1つ）', q[2]?.cell.muniId === 'b' && q[3]?.cell.muniId === 'a',
    JSON.stringify(q.map((x) => x.cell.muniId)));
  check('未確認は最後（欠落候補と混ぜない）', q[4]?.state === STATE.unconfirmed && q[4]?.cell.muniId === 'e');
  check('  └ 「書いていない」とは言えない旨が理由に入る', q[4]?.reason.includes('書いていない'), q[4]?.reason);
  check('全項目そろい・変化なしのセルは課題に出ない', !q.some((x) => x.cell.muniId === 'c' && x.state !== STATE.recheck) && q.length === 5);

  const counts = countByState(q);
  check('内訳が数えられる', counts[STATE.needsReview] === 1 && counts[STATE.recheck] === 1 && counts[STATE.missing] === 2 && counts[STATE.unconfirmed] === 1,
    JSON.stringify(counts));
}

// 1セル1件: 同じセルに欠落と見張りの変化と確認案件が重なったら、いちばん重い状態だけが出る
{
  const cells = [cell('a', 'tennyu', { breakdown: { ...FULL, 手数料: 0 } })];
  const statusItems = [{ municipality_id: 'a', procedure_id: 'tennyu', changed: true, gone: false, checked_at: '2026-09-08T00:00:00+0000' }];
  const verifiedRecords = [{ municipality_id: 'a', procedure_id: 'tennyu', fields: { fee: { status: 'needs_review' } } }];
  const q = buildQueue({ cells, statusItems, verifiedRecords });
  check('1セル1件・いちばん重い状態だけ', q.length === 1 && q[0].state === STATE.needsReview, JSON.stringify(q));
}

// 消えたページは理由が変わる
{
  const cells = [cell('a', 'tennyu')];
  const q = buildQueue({
    cells,
    statusItems: [{ municipality_id: 'a', procedure_id: 'tennyu', changed: false, gone: true, checked_at: '2026-09-08T00:00:00+0000' }],
  });
  check('消えたページ → 「消えています」', q[0]?.reason.includes('消えています'), q[0]?.reason);
}

// 採点していないページの見張り項目・記録は無視される（落ちない）
{
  const q = buildQueue({
    cells: [cell('a', 'tennyu')],
    statusItems: [{ municipality_id: 'z', procedure_id: 'tennyu', changed: true, gone: false, checked_at: '' }],
    verifiedRecords: [{ municipality_id: 'z', procedure_id: 'tennyu', fields: { fee: { status: 'needs_review' } } }],
  });
  check('採点していないページは課題に出ない', q.length === 0, JSON.stringify(q));
}

// データが無くても動く（見張り・記録なし）
{
  const q = buildQueue({ cells: [cell('a', 'tennyu', { breakdown: { ...FULL, 手数料: 0 } })] });
  check('見張り・記録なしでも欠落候補は出る', q.length === 1 && q[0].state === STATE.missing);
}

console.log(`\n結果: ${pass} PASS / ${fail} FAIL`);
if (fail > 0) process.exit(1);
