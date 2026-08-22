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
  // 本文の範囲。6枚とも <main> で統一されている
  ok(`${f} の data-selector が main`, /data-selector="main"/.test(tag[0]));
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

console.log(`${pass} PASS / ${fail} FAIL`);
process.exit(fail ? 1 : 0);
