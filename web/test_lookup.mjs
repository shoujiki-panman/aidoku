// 「自分の区を調べる」の照合テスト。DOM無しで回る（web/assets/lookup.js のみ）。
// 実行: node web/test_lookup.mjs
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { normalizeUrl, normalizeName, lookup, missingSummary, cellChip } = require('./assets/lookup.js');

let pass = 0;
let fail = 0;
function check(name, cond, detail = '') {
  if (cond) { pass++; console.log(`  PASS  ${name}`); }
  else { fail++; console.log(`  FAIL  ${name}  ${detail}`); }
}

// 実データと同じ形の最小セット
const CELLS = [
  { procId: 'tennyu', procName: '転入届', muniId: 'setagaya', muniName: '世田谷区',
    total: 0, url: 'https://www.city.setagaya.lg.jp/kurashi/kosekijuumin/11531.html' },
  { procId: 'sodaigomi', procName: '粗大ごみ収集の申込', muniId: 'setagaya', muniName: '世田谷区',
    total: 0, url: 'https://www.city.setagaya.lg.jp/kurashi/gomi/category/11682.html' },
  { procId: 'jidouteate', procName: '児童手当の申請', muniId: 'setagaya', muniName: '世田谷区',
    total: 0, url: 'https://www.city.setagaya.lg.jp/kurashi/kosodate/1.html' },
  { procId: 'tennyu', procName: '転入届', muniId: 'minato', muniName: '港区',
    total: 100, url: 'https://www.city.minato.tokyo.jp/shibamadosa/kurashi/todokede/hikkoshi/tennyu.html' },
];
const ORDER = ['tennyu', 'jidouteate', 'sodaigomi'];

// --- normalizeUrl ---
check('プロトコルとwwwを落とす',
  normalizeUrl('https://www.city.minato.tokyo.jp/a.html').key === 'city.minato.tokyo.jp/a.html');
check('クエリとフラグメントを落とす',
  normalizeUrl('https://a.jp/b.html?x=1#top').key === 'a.jp/b.html');
check('末尾スラッシュを落とす', normalizeUrl('https://a.jp/b/').key === 'a.jp/b');
check('index.html は落とさない',
  normalizeUrl('https://a.jp/b/index.html').key === 'a.jp/b/index.html');
check('ホストだけでも読める', normalizeUrl('city.setagaya.lg.jp').host === 'city.setagaya.lg.jp');
check('URLでないものは null', normalizeUrl('世田谷区') === null);
check('空文字は null', normalizeUrl('') === null);
check('文字列でなければ null', normalizeUrl(null) === null);

// --- normalizeName ---
check('末尾の区を落とす', normalizeName('世田谷区') === '世田谷');
check('空白を落とす', normalizeName('  世田谷 区 ') === '世田谷');

// --- lookup: ページそのものが当たる ---
const r1 = lookup('https://www.city.setagaya.lg.jp/kurashi/kosekijuumin/11531.html', CELLS, ORDER);
check('貼ったページを測ってあれば page', r1.kind === 'page', JSON.stringify(r1));
check('page はそのマスを返す', r1.kind === 'page' && r1.cell.procId === 'tennyu');
check('www有無・末尾スラッシュが違っても当たる',
  lookup('http://city.setagaya.lg.jp/kurashi/kosekijuumin/11531.html/', CELLS, ORDER).kind === 'page');

// --- lookup: 区は測ってあるがページは測っていない ---
const r2 = lookup('https://www.city.setagaya.lg.jp/kurashi/zei/9999.html', CELLS, ORDER);
check('同じ区の別ページは ward', r2.kind === 'ward', JSON.stringify(r2));
check('ward は URL ホスト一致と分かる', r2.kind === 'ward' && r2.matchedBy === 'url-host');
check('ward はその区の3マスを返す', r2.kind === 'ward' && r2.cells.length === 3);
check('ward は procedures.json の並び',
  r2.kind === 'ward' && r2.cells.map((c) => c.procId).join(',') === 'tennyu,jidouteate,sodaigomi');

// --- lookup: 区名で引く ---
const r3 = lookup('世田谷区', CELLS, ORDER);
check('区名で ward', r3.kind === 'ward' && r3.matchedBy === 'name');
check('「区」抜きでも引ける', lookup('世田谷', CELLS, ORDER).kind === 'ward');

// --- lookup: 当たらない ---
check('未測定の自治体は none',
  lookup('https://www.city.hachioji.tokyo.jp/a.html', CELLS, ORDER).kind === 'none');
check('未測定の理由は unmeasured',
  lookup('八王子市', CELLS, ORDER).reason === 'unmeasured');
check('空入力は empty', lookup('', CELLS, ORDER).reason === 'empty');
check('空白だけも empty', lookup('   ', CELLS, ORDER).reason === 'empty');
check('cells が配列でなくても落ちない', lookup('世田谷区', null, ORDER).kind === 'none');
check('壊れた行は落として続ける',
  lookup('港区', [null, 'x', { muniName: '' }, ...CELLS], ORDER).kind === 'ward');

// ★ 当てずっぽうを返さないこと。盤面のグレーと同じ約束
check('測っていないものに点数をつけない',
  lookup('八王子市', CELLS, ORDER).cell === undefined);

// --- 住民に見せる1文。点数（7/12）と棒グラフの代わり ---
// ★本人の指摘:「住民側にこれいらないでしょ。一切説明もない」
{
  const some = missingSummary(5, 3, 4);
  check('読み取れなかった数を言う', some === '測った3つの手続きのうち、AIが区のページから読み取れなかった項目が5つあります。', some);
  check('★点数の書き方（7/12）はしない', !/\d+\s*\/\s*\d+/.test(some), some);
  check('★「知れない」のような不自然な言い方をしない', !some.includes('知れない'), some);

  check('全部読めたときは、そう言う',
    missingSummary(0, 3, 4) === '測った3つの手続きは、どれも4項目すべてを読み取れました。');
  check('項目数は引数から出す（4を埋め込まない）',
    missingSummary(0, 2, 5).includes('5項目すべて'), missingSummary(0, 2, 5));
  check('1つも読めなかったときは、そう言う',
    missingSummary(12, 3, 4).includes('1項目も読み取れませんでした'));

  check('手続きが0なら何も言わない', missingSummary(0, 0, 4) === '');
  check('数字でなければ何も言わない', missingSummary('あ', 3, 4) === '' && missingSummary(1, null, 4) === '');
}

// --- 手続き1行の札 ---
{
  check('読めない数を言う', cellChip(2, 4) === '読めない 2項目');
  check('全部読めたときの札', cellChip(0, 4) === '4項目とも読めた');
  check('★0/4 のような点数にしない', !cellChip(0, 4).includes('/') && !cellChip(3, 4).includes('/'));
  check('数字でなければ空', cellChip(undefined, 4) === '');
}

console.log(`\n  ${pass} PASS / ${fail} FAIL`);
process.exit(fail === 0 ? 0 : 1);
