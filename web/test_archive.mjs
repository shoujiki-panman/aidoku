// 調査データ一覧の言い方のテスト。DOM無しで回る（web/assets/archive-list.js のみ）。
// 実行: node web/test_archive.mjs
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
const require = createRequire(import.meta.url);
const A = require('./assets/archive-list.js');

let pass = 0, fail = 0;
function check(name, cond, detail = '') {
  if (cond) { pass++; console.log(`  PASS  ${name}`); }
  else { fail++; console.log(`  FAIL  ${name}  ${detail}`); }
}

// --- 日付 ---
check('測定時刻を日本語にする', A.jpDateTime('2026-08-17T12:56:14+00:00') === '2026年8月17日 12:56');
check('日だけの表記', A.jpDate('2026-08-11T13:52:32+00:00') === '2026年8月11日');
check('壊れた日付は空にする（それらしい日付を作らない）', A.jpDateTime('いつか') === '');
check('未定義でも落ちない', A.jpDate(undefined) === '' && A.jpDateTime(null) === '');

// --- 見出し。ここが本題 ---
{
  const same = A.headline({ n_runs: 3, n_distinct: 1 });
  check('★3回の記録でも、値が違うのが1回なら そう書く',
        same.includes('3回ぶんの記録') && same.includes('違ったのは1回'), same);
  check('★「3回調査しました」とは書かない', !same.includes('3回の調査'), same);
  check('同じ値の回の理由を書く', same.includes('書き出しをやり直した'), same);

  const all = A.headline({ n_runs: 2, n_distinct: 2 });
  check('全部値が違うなら、素直に回数を言う', all === '2回の調査を記録しています。', all);
  check('記録が無いときは無いと言う', A.headline({ n_runs: 0, n_distinct: 0 }).includes('まだありません'));
  check('引数が無くても落ちない', typeof A.headline() === 'string');
}

// --- 回の中身 ---
{
  const run = { procedures: [
    { procedure: '転入届', municipalities: 23, average: 59.6 },
    { procedure: '粗大ごみ収集の申込', municipalities: 23, average: 39.6 },
  ] };
  check('手続き数と自治体数を言う', A.runSummary(run) === '2手続き × 23自治体', A.runSummary(run));
  check('手続きが無ければ空', A.runSummary({ procedures: [] }) === '');
  check('平均に単位をつける', A.averageText({ average: 59.6 }) === '59.6点');
  check('★平均が無いとき 0点とは書かない', A.averageText({}) === '記録なし');
}

// --- 測定条件 ---
check('★条件未記録の回は、比較できないと書く',
      A.conditionLabel('legacy_unknown').includes('比較はできません'));
check('条件を記録した回はそう書く', A.conditionLabel('recorded').includes('記録しています'));
check('混在も言い分ける', A.conditionLabel('mixed').includes('違います'));
check('知らない値は不明と書く', A.conditionLabel('なにか').includes('不明'));

// --- 日付の言い方。★書き出し時刻を「測定」と呼ばない ---
{
  const run = { exported_at: '2026-08-17T12:56:14+00:00', measured_at: null };
  check('★見出しは「書き出し」と言う', A.exportedLabel(run) === '2026年8月17日 12:56 に書き出し',
        A.exportedLabel(run));
  check('★見出しに「測定」と書かない', !A.exportedLabel(run).includes('測定'), A.exportedLabel(run));
  check('★実測時刻が無ければ「記録なし」と書く',
        A.measuredLabel(run).includes('記録なし'), A.measuredLabel(run));
  check('★実測時刻の欄に書き出し時刻を出さない',
        !A.measuredLabel(run).includes('12:56'), A.measuredLabel(run));

  const measured = {
    exported_at: '2026-08-17T12:56:14+00:00',
    measured_at: '2026-07-22T04:05:06+00:00',
  };
  check('実測時刻があればそれを出す',
        A.measuredLabel(measured) === '測った日時: 2026年7月22日 04:05', A.measuredLabel(measured));
  check('書き出し時刻の記録が無い回も落ちない',
        A.exportedLabel({}).includes('記録なし') && A.measuredLabel().includes('記録なし'));
}

// --- 同じ値の但し書き ---
check('同じ値の回に但し書きが付く', A.repeatNote({ same_as_previous: true }).includes('測り直した結果ではなく'));
check('違う値の回には付かない', A.repeatNote({ same_as_previous: false }) === '');
check('引数無しでも落ちない', A.repeatNote() === '');

// --- 実データ ---
{
  const doc = JSON.parse(readFileSync(new URL('./data/surveys.json', import.meta.url), 'utf8'));
  check('公開データにも同じ形が入っている', Array.isArray(doc.runs) && doc.runs.length > 0);
  check('★指紋は公開データに残っていない',
        doc.runs.every((r) => r.procedures.every((p) => !('fingerprint' in p))));
  check('全期間のファイルが並んでいる', Array.isArray(doc.files) && doc.files.length >= 3);
  check('各回に書き出し日がある', doc.runs.every((r) => /^\d{4}-\d{2}-\d{2}$/.test(r.exported_on)));
  check('★書き出し時刻を measured_at という名前で出していない',
        doc.runs.every((r) => r.measured_at !== r.exported_at));
  check('★実測時刻が無い回は null のまま（それらしい日付を作らない）',
        doc.runs.every((r) => r.measured_at_status === 'recorded'
          ? /^\d{4}-\d{2}-\d{2}$/.test(r.measured_on)
          : r.measured_at === null && r.measured_on === null));
  check('★いまの公開データは実測時刻が全件不明', doc.n_measured_unknown === doc.n_runs,
        `${doc.n_measured_unknown}/${doc.n_runs}`);
  check('★説明文が「書き出し時刻であって測定時刻ではない」と言っている',
        String(doc._about).includes('測定した時刻ではない'), doc._about);
  check('★いまの記録は3回・値が違うのは1回', doc.n_runs === 3 && doc.n_distinct === 1,
        `${doc.n_runs}/${doc.n_distinct}`);
}

// --- 画面が測定時刻を騙らないこと（DOM組み立て側の文字列を直接見る） ---
{
  const view = readFileSync(new URL('./assets/archive-view.js', import.meta.url), 'utf8');
  check('★カードの見出しに「に測定」を戻していない', !view.includes('に測定'), 'archive-view.js');
  check('カードは exportedLabel を使う', view.includes('A.exportedLabel(run)'));
  check('カードは measuredLabel を使う', view.includes('A.measuredLabel(run)'));
}

// --- 画面から点数を外したこと ---
{
  const app = readFileSync(new URL('./assets/app.js', import.meta.url), 'utf8');
  check('★住民の画面に棒グラフを戻していない', !app.includes('progressBar'));
  check('★住民の画面に 見張りと推移 への案内を戻していない', !app.includes('見張りと推移'));
  const html = readFileSync(new URL('./index.html', import.meta.url), 'utf8');
  check('住民の画面から調査データ一覧へ行ける', html.includes('archive.html'));
}

console.log(`\n  ${pass} PASS / ${fail} FAIL`);
process.exit(fail === 0 ? 0 : 1);
