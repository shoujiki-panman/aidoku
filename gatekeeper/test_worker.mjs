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
// 貯める側（KV）のスタブ。put のメタデータを持ち、list で返す。
const store = new Map();
const DEMAND = {
  put: async (key, _value, opts) => {
    store.set(key, opts?.metadata ?? null);
  },
  list: async ({ prefix = '', limit = 1000 } = {}) => ({
    keys: [...store.entries()]
      .filter(([k]) => k.startsWith(prefix))
      .slice(0, limit)
      .map(([name, metadata]) => ({ name, metadata })),
    list_complete: true,
  }),
};

const HOST = 'www.city.setagaya.lg.jp';
const EMPTY_PAGE = '/kurashi/kosekijuumin/11531.html'; // 実測で4項目とも読めなかったページ
const PARTIAL_PAGE = '/todokede/partial.html'; // 一部の項目だけ書いてあるページ
const env = {
  DEMAND,
  ANSWERS: {
    get: async (key) => {
      if (key === `${HOST}${PAGE}`) {
        return {
          procedure: '転入届',
          fields: {
            required_documents: '転出証明書、本人確認書類、マイナンバーカード',
            how_to_apply: '窓口のみ',
            deadline: '住み始めた日から14日以内',
            fee: '無料',
          },
        };
      }
      if (key === `${HOST}${PARTIAL_PAGE}`) {
        // 必要書類はあるが手数料が空。手数料を聞かれたら「取れずに帰った」になるべき
        return {
          procedure: '転入届',
          fields: {
            required_documents: '転出証明書、本人確認書類',
            how_to_apply: '窓口のみ',
            deadline: null,
            fee: null,
          },
        };
      }
      if (key === `${HOST}${EMPTY_PAGE}`) {
        // 実測データはあるが、そのページからは何も読み取れなかった
        return {
          procedure: '転入届',
          fields: { required_documents: null, how_to_apply: null, deadline: null, fee: null },
        };
      }
      return null;
    },
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
check('署名つきは整った答え(JSON)が返る', bodyA.answer?.fields?.fee === '無料', JSON.stringify(bodyA));
check(
  '記録が残る(何を探しに来て・取れたか・誰が)',
  records.length === 1 &&
    records[0].looking_for === '転入届 必要書類' &&
    records[0].answered === true &&
    records[0].verified === true &&
    records[0].agent === AGENT_ORIGIN &&
    records[0].path === PAGE,
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

// D. 署名つきだが答えが未整備のページ → 素通し＋「取れずに帰った」が記録される
const resD = await worker.fetch(
  new Request(`${SITE}/mimatomo.html?q=${encodeURIComponent('戸籍謄本 手数料')}`, { headers: signedHeaders }),
  env,
);
check('答えが未整備なら素通し', (await resD.text()).includes('元サイトのHTML'));
const lastD = records[records.length - 1];
check(
  '「取れずに帰った」が answered=false で記録される（このデータが主役）',
  lastD.answered === false && lastD.looking_for === '戸籍謄本 手数料' && lastD.verified === true,
  JSON.stringify(lastD),
);

// E. 実測データはあるが4項目とも読めなかったページ → 答えたふりをせず素通し＋取れずに帰った記録
const resE = await worker.fetch(
  new Request(`${SITE}${EMPTY_PAGE}?q=${encodeURIComponent('転入届 手数料')}`, { headers: signedHeaders }),
  env,
);
check('全項目nullの実測は「答えあり」にしない', (await resE.text()).includes('元サイトのHTML'));
const lastE = records[records.length - 1];
check(
  '全項目nullも answered=false で記録される',
  lastE.answered === false && lastE.path === EMPTY_PAGE,
  JSON.stringify(lastE),
);

// F. 集めたものがデータになって取り出せるか（これが門番の成果物）
const resF = await worker.fetch(new Request(`${SITE}/_aidoku/demand`), env);
const demand = await resF.json();
check(
  'データの取り出し口が集計を返す',
  demand.totals?.asks >= 3 && demand.totals.answered >= 1 && demand.totals.unanswered >= 2,
  JSON.stringify(demand.totals),
);
const missing = demand.unanswered.find((x) => x.looking_for === '戸籍謄本 手数料');
check(
  '取れずに帰った探し物が一覧に出る（＝区役所への更新依頼リスト）',
  missing && missing.unanswered_count >= 1 && missing.path === '/mimatomo.html',
  JSON.stringify(demand.unanswered),
);
check(
  '人（署名なし）のアクセスはデータに入らない',
  !demand.all.some((x) => x.looking_for === null && x.path === PAGE && x.count > 1),
  JSON.stringify(demand.all.map((x) => `${x.path}:${x.count}`)),
);

// G. 同じ探し物を繰り返すと件数が積み上がる（需要の大きさが見える）
for (let i = 0; i < 2; i++) {
  await worker.fetch(
    new Request(`${SITE}/mimatomo.html?q=${encodeURIComponent('戸籍謄本　手数料')}`, { headers: signedHeaders }),
    env,
  );
}
const demand2 = await (await worker.fetch(new Request(`${SITE}/_aidoku/demand`), env)).json();
const grown = demand2.unanswered.find((x) => x.looking_for === '戸籍謄本 手数料');
check(
  '同じ探し物は表記ゆれを吸収して数が積み上がる',
  grown && grown.unanswered_count === 3,
  JSON.stringify(grown),
);

// H. ページに答えの束はあるが、聞かれた項目だけ空 → 取れずに帰った扱い
const resH = await worker.fetch(
  new Request(`${SITE}${PARTIAL_PAGE}?q=${encodeURIComponent('転入届 手数料')}`, { headers: signedHeaders }),
  env,
);
const bodyH = await resH.json();
check(
  '聞かれた項目が空なら answered=false を返す（持っているぶんは渡す）',
  bodyH.answered === false && bodyH.answer?.fields?.required_documents,
  JSON.stringify(bodyH).slice(0, 160),
);
const resH2 = await worker.fetch(
  new Request(`${SITE}${PARTIAL_PAGE}?q=${encodeURIComponent('転入届 必要書類')}`, { headers: signedHeaders }),
  env,
);
check('同じページでも、書いてある項目を聞かれたら answered=true', (await resH2.json()).answered === true);

const demand3 = await (await worker.fetch(new Request(`${SITE}/_aidoku/demand`), env)).json();
check(
  '一部だけ空のページも、空の項目だけが更新依頼リストに出る',
  demand3.unanswered.some((x) => x.path === PARTIAL_PAGE && x.looking_for === '転入届 手数料') &&
    !demand3.unanswered.some((x) => x.path === PARTIAL_PAGE && x.looking_for === '転入届 必要書類'),
  JSON.stringify(demand3.unanswered.filter((x) => x.path === PARTIAL_PAGE)),
);

console.log = realLog;
realLog(`\n結果: ${pass} PASS / ${fail} FAIL`);
process.exit(fail === 0 ? 0 : 1);
