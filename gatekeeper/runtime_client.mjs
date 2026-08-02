// 本番ランタイム(workerd)で動いている門番に、外から実リクエストを送って確かめる。
//
//   端末1: npx wrangler dev -c runtime_check.wrangler.jsonc --local-protocol https --port 8787
//   端末2: node runtime_client.mjs
//
// test_worker.mjs との違いは「関数を呼ぶ」ではなく「HTTPで送る」こと。
// 署名ヘッダは実際にネットワークを通り、鍵は門番が JWKS を取りに来て解決する。
import { readFile } from 'node:fs/promises';
import { generateKeyPair, signRequest, jwkThumbprint } from './httpsig.mjs';

// テスト用エージェントの鍵は固定にしてある。
// 門番は JWKS を1時間キャッシュする設計なので、実行のたびに新しい鍵を作ると
// 2回目以降が unknown-key で落ちる（＝キャッシュが正しく効いている証拠でもある）。
// これは検証用の使い捨て鍵で、秘密ではない。本番の鍵をここに置かないこと。
const TEST_AGENT_JWK = {
  kty: 'OKP',
  crv: 'Ed25519',
  x: 'vugdnKA1cJHoltd14xkdSqtkmzQblOzkO3u1s01TjTE',
  d: 'hoEnGNKVCCOtfoerH7JDUseK-Pb2gGvBB1FKl7kV1Lg',
};

async function loadTestAgentKey() {
  const privateKey = await crypto.subtle.importKey('jwk', TEST_AGENT_JWK, { name: 'Ed25519' }, false, [
    'sign',
  ]);
  const publicJwk = { kty: 'OKP', crv: 'Ed25519', x: TEST_AGENT_JWK.x };
  return { privateKey, publicJwk, keyid: await jwkThumbprint(publicJwk) };
}

// wrangler dev の https は自己署名証明書。ローカル実測なのでここだけ許す。
process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';

const BASE = process.env.GATEKEEPER_BASE ?? 'https://localhost:8787';
const AUTHORITY = new URL(BASE).host;

let pass = 0;
let fail = 0;
function check(name, ok, detail) {
  if (ok) {
    pass++;
    console.log(`  PASS  ${name}`);
  } else {
    fail++;
    console.log(`  FAIL  ${name}${detail ? `  -> ${JSON.stringify(detail)}` : ''}`);
  }
}

// 素通しのときはHTMLが返る。JSONで無いことをそのまま失敗として見せる
async function asJson(res) {
  const text = await res.text();
  try {
    return JSON.parse(text);
  } catch {
    return { __notJson: text.slice(0, 120) };
  }
}

async function signedFetch(path, { privateKey, keyid, agent, authority = AUTHORITY, expires }) {
  const now = Math.floor(Date.now() / 1000);
  const headers = await signRequest({
    authority,
    agent,
    privateKey,
    keyid,
    created: now,
    expires: expires ?? now + 300,
  });
  return fetch(`${BASE}${path}`, { headers });
}

const main = async () => {
  // --- 1. workerd の中の暗号 ---------------------------------------------
  const c = await (await fetch(`${BASE}/_check/crypto`)).json();
  check('workerd の中で 鍵生成→署名→検証 が一周する', c.ok, c.steps);
  for (const s of c.steps ?? []) check(`  └ ${s.step}`, s.ok, s.reason);

  // --- 2. workerd の中から本物の鍵 ---------------------------------------
  const g = await (await fetch(`${BASE}/_check/chatgpt`)).json();
  check('workerd の中から ChatGPT の実鍵を取得・インポートできる', g.ok, g);
  if (g.keys?.[0]) check('  └ kid と RFC 7638 指紋が一致', g.keys[0].matches, g.keys[0]);

  // --- 3. テスト用エージェントを用意して名乗らせる -------------------------
  const { privateKey, publicJwk, keyid } = await loadTestAgentKey();
  const agent = BASE; // 鍵をこのオリジンで配る＝自分で名乗って自分で鍵を出す
  const reg = await (
    await fetch(`${BASE}/_check/register`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ ...publicJwk, kid: keyid, use: 'sig' }),
    })
  ).json();
  check('テスト用エージェントの公開鍵を JWKS として配れる', reg.ok === true, reg);

  // --- 4. 実測の答えを KV に入れる ----------------------------------------
  // 新宿区: オンライン可否は書いてあるが、手数料は書かれていない（実測値）
  const shinjuku = JSON.parse(
    await readFile(new URL('./answers/shinjuku.json', import.meta.url), 'utf8'),
  );
  const KEY_PATH = '/todokede/tennyu';
  const seed = await (
    await fetch(`${BASE}/_check/seed`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ key: `${AUTHORITY}${KEY_PATH}`, value: shinjuku }),
    })
  ).json();
  check('実測の答えを KV(ANSWERS) に入れられる', seed.ok === true, seed);

  // --- 5. 署名つきの実リクエストを門番に送る -------------------------------
  // 5-a: 書いてある項目を聞く → 取れて帰る
  const r1 = await signedFetch(`${KEY_PATH}?q=${encodeURIComponent('転入届 オンライン')}`, {
    privateKey,
    keyid,
    agent,
  });
  const b1 = await asJson(r1);
  check('署名つきの実リクエストに、整った答え(JSON)が返る', r1.status === 200 && !!b1.answer, {
    status: r1.status,
  });
  check('  └ 書いてある項目を聞いたら answered=true', b1.answered === true, b1.answered);
  check('  └ 返ってきたのは実測値そのもの', b1.answer?.municipality === '新宿区', b1.answer?.municipality);

  // 5-b: 書かれていない項目を聞く → 取れずに帰る（これが主役のデータ）
  const r2 = await signedFetch(`${KEY_PATH}?q=${encodeURIComponent('転入届 手数料')}`, {
    privateKey,
    keyid,
    agent,
  });
  const b2 = await asJson(r2);
  check('  └ 書かれていない項目を聞いたら answered=false', b2.answered === false, b2.answered);
  check('  └ 空の項目を隠さず null で返す', b2.answer?.fields?.fee === null, b2.answer?.fields?.fee);

  // 5-c: 期限切れの署名 → 素通し（答えは返さない）
  const now = Math.floor(Date.now() / 1000);
  const r3 = await signedFetch(`${KEY_PATH}?q=${encodeURIComponent('転入届 手数料')}`, {
    privateKey,
    keyid,
    agent,
    expires: now - 10,
  });
  const t3 = await r3.text();
  check('期限切れの署名には整った答えを返さない', !t3.includes('"answered"'), t3.slice(0, 80));

  // 5-d: 他人の鍵で本物の keyid を騙る → 検証失敗
  const impostor = await generateKeyPair();
  const r4 = await signedFetch(`${KEY_PATH}?q=${encodeURIComponent('転入届 手数料')}`, {
    privateKey: impostor.privateKey, // 署名は偽物の鍵
    keyid, // でも名乗る keyid は本物
    agent,
  });
  const t4 = await r4.text();
  check('他人の鍵で keyid を騙っても答えは出ない', !t4.includes('"answered"'), t4.slice(0, 80));

  // --- 6. 集めたものがデータになっているか ---------------------------------
  const d = await (await fetch(`${BASE}/_aidoku/demand`)).json();
  check('KV に貯まった記録が集計されて返る', !!d, d);
  const missed = JSON.stringify(d?.unanswered ?? d ?? {});
  check('  └ 取れずに帰った探し物が一覧に出る', missed.includes('手数料'), missed.slice(0, 200));

  console.log(`\n結果: ${pass} PASS / ${fail} FAIL`);
  console.log('\n--- /_aidoku/demand の中身 ---');
  console.log(JSON.stringify(d, null, 2));
  if (fail > 0) process.exitCode = 1;
};

main().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
