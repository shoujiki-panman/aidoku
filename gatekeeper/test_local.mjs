// 門番の署名検証をローカルで一周させるテスト。
// 自前の鍵ペアで 署名 → 検証 を通し、暗号として動くことを証明する。
// 実行: node gatekeeper/test_local.mjs
import {
  generateKeyPair,
  importPublicJwk,
  jwkThumbprint,
  signRequest,
  verifyRequest,
} from './httpsig.mjs';

let pass = 0;
let fail = 0;
function check(name, cond, detail = '') {
  if (cond) {
    pass++;
    console.log(`  PASS  ${name}`);
  } else {
    fail++;
    console.log(`  FAIL  ${name}  ${detail}`);
  }
}

const AGENT = 'https://agent.example';
const AUTHORITY = 'www.city.setagaya.lg.jp';

// --- 鍵ペアを作り、keyid = JWK指紋 (RFC 7638) を計算 ---
const { publicKey, privateKey } = await generateKeyPair();
const pubJwk = await crypto.subtle.exportKey('jwk', publicKey);
const keyid = await jwkThumbprint(pubJwk);
console.log(`鍵ペア生成: Ed25519, keyid(JWK指紋)=${keyid}`);

// 門番側の鍵解決: JWKS ディレクトリの代わりにローカルの1鍵
const directory = new Map([[keyid, await importPublicJwk(pubJwk)]]);
const getKey = async (kid) => directory.get(kid) ?? null;

const now = Math.floor(Date.now() / 1000);
const headers = await signRequest({
  authority: AUTHORITY,
  agent: AGENT,
  privateKey,
  keyid,
  created: now,
  expires: now + 300,
});
console.log('\n署名済みリクエストのヘッダ:');
for (const [k, v] of Object.entries(headers)) console.log(`  ${k}: ${v}`);

console.log('\nテスト:');

// 1. 正しい署名 → 検証が通る
const r1 = await verifyRequest({ authority: AUTHORITY, headers, getKey });
check('正しい署名は verified になる', r1.ok && r1.reason === 'verified', JSON.stringify(r1));

// 2. authority を改ざん → 落ちる（署名は宛先に縛られている）
const r2 = await verifyRequest({ authority: 'www.city.minato.tokyo.jp', headers, getKey });
check('宛先(authority)を変えると bad-signature', !r2.ok && r2.reason === 'bad-signature', JSON.stringify(r2));

// 3. Signature-Agent を改ざん → 落ちる（名乗りも署名対象）
const r3 = await verifyRequest({
  authority: AUTHORITY,
  headers: { ...headers, 'signature-agent': '"https://evil.example"' },
  getKey,
});
check('名乗り(signature-agent)を変えると bad-signature', !r3.ok && r3.reason === 'bad-signature', JSON.stringify(r3));

// 4. 期限切れ → expired で拒否
const expiredHeaders = await signRequest({
  authority: AUTHORITY,
  agent: AGENT,
  privateKey,
  keyid,
  created: now - 600,
  expires: now - 300,
});
const r4 = await verifyRequest({ authority: AUTHORITY, headers: expiredHeaders, getKey });
check('期限切れは expired で拒否', !r4.ok && r4.reason === 'expired', JSON.stringify(r4));

// 5. 知らない鍵 → unknown-key
const r5 = await verifyRequest({ authority: AUTHORITY, headers, getKey: async () => null });
check('未知の keyid は unknown-key', !r5.ok && r5.reason === 'unknown-key', JSON.stringify(r5));

// 6. 署名なし（普通のブラウザ）→ no-signature（拒否ではなく素通し判定に使う）
const r6 = await verifyRequest({ authority: AUTHORITY, headers: { 'user-agent': 'Mozilla/5.0' }, getKey });
check('署名なしは no-signature', !r6.ok && r6.reason === 'no-signature', JSON.stringify(r6));

// 7. 別人の鍵で署名（keyid だけ本物を名乗る）→ 落ちる
const impostor = await generateKeyPair();
const forged = await signRequest({
  authority: AUTHORITY,
  agent: AGENT,
  privateKey: impostor.privateKey,
  keyid, // 本物の keyid を騙る
  created: now,
  expires: now + 300,
});
const r7 = await verifyRequest({ authority: AUTHORITY, headers: forged, getKey });
check('他人の鍵で本物の keyid を騙ると bad-signature', !r7.ok && r7.reason === 'bad-signature', JSON.stringify(r7));

// --- 記録レコードの形（門番が貯めるデータ）---
const record = {
  ts: new Date().toISOString(),
  agent: r1.agent, // どのエージェントが（署名で証明済み）
  keyid: r1.keyid,
  authority: AUTHORITY, // どの自治体サイトに
  path: '/kurashi/tetsuduki/tennyu.html', // どのページへ
  looking_for: '転入届 必要書類 期限 手数料', // 何を探しに来たか（クエリ/ボディから）
  verified: r1.ok,
};
console.log('\n門番が貯める記録レコード（例）:');
console.log(JSON.stringify(record, null, 2));

console.log(`\n結果: ${pass} PASS / ${fail} FAIL`);
process.exit(fail === 0 ? 0 : 1);
