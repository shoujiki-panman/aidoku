// 「AIで開く」ボタンの組み込みを見る。
// ボタン本体（ask-ai-button.js）は外から貰った1ファイルで、中身は書き換えない。
// こちらが持つのは**どのページに載せ、どこを本文から外すか**だけなので、そこを見る。
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const read = (f) => readFileSync(join(here, f), 'utf8');

let pass = 0, fail = 0;
const ok = (name, cond, detail) => {
  if (cond) { pass++; return; }
  fail++;
  console.log(`FAIL ${name}${detail ? ` — ${detail}` : ''}`);
};

// 「 2.html」のような同期ソフトの複製は対象外
const pages = readdirSync(here)
  .filter((f) => f.endsWith('.html') && !/ \d+\.html$/.test(f))
  .sort();
ok('ページを見つけた', pages.length >= 6, `${pages.length}枚`);

for (const f of pages) {
  const s = read(f);
  const tag = s.match(/<script[^>]*ask-ai-button\.js[^>]*><\/script>/);
  ok(`${f} にボタンがある`, !!tag);
  if (!tag) continue;

  // ★ここは GitHub Pages のプロジェクトサイト（/aidoku/web/ 配下）。
  //   src="/ask-ai-button.js" と絶対で書くとドメイン直下を指して 404 になる。
  ok(`${f} の src が相対`, /src="ask-ai-button\.js"/.test(tag[0]), tag[0]);
  ok(`${f} が defer`, /\bdefer\b/.test(tag[0]));
  // 渡す範囲。index だけは「渡す用の中身」に絞る。
  // ページ全体を渡すと 10,000字を超えてURLに載らず、クリップボード経由になって
  // 本人が手で貼らないと動かない（実測 10,354字 → エンコード後 46,361）。
  const sel = (tag[0].match(/data-selector="([^"]+)"/) || [])[1];
  if (f === 'index.html') {
    ok(`${f} は #ai-payload だけを渡す`, sel === '#ai-payload', sel);
    ok(`${f} に #ai-payload がある`, /id="ai-payload"/.test(s));
    ok(`${f} の #ai-payload は画面に出さない`,
      /id="ai-payload"[^>]*dads-u-visually-hidden/.test(s));
  } else {
    ok(`${f} の data-selector が main`, sel === 'main', sel);
  }
  // 上流の4つ（要約・解説・質問・英訳）は読み物向けで、ここの目的と違う。
  // 出すのは AI読 が足した procedure だけ
  ok(`${f} の行動が procedure だけ`, /data-actions="procedure"/.test(tag[0]), tag[0]);
  ok(`${f} に main がある`, /<main[\s>]/.test(s));
  // 読み込みは </body> の直前（本文より後）
  ok(`${f} はボタンを最後に読む`, s.indexOf('ask-ai-button.js') > s.lastIndexOf('</main>'));
}

// 本文に混ぜたくない操作部品。ここが外れると、AIに座標やタブの文字が流れる
const index = read('index.html');
for (const sel of ['id="wardmap"', 'class="wardpick"', 'class="lookup__escape"', 'id="proc-tabs"']) {
  const m = index.match(new RegExp(`<[a-z]+[^>]*${sel.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}[^>]*>`));
  ok(`index の ${sel} を本文から外している`, !!m && /data-ai-ignore/.test(m[0]), m && m[0].slice(0, 70));
}

// 免責は本文と一緒に渡す。ここに data-ai-ignore が付いたら、
// AIに渡した文から「行政機関の公式発表ではありません」が落ちる
for (const f of pages) {
  const s = read(f);
  for (const m of s.matchAll(/<[a-z]+[^>]*class="[^"]*dads-notification-banner[^"]*"[^>]*>/g)) {
    ok(`${f} の免責は本文に残る`, !/data-ai-ignore/.test(m[0]), m[0].slice(0, 70));
  }
}

// 本体は外部から貰ったまま置く。外部通信もキーも持たない前提を、置いた時点で確かめる
const lib = read('ask-ai-button.js');
ok('本体がある', lib.length > 10000, `${lib.length}byte`);
ok('読み込み時に外へ出さない', !/\bfetch\s*\(|XMLHttpRequest|navigator\.sendBeacon/.test(lib));
ok('APIキーを持たない', !/api[_-]?key/i.test(lib));
ok('本文の範囲を data-ai-ignore で決める', lib.includes('data-ai-ignore'));

// AI読 が足した1項目。上流を更新するときに落ちやすいので、中身まで見る。
const block = lib.match(/▼▼▼ ここから AI読 の追加[\s\S]*?▲▲▲ ここまで AI読 の追加/);
ok('追加ブロックが1つに固まっている', !!block);
ok('上流の4つを消していない',
  ['summary:', 'explain:', 'ask:', 'translate:'].every((k) => lib.includes(k)));
if (block) {
  const b = block[0];
  ok('procedure がある', /procedure: \{/.test(b));
  // この指示が落ちると、AIは「無料です」「通常14日以内です」と一般論で埋める。
  // それを止めるために足したブロックなので、消えたら気づく必要がある
  ok('推測での穴埋めを禁じている', /一般論や他の自治体の値で埋めない/.test(b));
  ok('窓口確認へ案内している', /窓口に電話で確認/.test(b));
  ok('記憶で答えさせない', /あなたの記憶で答えない/.test(b));
  ok('公式発表ではないと言わせる', /公式発表ではありません/.test(b));
  ok('出典と測定時期を書かせる', /実測がいつのもの/.test(b));
  ok('持ち物までやらせる', /当日持っていくもの/.test(b));
}

console.log(`${pass} PASS / ${fail} FAIL`);
process.exit(fail ? 1 : 0);
