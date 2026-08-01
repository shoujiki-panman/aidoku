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
import { recordAsk, aggregate, isAnswered } from './demand.mjs';

// 集めたデータの取り出し口。自治体サイトのURLと衝突しないよう接頭辞を付ける。
const DEMAND_PATH = '/_aidoku/demand';

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

    // 集めたデータの取り出し口。誰でも読める（中身は「AIが何を探しに来たか」だけで、
    // 人の情報は入っていない）。新しいオープンデータとして自治体に返すための口。
    if (url.pathname === DEMAND_PATH) {
      const data = await aggregate(env);
      if (!data) return new Response('demand store is not configured', { status: 503 });
      return new Response(JSON.stringify(data, null, 2), {
        headers: {
          'content-type': 'application/json; charset=utf-8',
          'access-control-allow-origin': '*',
        },
      });
    }

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
    // 「取れた」は、ページに答えの束があることではなく、**聞かれた項目に答えがあること**。
    // 例: 手数料を聞かれたのに手数料だけ空なら、取れずに帰った。
    const lookingFor = url.searchParams.get('q');
    const record = {
      ts: new Date().toISOString(),
      looking_for: lookingFor ?? null, // 何を探しに来たか
      answered: result.ok ? isAnswered(answer, lookingFor) : null,
      verified: result.ok,
      reason: result.reason,
      agent: result.agent ?? null,
      keyid: result.keyid ?? null,
      authority: url.host,
      path: url.pathname,
    };
    console.log(JSON.stringify(record));
    // データとして貯める。応答を待たせないよう、書き込みはリクエストの外に逃がす。
    const uniq = `${result.keyid ?? 'unknown'}-${crypto.randomUUID().slice(0, 8)}`;
    const writing = recordAsk(env, record, uniq).catch(() => false);
    if (ctx?.waitUntil) ctx.waitUntil(writing);
    else await writing;

    if (answer) {
      // 持っているぶんは渡す。ただし聞かれた項目が空なら、それを隠さず伝える
      // （AI側が「このページには無い」と正しく答えられるように）。
      return new Response(
        JSON.stringify({
          source: url.href,
          asked: record.looking_for,
          answered: record.answered,
          answer,
        }),
        { headers: { 'content-type': 'application/json; charset=utf-8' } },
      );
    }

    // 整った答えがまだ無いページ／検証失敗 → 元のサイトへ素通し
    return fetch(request);
  },
};
