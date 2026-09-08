// 素通し先（env.ORIGIN）のテスト。
// 実行: node gatekeeper/test_origin.mjs
//
// 確かめたいことは1つ。
// workers.dev で動かしたとき、素通しが自分自身への再帰にならず ORIGIN へ渡るか。
//   - 署名なし（人間）→ ORIGIN の同じパスへ
//   - 検証失敗・答えなし → 同じく ORIGIN へ
//   - ORIGIN 未設定 → 従来どおり同じURLへ（実際に前へ置くときの動き）
import worker from './worker.mjs';

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

const fetched = [];
globalThis.fetch = async (input) => {
  const url = typeof input === 'string' ? input : input.url;
  fetched.push(url);
  return new Response('<html>素通し先</html>', { headers: { 'content-type': 'text/html' } });
};

const WORKER_URL = 'https://aidoku-gatekeeper.example.workers.dev/web/fix.html?muni=setagaya';
const ORIGIN = 'https://shoujiki-panman.github.io/aidoku';

console.log('テスト:');

// 署名なし → ORIGIN の同じパス＋クエリへ
{
  fetched.length = 0;
  const res = await worker.fetch(new Request(WORKER_URL), { ORIGIN });
  check('署名なしの素通しが ORIGIN へ渡る',
    fetched[0] === `${ORIGIN}/web/fix.html?muni=setagaya`, JSON.stringify(fetched));
  check('  └ 中身はそのまま返る', (await res.text()).includes('素通し先'));
}

// ORIGIN 未設定 → 従来どおり同じURL（実際に自治体サイトの前に置くときの動き）
{
  fetched.length = 0;
  await worker.fetch(new Request(WORKER_URL), {});
  check('ORIGIN 未設定なら同じURLへ（従来の動き）', fetched[0] === WORKER_URL, JSON.stringify(fetched));
}

// ORIGIN が壊れていても落ちない（従来の素通しに戻る）
{
  fetched.length = 0;
  await worker.fetch(new Request(WORKER_URL), { ORIGIN: 'not a url' });
  check('ORIGIN が壊れていても門番は落ちない', fetched[0] === WORKER_URL, JSON.stringify(fetched));
}

// 末尾スラッシュつきの ORIGIN でも二重スラッシュにならない
{
  fetched.length = 0;
  await worker.fetch(new Request(WORKER_URL), { ORIGIN: `${ORIGIN}/` });
  check('ORIGIN 末尾スラッシュを二重にしない', fetched[0] === `${ORIGIN}/web/fix.html?muni=setagaya`, JSON.stringify(fetched));
}

console.log(`\n結果: ${pass} PASS / ${fail} FAIL`);
if (fail > 0) process.exit(1);
