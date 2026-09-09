// 派生コンポーネント（@method 等）のテスト。
// 実行: node gatekeeper/test_derived.mjs
//
// 確かめたいことは1つ。
// 本物のChatGPTの署名の形（2026-09-09 の本番来訪で実測）が検証を通るか。
//   実測した signature-input:
//   sig1=("@authority" "@method" "signature-agent");created=...;keyid="...";alg="ed25519";...;tag="web-bot-auth"
//   従来は @authority しか派生コンポーネントに対応しておらず、base-construction-failed で
//   全来訪が unverified になっていた（本番の記録9件で実測）。
import worker from './worker.mjs';
import { generateKeyPair, jwkThumbprint, signRequest, verifyRequest } from './httpsig.mjs';

const AGENT_ORIGIN = 'https://agent.example';
const AUTHORITY = 'aidoku-gatekeeper.example.workers.dev';

let pass = 0;
let fail = 0;
const realLog = console.log;
function check(name, cond, detail = '') {
  if (cond) {
    pass++;
    realLog(`  PASS  ${name}`);
  } else {
    fail++;
    realLog(`  FAIL  ${name}  ${detail}`);
  }
}

const { publicKey, privateKey } = await generateKeyPair();
const pubJwk = await crypto.subtle.exportKey('jwk', publicKey);
const keyid = await jwkThumbprint(pubJwk);
const getKey = async (kid) => (kid === keyid ? publicKey : null);
const now = Math.floor(Date.now() / 1000);

realLog('テスト（部品）:');

// ChatGPTと同じ形（@authority @method signature-agent）が通る
{
  const headers = await signRequest({
    authority: AUTHORITY, agent: AGENT_ORIGIN, privateKey, keyid,
    created: now, expires: now + 300, method: 'GET',
  });
  check('署名対象の形がChatGPT実測と同じ',
    headers['signature-input'].includes('("@authority" "@method" "signature-agent")'),
    headers['signature-input']);
  const r = await verifyRequest({ authority: AUTHORITY, method: 'GET', headers, getKey });
  check('@method 入りの署名が検証を通る', r.ok === true, JSON.stringify(r));

  // メソッドが違えば落ちる（@method を署名対象に含める意味）
  const wrong = await verifyRequest({ authority: AUTHORITY, method: 'POST', headers, getKey });
  check('  └ メソッド改ざんは bad-signature', wrong.ok === false && wrong.reason === 'bad-signature', JSON.stringify(wrong));

  // 検証側に method が渡っていなければ、通すのではなく base-construction-failed に倒す
  const noMethod = await verifyRequest({ authority: AUTHORITY, headers, getKey });
  check('  └ method 未提供なら通さない', noMethod.ok === false && noMethod.reason === 'base-construction-failed', JSON.stringify(noMethod));
}

// 従来の形（@authority signature-agent）も引き続き通る（回帰なし）
{
  const headers = await signRequest({
    authority: AUTHORITY, agent: AGENT_ORIGIN, privateKey, keyid,
    created: now, expires: now + 300,
  });
  const r = await verifyRequest({ authority: AUTHORITY, method: 'GET', headers, getKey });
  check('従来の形（@methodなし）も通る', r.ok === true, JSON.stringify(r));
}

// 知らない派生コンポーネントは今までどおり base-construction-failed（黙って通さない）
{
  const headers = await signRequest({
    authority: AUTHORITY, agent: AGENT_ORIGIN, privateKey, keyid,
    created: now, expires: now + 300,
  });
  const forged = { ...headers, 'signature-input': headers['signature-input'].replace('"@authority"', '"@query"') };
  const r = await verifyRequest({ authority: AUTHORITY, method: 'GET', headers: forged, getKey });
  check('未対応の派生コンポーネントは通さない', r.ok === false && r.reason === 'base-construction-failed', JSON.stringify(r));
}

// --- 門番ごと（workerがrequestのmethod等を渡していること）---
realLog('テスト（門番ごと）:');

globalThis.fetch = async (input) => {
  const url = typeof input === 'string' ? input : input.url;
  if (url === `${AGENT_ORIGIN}/.well-known/http-message-signatures-directory`) {
    return new Response(
      JSON.stringify({ keys: [{ kty: 'OKP', crv: 'Ed25519', x: pubJwk.x, kid: keyid, use: 'sig' }] }),
    );
  }
  return new Response('<html>素通し先</html>', { headers: { 'content-type': 'text/html' } });
};

const records = [];
console.log = (line) => {
  try {
    records.push(JSON.parse(line));
  } catch {
    realLog(line);
  }
};

{
  const headers = await signRequest({
    authority: AUTHORITY, agent: AGENT_ORIGIN, privateKey, keyid,
    created: now, expires: now + 300, method: 'GET',
  });
  await worker.fetch(
    new Request(`https://${AUTHORITY}/web/index.html`, { headers }),
    { ANSWERS: { get: async () => null } },
  );
  const rec = records.at(-1);
  check('ChatGPT形の来訪が verified:true で記録される', rec?.verified === true && rec?.agent === AGENT_ORIGIN, JSON.stringify(rec));
}

console.log = realLog;
realLog(`\n${pass} 件通過 / ${fail} 件失敗`);
if (fail > 0) process.exit(1);
