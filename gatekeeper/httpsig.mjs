// RFC 9421 (HTTP Message Signatures) の最小実装。
// Web Bot Auth (draft-meunier-web-bot-auth-architecture) が使う範囲だけを扱う:
//   - 署名対象コンポーネント: "@authority" と "signature-agent"
//   - アルゴリズム: Ed25519（WebCrypto。Node v24 / Cloudflare Workers 共通）
//   - keyid: JWK 指紋 (RFC 7638) または JWKS の kid
//
// Node でもWorkerでも動くよう、依存は WebCrypto (globalThis.crypto) のみ。

const enc = new TextEncoder();

// ---- base64 helpers -------------------------------------------------------

export function b64ToBytes(s) {
  return Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
}

export function bytesToB64(bytes) {
  let bin = '';
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin);
}

export function bytesToB64u(bytes) {
  return bytesToB64(bytes).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

// ---- 鍵まわり --------------------------------------------------------------

export async function generateKeyPair() {
  return crypto.subtle.generateKey({ name: 'Ed25519' }, true, ['sign', 'verify']);
}

// JWKS の1エントリ (kty=OKP, crv=Ed25519, x=...) を検証鍵として取り込む
export async function importPublicJwk(jwk) {
  return crypto.subtle.importKey(
    'jwk',
    { kty: jwk.kty, crv: jwk.crv, x: jwk.x },
    { name: 'Ed25519' },
    true,
    ['verify'],
  );
}

// RFC 7638 の JWK 指紋。OKP は {"crv","kty","x"} を辞書順で並べて SHA-256
export async function jwkThumbprint(jwk) {
  const json = JSON.stringify({ crv: jwk.crv, kty: jwk.kty, x: jwk.x });
  const hash = await crypto.subtle.digest('SHA-256', enc.encode(json));
  return bytesToB64u(new Uint8Array(hash));
}

// ---- 署名ベース (RFC 9421 §2.5) --------------------------------------------

export function buildSignatureBase(components, valueOf, paramsRaw) {
  const lines = components.map((c) => `"${c}": ${valueOf(c)}`);
  lines.push(`"@signature-params": ${paramsRaw}`);
  return lines.join('\n');
}

// ---- 署名（テスト用クライアント側）----------------------------------------

export async function signRequest({ authority, agent, privateKey, keyid, created, expires }) {
  const agentValue = `"${agent}"`; // Signature-Agent は sf-string（引用符つき）
  const components = ['@authority', 'signature-agent'];
  const paramsRaw =
    `("@authority" "signature-agent")` +
    `;created=${created};expires=${expires};keyid="${keyid}";alg="ed25519";tag="web-bot-auth"`;
  const base = buildSignatureBase(
    components,
    (name) => (name === '@authority' ? authority.toLowerCase() : agentValue),
    paramsRaw,
  );
  const sig = new Uint8Array(await crypto.subtle.sign({ name: 'Ed25519' }, privateKey, enc.encode(base)));
  return {
    'signature-agent': agentValue,
    'signature-input': `sig1=${paramsRaw}`,
    signature: `sig1=:${bytesToB64(sig)}:`, // sf-binary は標準base64＋コロン囲み
  };
}

// ---- 検証（門番側）---------------------------------------------------------

// headers: 小文字キーのプレーンオブジェクト
// getKey(keyid, agentValue) -> CryptoKey | null
export async function verifyRequest({ authority, headers, getKey, now = Math.floor(Date.now() / 1000) }) {
  const h = {};
  for (const [k, v] of Object.entries(headers)) h[k.toLowerCase()] = v;

  const sigInput = h['signature-input'];
  const sigHeader = h['signature'];
  if (!sigInput || !sigHeader) return { ok: false, reason: 'no-signature' };

  // sig1=("@authority" "signature-agent");created=...;keyid="...";...
  const m = sigInput.match(/^\s*([!#$%&'*+\-.^_`|~0-9a-zA-Z]+)=(\(([^)]*)\)(.*))$/s);
  if (!m) return { ok: false, reason: 'malformed-signature-input' };
  const [, label, paramsRaw, componentList, paramsPart] = m;

  const components = [...componentList.matchAll(/"([^"]+)"/g)].map((x) => x[1]);
  const params = {};
  for (const pm of paramsPart.matchAll(/;([a-zA-Z]+)=(?:"([^"]*)"|([^;]+))/g)) {
    params[pm[1]] = pm[2] !== undefined ? pm[2] : pm[3];
  }

  if (params.tag !== 'web-bot-auth') return { ok: false, reason: 'wrong-tag', tag: params.tag };
  if (params.alg && params.alg !== 'ed25519') return { ok: false, reason: 'unsupported-alg', alg: params.alg };
  if (params.created && now + 60 < Number(params.created)) return { ok: false, reason: 'created-in-future' };
  if (params.expires && now > Number(params.expires)) return { ok: false, reason: 'expired' };

  // ラベルは正規表現に埋める前に必ずエスケープする。
  // RFC 8941 の辞書キーは `*` で始められ `.` `*` を含められるので、そのまま埋めると
  // `*sig` で SyntaxError、`a.c` で `.` がワイルドカードとして働く。
  // 先頭かカンマの直後に固定して、別エントリを拾わないようにする。
  const escaped = label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const sm = sigHeader.match(new RegExp(`(?:^|,)\\s*${escaped}=:([A-Za-z0-9+/=]+):`));
  if (!sm || !sm[1]) return { ok: false, reason: 'malformed-signature' };
  // base64 として成立しない長さでも atob は例外を投げる（外から来た値なので握る）
  let sigBytes;
  try {
    sigBytes = b64ToBytes(sm[1]);
  } catch {
    return { ok: false, reason: 'malformed-signature' };
  }

  let base;
  try {
    base = buildSignatureBase(
      components,
      (name) => {
        if (name === '@authority') return authority.toLowerCase();
        if (name.startsWith('@')) throw new Error(`unsupported derived component: ${name}`);
        const v = h[name];
        if (v === undefined) throw new Error(`missing covered header: ${name}`);
        return v;
      },
      paramsRaw,
    );
  } catch (e) {
    return { ok: false, reason: 'base-construction-failed', detail: String(e.message) };
  }

  // 鍵の取得も検証も、外から来た値を触る＝落ちうる場所。ここで握って結果に変える
  // （門番は拒否しない＝例外で落ちてもいけない）。
  let key;
  try {
    key = await getKey(params.keyid, h['signature-agent']);
  } catch {
    return { ok: false, reason: 'unknown-key', keyid: params.keyid };
  }
  if (!key) return { ok: false, reason: 'unknown-key', keyid: params.keyid };

  let ok = false;
  try {
    ok = await crypto.subtle.verify({ name: 'Ed25519' }, key, sigBytes, enc.encode(base));
  } catch {
    return { ok: false, reason: 'bad-signature', keyid: params.keyid };
  }
  return {
    ok,
    reason: ok ? 'verified' : 'bad-signature',
    keyid: params.keyid,
    agent: (h['signature-agent'] || '').replace(/^"|"$/g, ''),
    created: params.created ? Number(params.created) : undefined,
    expires: params.expires ? Number(params.expires) : undefined,
  };
}
