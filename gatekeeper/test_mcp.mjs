// MCP の窓口（POST /mcp）のテスト。
// 仕様: https://modelcontextprotocol.io/specification/2025-06-18
// ツール名と引数は NLWeb 仕様 Appendix A（ask / query・context・prefer・meta）。
// 実行: node gatekeeper/test_mcp.mjs
import worker from './worker.mjs';
import { generateKeyPair, jwkThumbprint, signRequest } from './httpsig.mjs';
import { PROTOCOL_VERSION } from './mcp.mjs';

const AGENT_ORIGIN = 'https://agent.example';
const HOST = 'www.city.shinjuku.lg.jp';
const SITE = `https://${HOST}`;
const PAGE = '/todokede/tennyu.html';

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

async function rpc(message, headers = signed) {
  const res = await worker.fetch(
    new Request(`${SITE}/mcp`, {
      method: 'POST',
      headers: { ...headers, 'content-type': 'application/json' },
      body: JSON.stringify(message),
    }),
    env,
  );
  const text = await res.text();
  let body = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = { __notJson: text.slice(0, 120) };
  }
  return { res, body };
}

realLog('テスト:');

// 1. initialize（仕様どおりの握手）
const init = await rpc({
  jsonrpc: '2.0',
  id: 1,
  method: 'initialize',
  params: { protocolVersion: PROTOCOL_VERSION, capabilities: {}, clientInfo: { name: 'test', version: '1' } },
});
check('initialize が返る', init.body?.result?.protocolVersion === PROTOCOL_VERSION, JSON.stringify(init.body).slice(0, 160));
check('  └ tools を持っていると申告する', !!init.body.result.capabilities?.tools, JSON.stringify(init.body.result.capabilities));
check('  └ serverInfo がある', !!init.body.result.serverInfo?.name, JSON.stringify(init.body.result.serverInfo));
check(
  '  └ 行政の公式発表ではない旨を最初に伝える',
  init.body.result.instructions?.includes('公式発表ではありません'),
  '',
);

// 2. 知らない版を出されたら、こちらが対応している版を返す（仕様どおり）
const init2 = await rpc({ jsonrpc: '2.0', id: 2, method: 'initialize', params: { protocolVersion: '1.0.0' } });
check('知らない版には自分の対応版を返す', init2.body?.result?.protocolVersion === PROTOCOL_VERSION, JSON.stringify(init2.body?.result?.protocolVersion));

// 3. 通知には本文を返さない
const note = await rpc({ jsonrpc: '2.0', method: 'notifications/initialized' });
check('通知には本文を返さない（202）', note.res.status === 202 && !note.body, String(note.res.status));

// 4. tools/list（NLWeb 仕様の ask ツール）
const list = await rpc({ jsonrpc: '2.0', id: 3, method: 'tools/list' });
const tool = list.body?.result?.tools?.[0];
check('tools/list が ask ツールを返す', tool?.name === 'ask', JSON.stringify(list.body).slice(0, 160));
check('  └ 引数は NLWeb 仕様の query（必須）', tool?.inputSchema?.required?.includes('query'), JSON.stringify(tool?.inputSchema?.required));
check(
  '  └ query.text が必須',
  tool?.inputSchema?.properties?.query?.required?.includes('text'),
  JSON.stringify(tool?.inputSchema?.properties?.query?.required),
);

// 5. tools/call → 書いてある項目
const call1 = await rpc({
  jsonrpc: '2.0',
  id: 4,
  method: 'tools/call',
  params: { name: 'ask', arguments: { query: { text: '転入届はオンラインでできますか', site: PAGE } } },
});
check('tools/call で答えが返る', call1.body?.result?.structuredContent?._meta?.response_type === 'answer', JSON.stringify(call1.body).slice(0, 160));
check('  └ 後方互換のため text にも同じJSONが入る', JSON.parse(call1.body.result.content[0].text)._meta.response_type === 'answer', '');
check('  └ 実測値が入っている', call1.body.result.structuredContent.results[0].provider?.name === '新宿区', '');
check('  └ isError は false', call1.body.result.isError === false, String(call1.body.result.isError));

// 6. tools/call → 書かれていない項目（主役のデータ）
const call2 = await rpc({
  jsonrpc: '2.0',
  id: 5,
  method: 'tools/call',
  params: { name: 'ask', arguments: { query: { text: '転入届の手数料はいくらですか', site: PAGE } } },
});
check('書かれていない項目は failure(NO_RESULTS)', call2.body.result.structuredContent.error?.code === 'NO_RESULTS', '');
check(
  '  └ 「そのページに無い」は失敗ではないので isError は false',
  call2.body.result.isError === false,
  String(call2.body.result.isError),
);
check(
  '  └ MCP 経由でも「取れずに帰った」が記録される',
  records.at(-1)?.answered === false && records.at(-1)?.via === 'mcp',
  JSON.stringify(records.at(-1)),
);

// 7. tools/call → 曖昧な問いは聞き返す
const call3 = await rpc({
  jsonrpc: '2.0',
  id: 6,
  method: 'tools/call',
  params: { name: 'ask', arguments: { query: { text: '転入届について教えてください', site: PAGE } } },
});
check('曖昧な問いは elicitation で聞き返す', call3.body.result.structuredContent._meta.response_type === 'elicitation', '');
check('  └ 「取れた」に数えない（answered=null）', records.at(-1)?.answered === null, JSON.stringify(records.at(-1)?.answered));

// 8. 規格どおりのエラー
const unknownTool = await rpc({ jsonrpc: '2.0', id: 7, method: 'tools/call', params: { name: 'delete_everything' } });
check('知らないツールは -32602', unknownTool.body?.error?.code === -32602, JSON.stringify(unknownTool.body?.error));

const badArgs = await rpc({ jsonrpc: '2.0', id: 8, method: 'tools/call', params: { name: 'ask', arguments: {} } });
check('query が無ければ -32602', badArgs.body?.error?.code === -32602, JSON.stringify(badArgs.body?.error));

const unknownMethod = await rpc({ jsonrpc: '2.0', id: 9, method: 'resources/list' });
check('知らないメソッドは -32601', unknownMethod.body?.error?.code === -32601, JSON.stringify(unknownMethod.body?.error));

const broken = await worker.fetch(
  new Request(`${SITE}/mcp`, { method: 'POST', headers: signed, body: 'これはJSONではない' }),
  env,
);
check('壊れた body でも門番は落ちず -32700', (await broken.json()).error?.code === -32700, '');

// 9. 署名なし（人間）は記録しない
const before = records.length;
await rpc(
  {
    jsonrpc: '2.0',
    id: 10,
    method: 'tools/call',
    params: { name: 'ask', arguments: { query: { text: '転入届の手数料はいくらですか', site: PAGE } } },
  },
  { 'user-agent': 'Mozilla/5.0' },
);
check('署名なしは記録しない（住民のデータは集めない）', records.length === before, `${before} -> ${records.length}`);

// 10. 集計は口が違っても同じ場所に貯まる
const demand = await (await worker.fetch(new Request(`${SITE}/_aidoku/demand`), env)).json();
check(
  'MCP で聞かれた分も更新依頼リストに出る',
  demand.unanswered.some((x) => x.looking_for === '転入届の手数料はいくらですか'),
  JSON.stringify(demand.unanswered.map((x) => x.looking_for)),
);

console.log = realLog;
realLog(`\n結果: ${pass} PASS / ${fail} FAIL`);
process.exit(fail === 0 ? 0 : 1);
