// 門番 (Cloudflare Worker 形)。自治体サイトの前段に置く。
//
//   AIエージェント（署名つき） → 検証 → 記録 → 整った答え(JSON)を返す
//   人間のブラウザ（署名なし） → 記録せずそのまま元サイトへ素通し
//   検証に失敗した署名        → 記録だけして素通し（門番は拒否しない）
//
// 通行料は取らない（402課金は AWS/Cloudflare/Akamai の標準機能＝作る場所ではない）。
// この門番が貯める主役のデータは「AIが何を探しに来て、取れたか／取れずに帰ったか」。
// サーバーログには「来た」しか残らず、「来たが取れなかった」はどこにも記録が無い。
//
// ローカル実測は test_local.mjs / check_chatgpt_keys.mjs 参照。
// この形のまま Cloudflare Workers にデプロイできる（wrangler deploy）。
// 実運用の記録先は console.log ではなく Workers Analytics Engine / KV に差し替える。
import { verifyRequest, importPublicJwk, jwkThumbprint } from './httpsig.mjs';

// Signature-Agent のオリジンごとに JWKS を取得してキャッシュ（1時間）
const directoryCache = new Map(); // origin -> { fetchedAt, keys: Map<keyid, CryptoKey> }
const DIRECTORY_TTL_MS = 60 * 60 * 1000;

async function resolveKey(keyid, signatureAgentValue) {
  if (!keyid || !signatureAgentValue) return null;
  const agent = signatureAgentValue.replace(/^"|"$/g, '');
  let origin;
  try {
    origin = new URL(agent).origin;
    if (!origin.startsWith('https://')) return null; // 鍵配布は https のみ信用する
  } catch {
    return null;
  }

  let entry = directoryCache.get(origin);
  if (!entry || Date.now() - entry.fetchedAt > DIRECTORY_TTL_MS) {
    // 名乗ったオリジンが存在しない・落ちている場合も門番は落ちない → unknown-key 扱い
    let body;
    try {
      const res = await fetch(`${origin}/.well-known/http-message-signatures-directory`, {
        headers: { accept: 'application/http-message-signatures-directory+json, application/json' },
      });
      if (!res.ok) return null;
      body = await res.json();
    } catch {
      return null;
    }
    const keys = new Map();
    for (const jwk of body.keys || []) {
      if (jwk.kty !== 'OKP' || jwk.crv !== 'Ed25519') continue;
      const key = await importPublicJwk(jwk);
      // keyid は kid、無ければ RFC 7638 指紋（ChatGPT は両者一致を実測済み）
      keys.set(jwk.kid ?? (await jwkThumbprint(jwk)), key);
    }
    entry = { fetchedAt: Date.now(), keys };
    directoryCache.set(origin, entry);
  }
  return entry.keys.get(keyid) ?? null;
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const headers = Object.fromEntries(request.headers);

    const result = await verifyRequest({
      authority: url.host,
      headers,
      getKey: resolveKey,
    });

    // 署名なし＝普通の人間のアクセス。記録せず素通し（住民のデータは集めない）
    if (result.reason === 'no-signature') {
      return fetch(request);
    }

    // 検証済みエージェントに返す整った答え（AI読の実測データを流用）を先に引く。
    // 「答えがあるか」自体が記録の主役になるため、記録より先に引く。
    // キーは host+path（1つの門番が複数の自治体の前に立てるように）。
    let answer = null;
    if (result.ok && env?.ANSWERS) {
      answer = await env.ANSWERS.get(`${url.host}${url.pathname}`, 'json');
      // 全項目が null＝そのページからは何も読み取れなかった、ということ。
      // 「答えがある」ふりをせず、取れずに帰った扱いにする。
      if (answer && Object.values(answer.fields ?? {}).every((v) => v === null)) {
        answer = null;
      }
    }

    // 門番が貯める記録の主役: 何を探しに来て、取れたか／取れずに帰ったか
    const record = {
      ts: new Date().toISOString(),
      looking_for: url.searchParams.get('q') ?? null, // 何を探しに来たか
      answered: result.ok ? Boolean(answer) : null, // 取れた=true ／ 取れずに帰った=false
      verified: result.ok,
      reason: result.reason,
      agent: result.agent ?? null,
      keyid: result.keyid ?? null,
      authority: url.host,
      path: url.pathname,
    };
    console.log(JSON.stringify(record)); // TODO: Analytics Engine / KV に置き換え

    if (answer) {
      return new Response(JSON.stringify({ source: url.href, answer }), {
        headers: { 'content-type': 'application/json; charset=utf-8' },
      });
    }

    // 整った答えがまだ無いページ／検証失敗 → 元のサイトへ素通し
    return fetch(request);
  },
};
