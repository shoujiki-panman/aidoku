// AIエージェントと門番が実際に何をやり取りしているかを、そのまま書き出す。
//
//   node gatekeeper/demo_talk.mjs
//
// 使うのは実物の worker.mjs / httpsig.mjs / demand.mjs。
// 署名も本物（Ed25519）で、門番はそれを検証してから答えている。
import worker from './worker.mjs';
import { generateKeyPair, jwkThumbprint, signRequest } from './httpsig.mjs';
import { readFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const AGENT = 'https://agent-a.example';

// KVの代用（メモリ）
const store = new Map();
const DEMAND = {
  put: async (k, _v, o) => void store.set(k, o?.metadata ?? null),
  list: async ({ prefix = '' } = {}) => ({
    keys: [...store.entries()].filter(([k]) => k.startsWith(prefix)).map(([name, metadata]) => ({ name, metadata })),
    list_complete: true,
  }),
};

const index = JSON.parse(await readFile(join(HERE, 'answers', '_index.json'), 'utf-8'));
const answers = new Map();
for (const r of index) answers.set(r.key, JSON.parse(await readFile(join(HERE, 'answers', r.file), 'utf-8')));
const env = { DEMAND, ANSWERS: { get: async (k) => answers.get(k) ?? null } };

// エージェントの鍵と、門番が鍵を取りに行く先
const { publicKey, privateKey } = await generateKeyPair();
const jwk = await crypto.subtle.exportKey('jwk', publicKey);
const keyid = await jwkThumbprint(jwk);
const realFetch = globalThis.fetch;
globalThis.fetch = async (input) => {
  const u = typeof input === 'string' ? input : input.url;
  if (u === `${AGENT}/.well-known/http-message-signatures-directory`) {
    return new Response(JSON.stringify({ keys: [{ kty: 'OKP', crv: 'Ed25519', x: jwk.x, kid: keyid, use: 'sig' }] }), {
      headers: { 'content-type': 'application/json' },
    });
  }
  return new Response('<html>… 区の手続きページのHTML …</html>', { headers: { 'content-type': 'text/html' } });
};

const quiet = console.log;
const say = (...a) => quiet(...a);

const CASES = [
  ['港区（ページに答えが書いてある）', 'www.city.minato.tokyo.jp', '/shibamadosa/kurashi/todokede/hikkoshi/tennyu.html', '転入届 必要書類'],
  ['新宿区（他は書いてあるが、手数料だけ無い）', 'www.city.shinjuku.lg.jp', '/todokede/koseki01_000001_00007.html', '転入届 手数料'],
  ['世田谷区（入口ページに何も無い）', 'www.city.setagaya.lg.jp', '/kurashi/kosekijuumin/11531.html', '転入届 手数料'],
];

for (const [title, host, path, q] of CASES) {
  const now = Math.floor(Date.now() / 1000);
  const headers = await signRequest({ authority: host, agent: AGENT, privateKey, keyid, created: now, expires: now + 300 });

  say(`\n──────── ${title} ────────`);
  say(`\n【AI → 門番】 何を探しに来たか、名乗りと署名つきで`);
  say(`  GET https://${host}${path}?q=${q}`);
  say(`  Signature-Agent: ${headers['signature-agent']}`);
  say(`  Signature-Input: ${headers['signature-input'].slice(0, 96)}…`);
  say(`  Signature:       ${headers.signature.slice(0, 46)}…`);

  console.log = () => {}; // worker が出す生ログを止める
  const res = await worker.fetch(new Request(`https://${host}${path}?q=${encodeURIComponent(q)}`, { headers }), env, {});
  const ctype = res.headers.get('content-type') || '';
  const body = ctype.includes('json') ? await res.json() : await res.text();
  console.log = quiet;

  say(`\n【門番】 署名を確かめる`);
  say(`  → ${AGENT} 本人だと確認できた（鍵 ${keyid.slice(0, 12)}…）`);

  say(`\n【門番 → AI】`);
  if (typeof body === 'string') {
    say(`  ${res.status} text/html — 渡せる答えを持っていないので、元のページをそのまま返した`);
    say(`  ${body.slice(0, 60)}`);
  } else {
    say(`  ${res.status} application/json`);
    say(`  聞かれたこと : ${body.asked}`);
    say(`  取れたか     : ${body.answered ? 'はい' : 'いいえ（この項目はページに無い）'}`);
    const f = body.answer.fields;
    for (const [k, v] of Object.entries(f)) {
      say(`    ${k.padEnd(20)}: ${v === null ? '（無い）' : String(v).slice(0, 46) + (String(v).length > 46 ? '…' : '')}`);
    }
  }

  const rec = [...store.values()].pop();
  say(`\n【門番のメモ】 ${rec.looking_for} を探しに来て、${rec.answered ? '取れた' : '取れずに帰った'}`);
}

globalThis.fetch = realFetch;
say(`\n──────── ここまでで貯まったもの ────────\n`);
const d = await (await worker.fetch(new Request('https://www.city.setagaya.lg.jp/_aidoku/demand'), env, {})).json();
for (const r of d.unanswered) say(`  取れずに帰った: 「${r.looking_for}」  ${r.authority}${r.path}`);
say(`\n  ${d.note}`);
