// ChatGPT が実際に配っている公開鍵 (Web Bot Auth の JWKS ディレクトリ) を取得し、
// この実装でパース・インポートできるか（＝本物の鍵で検証形式が合うか）を確かめる。
// 実行: node gatekeeper/check_chatgpt_keys.mjs
import { importPublicJwk, jwkThumbprint } from './httpsig.mjs';

const URL_ = 'https://chatgpt.com/.well-known/http-message-signatures-directory';

const res = await fetch(URL_, { headers: { accept: 'application/http-message-signatures-directory+json, application/json' } });
console.log(`GET ${URL_}`);
console.log(`HTTP ${res.status} ${res.headers.get('content-type') || ''}`);
if (!res.ok) process.exit(1);

const body = await res.json();
console.log('\n生のレスポンス:');
console.log(JSON.stringify(body, null, 2));

const keys = body.keys || [];
console.log(`\n鍵の本数: ${keys.length}`);

let ok = true;
for (const jwk of keys) {
  console.log(`\n--- kty=${jwk.kty} crv=${jwk.crv} kid=${jwk.kid ?? '(なし)'} ---`);
  try {
    const key = await importPublicJwk(jwk);
    console.log(`WebCrypto インポート: 成功 (${key.algorithm.name})`);
    const thumb = await jwkThumbprint(jwk);
    console.log(`RFC 7638 指紋: ${thumb}`);
    if (jwk.kid) console.log(`kid と指紋の一致: ${jwk.kid === thumb ? '一致' : '不一致'}`);
    // ダミー署名を検証にかけ、例外を出さずに false が返ること（=検証呼び出しの形式互換）を確認
    const dummySig = new Uint8Array(64);
    const verdict = await crypto.subtle.verify(
      { name: 'Ed25519' },
      key,
      dummySig,
      new TextEncoder().encode('format-compatibility-probe'),
    );
    console.log(`ダミー署名の検証呼び出し: 例外なし・結果=${verdict}（false が正常）`);
  } catch (e) {
    ok = false;
    console.log(`失敗: ${e.message}`);
  }
}
process.exit(ok ? 0 : 1);
