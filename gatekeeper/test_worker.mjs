// worker.mjs（門番本体）をローカルで一周させるテスト。
// ネットワークは使わず、fetch をスタブして JWKS 配布と元サイトを演じる。
// 実行: node gatekeeper/test_worker.mjs
import worker from './worker.mjs';
import { generateKeyPair, jwkThumbprint, signRequest } from './httpsig.mjs';

const AGENT_ORIGIN = 'https://agent.example';
const SITE = 'https://www.city.setagaya.lg.jp';
const PAGE = '/kurashi/tetsuduki/tennyu.html';

// --- エージェントの鍵ペアと JWKS ディレクトリ ---
const { publicKey, privateKey } = await generateKeyPair();
const pubJwk = await crypto.subtle.exportKey('jwk', publicKey);
const keyid = await jwkThumbprint(pubJwk);
const jwks = {
  keys: [{ kty: 'OKP', crv: 'Ed25519', x: pubJwk.x, kid: keyid, use: 'sig' }],
  signature_agent: AGENT_ORIGIN,
  purpose: 'ai',
};

// --- fetch をスタブ: JWKS 配布と元サイトを演じる ---
const realFetch = globalThis.fetch;
globalThis.fetch = async (input) => {
  const url = typeof input === 'string' ? input : input.url;
  if (url === `${AGENT_ORIGIN}/.well-known/http-message-signatures-directory`) {
    return new Response(JSON.stringify(jwks), {
      headers: { 'content-type': 'application/http-message-signatures-directory+json' },
    });
  }
  if (url.startsWith(SITE)) {
    return new Response('<html>元サイトのHTML</html>', { headers: { 'content-type': 'text/html' } });
  }
  // 上記以外（偽エージェントの鍵配布URLなど）は存在しない扱い
  return new Response('not found', { status: 404 });
};

// --- console.log を捕まえて記録レコードを検証 ---
const records = [];
const realLog = console.log;
console.log = (line) => {
  try {
    records.push(JSON.parse(line));
  } catch {
    realLog(line);
  }
};

// --- 整った答え（AI読の実測データを流用する想定のモック）---
const env = {
  ANSWERS: {
    get: async (path) =>
      path === PAGE
        ? {
            procedure: '転入届',
            required_documents: '転出証明書、本人確認書類、マイナンバーカード',
            deadline: '住み始めた日から14日以内',
            fee: '無料',
          }
        : null,
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
const signedHeaders = await signRequest({
  authority: 'www.city.setagaya.lg.jp',
  agent: AGENT_ORIGIN,
  privateKey,
  keyid,
  created: now,
  expires: now + 300,
});

realLog('テスト:');

// A. 署名つき＋答えがあるページ → JSON の整った答え＋記録
const resA = await worker.fetch(
  new Request(`${SITE}${PAGE}?q=${encodeURIComponent('転入届 必要書類')}`, { headers: signedHeaders }),
  env,
);
const bodyA = await resA.json();
check('署名つきは整った答え(JSON)が返る', bodyA.answer?.fee === '無料', JSON.stringify(bodyA));
check(
  '記録が残る(誰が・どこへ・何を)',
  records.length === 1 &&
    records[0].verified === true &&
    records[0].agent === AGENT_ORIGIN &&
    records[0].path === PAGE &&
    records[0].looking_for === '転入届 必要書類',
  JSON.stringify(records),
);

// B. 署名なし（人間のブラウザ）→ 元サイトへ素通し・記録なし
const before = records.length;
const resB = await worker.fetch(new Request(`${SITE}${PAGE}`), env);
const bodyB = await resB.text();
check('署名なしは元サイトへ素通し', bodyB.includes('元サイトのHTML'), bodyB.slice(0, 80));
check('署名なしは記録しない（住民のデータは集めない）', records.length === before);

// C. 改ざんされた署名 → 素通しだが verified=false で記録
const resC = await worker.fetch(
  new Request(`${SITE}/other.html`, {
    headers: { ...signedHeaders, 'signature-agent': '"https://evil.example"' },
  }),
  env,
);
const bodyC = await resC.text();
check('検証失敗は素通し（門番は拒否しない）', bodyC.includes('元サイトのHTML'), bodyC.slice(0, 80));
const last = records[records.length - 1];
check('検証失敗も verified=false で記録される', records.length === before + 1 && last.verified === false, JSON.stringify(last));

// D. 署名つきだが答えが未整備のページ → 素通し＋記録
const resD = await worker.fetch(new Request(`${SITE}/mimatomo.html`, { headers: signedHeaders }), env);
check('答えが未整備なら素通し', (await resD.text()).includes('元サイトのHTML'));

console.log = realLog;
realLog(`\n結果: ${pass} PASS / ${fail} FAIL`);
process.exit(fail === 0 ? 0 : 1);
