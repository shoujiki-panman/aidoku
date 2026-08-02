// 画面（web/demand.html）に出す**見本**のデータを作る。
//
//   node gatekeeper/build_demand_sample.mjs
//
// ⚠️ ここで作るのは「本物のAIが来た記録」ではない。門番はまだデプロイされておらず、
//    本物のエージェントは1体も来ていない。**来訪だけがこちらで作った再現**で、
//    「どの項目が空か」は 23区の実測（answers/）そのもの。
//    JSONにも is_sample: true を入れて、画面側で消せないラベルとして出す。
//
// 数字を手で書かないために、実物と同じ worker.mjs / demand.mjs / nlweb.mjs に
// 本物のEd25519署名で /ask を叩かせて、その集計をそのまま書き出す。
import worker from './worker.mjs';
import { generateKeyPair, jwkThumbprint, signRequest } from './httpsig.mjs';
import { readFile, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const WEB_DATA = join(HERE, '..', 'web', 'data');

// ── KVの代用（メモリ）──────────────────────────────
const memo = (m = new Map()) => ({
  put: async (k, _v, o) => void m.set(k, o?.metadata ?? null),
  list: async ({ prefix = '' } = {}) => ({
    keys: [...m.entries()]
      .filter(([k]) => k.startsWith(prefix))
      .sort(([a], [b]) => (a < b ? -1 : 1))
      .map(([name, metadata]) => ({ name, metadata })),
    list_complete: true,
  }),
});

const index = JSON.parse(await readFile(join(HERE, 'answers', '_index.json'), 'utf-8'));
const answers = new Map();
for (const r of index) {
  answers.set(r.key, JSON.parse(await readFile(join(HERE, 'answers', r.file), 'utf-8')));
}
const env = { DEMAND: memo(), ANSWERS: { get: async (key) => answers.get(key) ?? null } };

// ── 来訪するAIエージェント（2体。それぞれ本物の鍵を持つ）──────────
const jwksByOrigin = new Map();
const agents = [];
for (const origin of ['https://agent-a.example', 'https://agent-b.example']) {
  const { publicKey, privateKey } = await generateKeyPair();
  const jwk = await crypto.subtle.exportKey('jwk', publicKey);
  const keyid = await jwkThumbprint(jwk);
  jwksByOrigin.set(origin, { keys: [{ kty: 'OKP', crv: 'Ed25519', x: jwk.x, kid: keyid, use: 'sig' }] });
  agents.push({ origin, privateKey, keyid });
}

globalThis.fetch = async (input) => {
  const url = typeof input === 'string' ? input : input.url;
  for (const [origin, jwks] of jwksByOrigin) {
    if (url === `${origin}/.well-known/http-message-signatures-directory`) {
      return new Response(JSON.stringify(jwks));
    }
  }
  return new Response('<html>元サイト</html>', { headers: { 'content-type': 'text/html' } });
};

// ── 住民のAIが聞きそうなこと（4項目の自然な言い回し）────────────
// 文章はここで作るが、**答えの中身は作らない**（answers/ の実測をそのまま使う）。
// times は「同じ問いが何度も来る」のを見せるための重み。
// 実測で22区が空だった手数料をいちばん多く聞きに来る、という置き方にしてある。
const QUESTIONS = [
  { text: '転入届の手数料はいくらですか', times: 3 },
  { text: '転入届に必要な書類は何ですか', times: 2 },
  { text: '転入届はいつまでに出せばいいですか', times: 1 },
  { text: '転入届はオンラインでできますか', times: 1 },
];

// 実測済みのページから何件か選ぶ（キーは host+path）
const targets = index.slice(0, 8).map((r) => r.key);

async function ask(agent, key, text) {
  const [host, ...rest] = key.split('/');
  const path = `/${rest.join('/')}`;
  const now = Math.floor(Date.now() / 1000);
  const headers = await signRequest({
    authority: host,
    agent: agent.origin,
    privateKey: agent.privateKey,
    keyid: agent.keyid,
    created: now,
    expires: now + 300,
  });
  await worker.fetch(
    new Request(`https://${host}/ask`, {
      method: 'POST',
      headers: { ...headers, 'content-type': 'application/json' },
      body: JSON.stringify({ query: { text, site: path } }),
    }),
    env,
  );
}

// 記録レコードの console.log を画面に出さない
const realLog = console.log;
console.log = () => {};
let turn = 0;
for (const key of targets) {
  for (const q of QUESTIONS) {
    for (let n = 0; n < q.times; n++) {
      // 2体が代わるがわる聞きに来る（同じ問いが積み上がるところも見せる）
      await ask(agents[turn++ % agents.length], key, q.text);
    }
  }
}
console.log = realLog;

// ── 集計を実物の口（/_aidoku/demand）から取り出す ──────────────
const res = await worker.fetch(new Request('https://example.invalid/_aidoku/demand'), env);
const data = await res.json();

// 画面が消せないラベルとして出すための印
data.is_sample = true;
data.sample_note =
  '⚠️ これは見本です。門番はまだ公開されておらず、本物のAIエージェントは1件も来ていません。' +
  '来訪（誰が・何回）はこちらで作った再現で、「どの項目が空か」だけが23区の実測値です。';

await writeFile(join(WEB_DATA, 'demand.json'), `${JSON.stringify(data, null, 2)}\n`);

// ── CSV（チェックリスト26: データファイルの公開）────────────────
const csvCell = (v) => {
  const s = String(v ?? '');
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};
const csv = [
  ['自治体', 'ページ', '探し物', '来た回数', '取れた回数', '取れずに帰った回数', '最初', '最後'],
  ...data.all.map((x) => [
    x.authority,
    x.path,
    x.looking_for ?? '',
    x.count,
    x.answered_count,
    x.unanswered_count,
    x.first_seen,
    x.last_seen,
  ]),
]
  .map((row) => row.map(csvCell).join(','))
  .join('\n');
await writeFile(join(WEB_DATA, 'demand.csv'), `${csv}\n`);

// ── 要約テキスト（チェックリスト27: 要約されたテキストの公開）────────
const lines = [
  'AI読（アイドク） 門番が集めたデータの要約',
  '',
  data.sample_note.replace(/^⚠️ /, ''),
  '',
  `【集計】生成日: ${data.generated_at}`,
  `・AIが聞きに来た回数: ${data.totals.asks} 回`,
  `・答えを持ち帰れた: ${data.totals.answered} 回`,
  `・取れずに帰った: ${data.totals.unanswered} 回`,
  `・何を聞かれたか特定できず聞き返した: ${data.totals.undetermined} 回`,
  `・署名の検証に失敗した来訪: ${data.totals.unverified} 回`,
  `・来たAIの数（検証できた名乗り）: ${data.totals.agents} 体`,
  `・集計対象: ${data.coverage.from} 〜 ${data.coverage.to}（打ち切り: ${data.coverage.truncated ? 'あり' : 'なし'}）`,
  '',
  '【AIが探しに来たのに、取れずに帰ったもの（＝そのページに足りていない情報）】',
  ...data.unanswered
    .slice(0, 20)
    .map((x) => `・${x.unanswered_count}回  ${x.looking_for}  ${x.authority}${x.path}`),
  '',
  '本物のAIエージェントからの実データは、門番を公開してから集まります。',
  'これは個人が行った第三者調査であり、行政機関の公式発表ではありません。',
];
await writeFile(join(WEB_DATA, 'demand-summary.txt'), `${lines.join('\n')}\n`);

realLog('web/data/ に書き出しました:');
realLog(`  demand.json          (${data.totals.asks}回ぶんの集計)`);
realLog(`  demand.csv           (${data.all.length}行)`);
realLog('  demand-summary.txt');
realLog('');
realLog(`取れずに帰った探し物: ${data.unanswered.length} 種類`);
for (const x of data.unanswered.slice(0, 5)) {
  realLog(`  ${x.unanswered_count}回  ${x.looking_for}  ${x.authority}${x.path}`);
}
