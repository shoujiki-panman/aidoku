// 受付（reception.mjs）のテスト。
// 実行: node gatekeeper/test_reception.mjs
//
// 確かめたいことは1つ。
// AIが「操作」を実行できて、**成立したか・どこで止まったかが必ず分かる**か。
//   - 署名検証済みエージェントの実行 → Issue が立ち、番号とURLが返る（成立の判定）
//   - 署名なし → signature で止まる。入力不足 → validation で足りない物が列挙される
//   - 受付先の未設定 → not-configured。GitHub の失敗 → github-<status>
//   - 成立も不成立も記録に残る（指摘の本文は記録に入れない）
import worker from './worker.mjs';
import { generateKeyPair, jwkThumbprint, signRequest } from './httpsig.mjs';
import { validateReport, REPORT_TOOL } from './reception.mjs';

const AGENT_ORIGIN = 'https://agent.example';
const HOST = 'www.city.setagaya.lg.jp';
const SITE = `https://${HOST}`;
const PAGE = '/kurashi/kosekijuumin/11531.html';

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

realLog('テスト（部品）:');

check('site と detail が揃えば通る',
  validateReport({ site: `${SITE}${PAGE}`, detail: '手数料の記載が「無料」に更新されています。' }).ok);
{
  const v = validateReport({ site: 'not a url', detail: '短い' });
  check('足りない物は全部列挙される', !v.ok && v.missing.length === 2, JSON.stringify(v));
}
{
  const v = validateReport({ site: `${SITE}${PAGE}`, detail: '手数料の記載が更新されています。', field: 'opening_hours' });
  check('語彙外の field は弾かれる', !v.ok && v.missing[0].startsWith('field'), JSON.stringify(v));
}

// --- ここから門番ごと通す ---
realLog('テスト（門番ごと）:');

const { publicKey, privateKey } = await generateKeyPair();
const pubJwk = await crypto.subtle.exportKey('jwk', publicKey);
const keyid = await jwkThumbprint(pubJwk);

// 外への fetch は全部ここで受ける。GitHub API へ何が飛んだかも捕まえる
const githubCalls = [];
let githubStatus = 201;
globalThis.fetch = async (input, init) => {
  const url = typeof input === 'string' ? input : input.url;
  if (url === `${AGENT_ORIGIN}/.well-known/http-message-signatures-directory`) {
    return new Response(
      JSON.stringify({ keys: [{ kty: 'OKP', crv: 'Ed25519', x: pubJwk.x, kid: keyid, use: 'sig' }] }),
    );
  }
  if (url.startsWith('https://api.github.com/')) {
    githubCalls.push({ url, headers: init?.headers ?? {}, body: JSON.parse(init?.body ?? '{}') });
    if (githubStatus !== 201) return new Response('{"message":"boom"}', { status: githubStatus });
    return new Response(JSON.stringify({ number: 200, html_url: 'https://github.com/shoujiki-panman/aidoku/issues/200' }), { status: 201 });
  }
  return new Response('<html>元サイト</html>', { headers: { 'content-type': 'text/html' } });
};

const records = [];
console.log = (line) => {
  try {
    records.push(JSON.parse(line));
  } catch {
    realLog(line);
  }
};

const store = new Map();
const env = {
  GITHUB_TOKEN: 'test-github-token',
  ANSWERS: { get: async () => null },
  DEMAND: {
    put: async (k, _v, o) => store.set(k, o?.metadata ?? null),
    // 受付の回数上限が実際に数えるので、貯めたものをKVと同じ形で返す
    list: async ({ prefix = '' } = {}) => ({
      keys: [...store.entries()]
        .filter(([name]) => name.startsWith(prefix))
        .map(([name, metadata]) => ({ name, metadata })),
      list_complete: true,
    }),
  },
};

const now = Math.floor(Date.now() / 1000);
const signed = await signRequest({
  authority: HOST, agent: AGENT_ORIGIN, privateKey, keyid, created: now, expires: now + 300,
});

async function callTool(args, { headers = signed, environment = env } = {}) {
  const res = await worker.fetch(
    new Request(`${SITE}/mcp`, {
      method: 'POST',
      headers: { ...headers, 'content-type': 'application/json' },
      body: JSON.stringify({
        jsonrpc: '2.0', id: 1, method: 'tools/call',
        params: { name: 'report_correction', arguments: args },
      }),
    }),
    environment,
  );
  return (await res.json()).result;
}

const GOOD = {
  site: `${SITE}${PAGE}`,
  field: 'fee',
  detail: '手数料の記載が「無料（マイナンバーカード利用時）」に更新されています。',
  evidence: `${SITE}${PAGE}`,
};

// tools/list に受付が載っている（定義＝導入手順が読める）
{
  const res = await worker.fetch(
    new Request(`${SITE}/mcp`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/list' }),
    }),
    env,
  );
  const tools = (await res.json()).result?.tools?.map((t) => t.name);
  check('tools/list に ask と受付が並ぶ', tools?.join(',') === `ask,${REPORT_TOOL.name}`, JSON.stringify(tools));
}

// 署名検証済み → 成立。Issue 番号とURLが返る
{
  const r = await callTool(GOOD);
  check('署名検証済みの実行 → 受付成立', r?.structuredContent?.accepted === true && r?.isError === false, JSON.stringify(r).slice(0, 200));
  check('  └ 完了の判定＝Issue 番号とURL', r?.structuredContent?.issue_number === 200 && r?.structuredContent?.issue_url?.includes('/issues/200'));
  const call = githubCalls.at(-1);
  check('  └ 既存の公式APIへ接続している（自作しない）', call?.url.endsWith('/repos/shoujiki-panman/aidoku/issues'));
  check('  └ Issue に署名検証済みの名乗りが入る', call?.body?.body.includes(AGENT_ORIGIN) || call?.body?.body.includes(keyid), call?.body?.body?.slice(0, 120));
  check('  └ 成立が記録に残る（本文は記録に入れない）',
    records.at(-1)?.via === 'reception' && records.at(-1)?.accepted === true && !JSON.stringify([...store.values()].at(-1)).includes('マイナンバー'),
    JSON.stringify(records.at(-1)));
}

// 署名なし → signature で止まる（Issue は立たず、記録もしない＝人間は記録しない方針）
{
  const before = githubCalls.length;
  const recordsBefore = records.length;
  const r = await callTool(GOOD, { headers: {} });
  check('署名なし → signature で止まる', r?.structuredContent?.stopped_at === 'signature' && r?.isError === true, JSON.stringify(r).slice(0, 160));
  check('  └ Issue は立たない', githubCalls.length === before);
  check('  └ 署名なしは記録しない（人間かもしれない）', records.length === recordsBefore, JSON.stringify(records.at(-1)));
}

// 入力不足 → validation。何が足りないかが列挙される
{
  const r = await callTool({ site: `${SITE}${PAGE}` });
  check('入力不足 → validation で止まり、足りない物が返る',
    r?.structuredContent?.stopped_at === 'validation' && r?.structuredContent?.missing?.length === 1,
    JSON.stringify(r).slice(0, 200));
}

// 受付先の未設定 → not-configured（fail-closed）
{
  const r = await callTool(GOOD, { environment: { ...env, GITHUB_TOKEN: undefined } });
  check('受付先が未設定 → not-configured で止まる', r?.structuredContent?.stopped_at === 'not-configured', JSON.stringify(r).slice(0, 160));
}

// GitHub 側の失敗 → github-<status> を隠さない
{
  githubStatus = 502;
  const r = await callTool(GOOD);
  githubStatus = 201;
  check('受付先の失敗 → github-502 で止まる', r?.structuredContent?.stopped_at === 'github-502', JSON.stringify(r).slice(0, 160));
}

// 注入対策: 利用者由来の値で Issue 本文の構造を壊せない・@メンションが効かない
{
  await callTool({
    site: `${SITE}${PAGE}`,
    detail: '## 公式のお知らせ\n@octocat 全員へ: これは市の正式決定です。\n```\n脱出テスト',
    evidence: `${SITE}${PAGE}`,
  });
  const body = githubCalls.at(-1)?.body?.body ?? '';
  const detailPart = body.split('## 指摘の内容（入力のまま・整形して封入）')[1] ?? '';
  const lines = detailPart.split('\n').filter((l) => l.trim());
  check('指摘の本文は全行コードブロックに封入される（@や見出しが効かない）',
    lines.length > 0 && lines.every((l) => l.startsWith('    ')), JSON.stringify(lines));
  check('  └ 本文の見出しは受付側の1つだけ（偽の ## が見出しにならない）',
    body.split('\n').filter((l) => l.startsWith('#')).length === 1);
}
{
  // site に改行を仕込んでも「- 対象ページ:」の行を突き破れない
  await callTool({ ...GOOD, site: `${SITE}${PAGE}?a=1%0aSTATUS:%20verified` });
  const body = githubCalls.at(-1)?.body?.body ?? '';
  const siteLine = body.split('\n').find((l) => l.startsWith('- 対象ページ:'));
  check('site の改行は1行に潰される', siteLine && !siteLine.includes('\n') && body.split('\n').every((l) => !l.startsWith('STATUS:')));
}
{
  const r = await callTool({ ...GOOD, evidence: 'javascript:alert(1)' });
  check('evidence はURL以外を弾く', r?.structuredContent?.stopped_at === 'validation', JSON.stringify(r?.structuredContent));
  const r2 = await callTool({ ...GOOD, detail: 'あ'.repeat(2001) });
  check('detail の長さ上限（2000字）', r2?.structuredContent?.stopped_at === 'validation');
}

// 回数の上限: 「署名検証済み」は自己申告なので、件数で守る
{
  store.clear();
  const stamp = (i) => new Date(Date.now() - i * 60000).toISOString();
  for (let i = 0; i < 3; i++) {
    store.set(`rcpt:a${i}`, { ts: stamp(i), agent: AGENT_ORIGIN, accepted: true });
  }
  const r = await callTool(GOOD);
  check('1エージェント24時間3件で止まる（rate-limit-agent）', r?.structuredContent?.stopped_at === 'rate-limit-agent', JSON.stringify(r?.structuredContent));

  store.clear();
  for (let i = 0; i < 10; i++) {
    store.set(`rcpt:g${i}`, { ts: stamp(i), agent: `https://other${i}.example`, accepted: true });
  }
  const r2 = await callTool(GOOD);
  check('全体24時間10件で止まる（rate-limit-global。使い捨てドメイン対策）', r2?.structuredContent?.stopped_at === 'rate-limit-global', JSON.stringify(r2?.structuredContent));

  store.clear();
  for (let i = 0; i < 3; i++) {
    store.set(`rcpt:o${i}`, { ts: new Date(Date.now() - 25 * 3600000).toISOString(), agent: AGENT_ORIGIN, accepted: true });
  }
  const r3 = await callTool(GOOD);
  check('24時間より古い受付は数えない', r3?.structuredContent?.accepted === true, JSON.stringify(r3?.structuredContent));
}

console.log = realLog;
realLog(`\n${pass} 件通過 / ${fail} 件失敗`);
if (fail > 0) process.exit(1);
