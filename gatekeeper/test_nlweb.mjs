// NLWeb の窓口（POST /ask）のテスト。
// 仕様: https://nlweb.ai/docs/specification
// 実行: node gatekeeper/test_nlweb.mjs
//
// 確かめたいことは1つ。
// 「実際のAIは ?q= を付けてこない」という穴が、これで本当に塞がったか。
//   - 探し物は query.text で受け取れているか
//   - 答えられないときに failure が返り、「取れずに帰った」として記録されるか
//   - どの項目か分からないときに、黙って「取れた」にせず elicitation で聞き返すか
import worker from './worker.mjs';
import { generateKeyPair, jwkThumbprint, signRequest } from './httpsig.mjs';

const AGENT_ORIGIN = 'https://agent.example';
const HOST = 'www.city.shinjuku.lg.jp';
const SITE = `https://${HOST}`;
const PAGE = '/todokede/tennyu.html';

// --- 実測データ（新宿区。オンライン可否は書いてあるが手数料は書かれていない）---
const SHINJUKU = {
  procedure: '転入届',
  municipality: '新宿区',
  source: `${SITE}${PAGE}`,
  measured_at: '2026-07-22',
  fields: {
    required_documents: null,
    how_to_apply: '窓口(来庁)での届出が必要とされている。オンラインで完結できるとの記載はない',
    deadline: null,
    fee: null,
  },
  note: 'デジタル庁OSS「源内」のAIアプリ仕様に準拠した第三者調査（AI読）による実測値です。行政機関の公式発表ではありません。',
};

// --- エージェントの鍵と JWKS ---
const { publicKey, privateKey } = await generateKeyPair();
const pubJwk = await crypto.subtle.exportKey('jwk', publicKey);
const keyid = await jwkThumbprint(pubJwk);

globalThis.fetch = async (input) => {
  const url = typeof input === 'string' ? input : input.url;
  if (url === `${AGENT_ORIGIN}/.well-known/http-message-signatures-directory`) {
    return new Response(
      JSON.stringify({ keys: [{ kty: 'OKP', crv: 'Ed25519', x: pubJwk.x, kid: keyid, use: 'sig' }] }),
    );
  }
  return new Response('<html>元サイト</html>', { headers: { 'content-type': 'text/html' } });
};

// --- 記録を捕まえる ---
const records = [];
const realLog = console.log;
console.log = (line) => {
  try {
    records.push(JSON.parse(line));
  } catch {
    realLog(line);
  }
};

const store = new Map();
const env = {
  ANSWERS: { get: async (key) => (key === `${HOST}${PAGE}` ? SHINJUKU : null) },
  DEMAND: {
    put: async (k, _v, o) => store.set(k, o?.metadata ?? null),
    list: async ({ prefix = '' } = {}) => ({
      keys: [...store.entries()]
        .filter(([k]) => k.startsWith(prefix))
        .map(([name, metadata]) => ({ name, metadata })),
      list_complete: true,
    }),
  },
};

let pass = 0;
let fail = 0;
function check(name, cond, detail = '') {
  if (cond) {
    pass++;
    realLog(`  PASS  ${name}`);
  } else {
    fail++;
    realLog(`  FAIL  ${name}  ${detail}`);
  }
}

const now = Math.floor(Date.now() / 1000);
const signed = await signRequest({
  authority: HOST,
  agent: AGENT_ORIGIN,
  privateKey,
  keyid,
  created: now,
  expires: now + 300,
});

// NLWeb の作法どおりに聞く。?q= は付けない（実際のAIは付けてこない）
async function ask(text, { headers = signed, site = PAGE } = {}) {
  const res = await worker.fetch(
    new Request(`${SITE}/ask`, {
      method: 'POST',
      headers: { ...headers, 'content-type': 'application/json' },
      body: JSON.stringify({ query: { text, site }, prefer: { mode: 'list' } }),
    }),
    env,
  );
  return { res, body: await res.json() };
}

realLog('テスト:');

// 1. 書いてある項目を聞く → answer
const a = await ask('転入届はオンラインでできますか');
check('書いてある項目 → answer が返る', a.body._meta?.response_type === 'answer', JSON.stringify(a.body).slice(0, 160));
check('  └ 仕様どおり _meta に version がある', typeof a.body._meta?.version === 'string', JSON.stringify(a.body._meta));
check(
  '  └ results は schema.org の型で返る',
  a.body.results?.[0]?.['@type'] === 'GovernmentService' &&
    a.body.results[0].provider?.name === '新宿区',
  JSON.stringify(a.body.results?.[0]).slice(0, 160),
);
check('  └ 実測値そのものが入っている', a.body.results?.[0]?.fields?.how_to_apply?.includes('窓口'), '');
check(
  '  └ 行政の公式発表ではない旨が付いてくる',
  a.body.results?.[0]?.note?.includes('公式発表ではありません'),
  '',
);

// 2. 書かれていない項目を聞く → failure（これが主役のデータ）
const f = await ask('転入届の手数料はいくらですか');
check('書かれていない項目 → failure が返る', f.body._meta?.response_type === 'failure', JSON.stringify(f.body).slice(0, 160));
check('  └ 規格の error.code = NO_RESULTS', f.body.error?.code === 'NO_RESULTS', JSON.stringify(f.body.error));
check(
  '  └ ?q= を付けずに「取れずに帰った」が記録される',
  records.at(-1)?.answered === false && records.at(-1)?.looking_for === '転入届の手数料はいくらですか',
  JSON.stringify(records.at(-1)),
);
check('  └ NLWeb 経由と分かる印が付く', records.at(-1)?.via === 'nlweb', JSON.stringify(records.at(-1)?.via));

// 3. どの項目か分からない → elicitation（黙って「取れた」にしない）
//    ここが ?q= 時代の穴だった。曖昧なら推測せず聞き返す。
const e = await ask('転入届について教えてください');
check(
  'どの項目か分からない → elicitation で聞き返す',
  e.body._meta?.response_type === 'elicitation',
  JSON.stringify(e.body).slice(0, 160),
);
check('  └ 聞き返しに選択肢が付く', Array.isArray(e.body.elicitation?.questions?.[0]?.options), '');
check(
  '  └ 選択肢は実測で値がある項目だけ（空の項目を勧めない）',
  e.body.elicitation.questions[0].options.length === 1 &&
    e.body.elicitation.questions[0].options[0].includes('窓口'),
  JSON.stringify(e.body.elicitation.questions[0].options),
);
check(
  '  └ 曖昧な問いは「取れた」に数えない（answered=null）',
  records.at(-1)?.answered === null && records.at(-1)?.verified === true,
  JSON.stringify(records.at(-1)),
);

// 4. 実測データを持っていないページ → failure
const u = await ask('転入届の手数料は', { site: '/unknown.html' });
check('未調査のページ → failure', u.body._meta?.response_type === 'failure', JSON.stringify(u.body).slice(0, 120));

// 5. 署名なし（人間）→ 答えは返すが記録しない
const before = records.length;
const h = await ask('転入届の手数料はいくらですか', { headers: { 'user-agent': 'Mozilla/5.0' } });
check('署名なしでも答えは返る', !!h.body._meta?.response_type, JSON.stringify(h.body._meta));
check('署名なしは記録しない（住民のデータは集めない）', records.length === before, `${before} -> ${records.length}`);

// 6. 壊れたリクエスト → 規格の INVALID_QUERY（門番は落ちない）
const bad = await worker.fetch(
  new Request(`${SITE}/ask`, { method: 'POST', headers: signed, body: 'これはJSONではない' }),
  env,
);
const badBody = await bad.json();
check('壊れた body でも落ちず INVALID_QUERY', badBody.error?.code === 'INVALID_QUERY', JSON.stringify(badBody));

const getRes = await worker.fetch(new Request(`${SITE}/ask`, { headers: signed }), env);
check('GET は 405 で INVALID_QUERY', getRes.status === 405, String(getRes.status));

// 7. 集計に「聞き返した分」が別で出る
const demand = await (await worker.fetch(new Request(`${SITE}/_aidoku/demand`), env)).json();
check(
  '集計に undetermined（聞き返した分）が出る',
  demand.totals.undetermined === 1 && demand.totals.unanswered === 2,
  JSON.stringify(demand.totals),
);
check(
  '自然文の質問がそのまま更新依頼リストに出る',
  demand.unanswered.some((x) => x.looking_for === '転入届の手数料はいくらですか'),
  JSON.stringify(demand.unanswered.map((x) => x.looking_for)),
);

console.log = realLog;
realLog(`\n結果: ${pass} PASS / ${fail} FAIL`);
process.exit(fail === 0 ? 0 : 1);
