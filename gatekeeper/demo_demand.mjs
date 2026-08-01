// 門番に何体かのAIエージェントを来させて、「何を探しに来て、取れずに帰ったか」が
// データになるところを、Cloudflare無しでそのまま見せる。
//
//   node gatekeeper/demo_demand.mjs
//
// 使うのは実物と同じ worker.mjs / demand.mjs。KVだけメモリ上の代用に差し替える。
// エージェントの署名も本物（Ed25519）で、門番はそれを検証してから記録する。
import worker from './worker.mjs';
import { generateKeyPair, jwkThumbprint, signRequest } from './httpsig.mjs';
import { readFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));

// ── KVの代用（メモリ）──────────────────────────────
const memo = (m = new Map()) => ({
  put: async (k, _v, o) => void m.set(k, o?.metadata ?? null),
  list: async ({ prefix = '' } = {}) => ({
    keys: [...m.entries()].filter(([k]) => k.startsWith(prefix)).map(([name, metadata]) => ({ name, metadata })),
    list_complete: true,
  }),
});

// 実測から作った答え（gatekeeper/answers）をそのまま使う
const index = JSON.parse(await readFile(join(HERE, 'answers', '_index.json'), 'utf-8'));
const answers = new Map();
for (const r of index) {
  answers.set(r.key, JSON.parse(await readFile(join(HERE, 'answers', r.file), 'utf-8')));
}
const env = {
  DEMAND: memo(),
  ANSWERS: { get: async (key) => answers.get(key) ?? null },
};

// ── 来訪するAIエージェント（2体。それぞれ自分の鍵を持つ）──────────
const agents = [];
for (const origin of ['https://agent-a.example', 'https://agent-b.example']) {
  const { publicKey, privateKey } = await generateKeyPair();
  const jwk = await crypto.subtle.exportKey('jwk', publicKey);
  agents.push({ origin, privateKey, keyid: await jwkThumbprint(jwk), jwk });
}

// 門番が鍵を取りに行く先（JWKS）を差し替える
const realFetch = globalThis.fetch;
globalThis.fetch = async (input) => {
  const u = typeof input === 'string' ? input : input.url;
  const a = agents.find((x) => u === `${x.origin}/.well-known/http-message-signatures-directory`);
  if (a) {
    return new Response(
      JSON.stringify({ keys: [{ kty: 'OKP', crv: 'Ed25519', x: a.jwk.x, kid: a.keyid, use: 'sig' }] }),
      { headers: { 'content-type': 'application/json' } },
    );
  }
  return new Response('<html>元サイトのHTML</html>', { headers: { 'content-type': 'text/html' } });
};

// ── 住民のAIが実際に探しに来そうなもの ──────────────────
const VISITS = [
  ['minato', '/shibamadosa/kurashi/todokede/hikkoshi/tennyu.html', 'www.city.minato.tokyo.jp', '転入届 必要書類', 3],
  ['minato', '/shibamadosa/kurashi/todokede/hikkoshi/tennyu.html', 'www.city.minato.tokyo.jp', '転入届 手数料', 2],
  ['setagaya', '/kurashi/kosekijuumin/11531.html', 'www.city.setagaya.lg.jp', '転入届 必要書類', 4],
  ['setagaya', '/kurashi/kosekijuumin/11531.html', 'www.city.setagaya.lg.jp', '転入届　手数料', 3], // 全角ゆれ
  ['setagaya', '/kurashi/kosekijuumin/11531.html', 'www.city.setagaya.lg.jp', '転入届 期限', 2],
  ['shinjuku', '/todokede/koseki01_000001_00007.html', 'www.city.shinjuku.lg.jp', '転入届 手数料', 2],
];

// worker は1件ごとに生の記録を console.log する。デモでは結果だけ見せたいので黙らせる。
const realLog = console.log;
console.log = () => {};

let n = 0;
for (const [, path, host, q, times] of VISITS) {
  for (let i = 0; i < times; i++) {
    const a = agents[i % agents.length];
    const now = Math.floor(Date.now() / 1000);
    const headers = await signRequest({
      authority: host,
      agent: a.origin,
      privateKey: a.privateKey,
      keyid: a.keyid,
      created: now,
      expires: now + 300,
    });
    await worker.fetch(new Request(`https://${host}${path}?q=${encodeURIComponent(q)}`, { headers }), env, {});
    n++;
  }
}

// 人（署名なし）も混ぜる。これは記録されないはず。
for (let i = 0; i < 5; i++) {
  await worker.fetch(new Request('https://www.city.setagaya.lg.jp/kurashi/kosekijuumin/11531.html'), env, {});
}

// ── 取り出し口から、できたデータを読む ──────────────────
const res = await worker.fetch(new Request('https://www.city.setagaya.lg.jp/_aidoku/demand'), env, {});
const d = await res.json();

globalThis.fetch = realFetch;
console.log = realLog;

console.log(`AIエージェントの来訪 ${n}件 ＋ 人のアクセス5件を流しました。\n`);
console.log(`記録されたのは ${d.totals.asks}件（人の5件は入っていません）`);
console.log(`  答えを持ち帰れた: ${d.totals.answered}件 / 取れずに帰った: ${d.totals.unanswered}件`);
console.log(`  来たエージェント: ${d.totals.agents}体\n`);
console.log('■ AIが探しに来たのに、取れずに帰ったもの（＝そのページに足りていない情報）');
for (const r of d.unanswered) {
  console.log(`  ${String(r.unanswered_count).padStart(2)}回  ${r.looking_for}`);
  console.log(`        ${r.authority}${r.path}`);
}
console.log('\n■ 答えを渡せたもの');
for (const r of d.all.filter((x) => x.answered_count > 0)) {
  console.log(`  ${String(r.answered_count).padStart(2)}回  ${r.looking_for}  （${r.authority}）`);
}
console.log(`\n${d.note}`);
