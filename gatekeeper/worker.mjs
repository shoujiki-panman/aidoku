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
import { ASK_PATH, parseAsk, askTarget, decideAsk, failureResponse } from './nlweb.mjs';

// 集めたデータの取り出し口。自治体サイトのURLと衝突しないよう接頭辞を付ける。
const DEMAND_PATH = '/_aidoku/demand';

// Signature-Agent のオリジンごとに JWKS を取得してキャッシュ（1時間）
const directoryCache = new Map(); // origin -> { fetchedAt, keys: Map<keyid, CryptoKey> }
const DIRECTORY_TTL_MS = 60 * 60 * 1000;
// 取りに行った先が落ちている・存在しない場合も、しばらくは覚えておく。
// 覚えないと、存在しないオリジンを名乗るリクエストが来るたびに外部fetchが走る。
const DIRECTORY_FAIL_TTL_MS = 5 * 60 * 1000;
const DIRECTORY_TIMEOUT_MS = 2000; // 相手が遅いだけで門番が詰まらないように
const MAX_KEYS = 50; // 1オリジンから取り込む鍵の上限
const MAX_CACHED_ORIGINS = 100; // キャッシュそのものが太らないように

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
  const ttl = entry?.failed ? DIRECTORY_FAIL_TTL_MS : DIRECTORY_TTL_MS;
  if (!entry || Date.now() - entry.fetchedAt > ttl) {
    // 名乗ったオリジンが存在しない・落ちている場合も門番は落ちない → unknown-key 扱い。
    // 失敗も短く覚えておく（覚えないと、来るたびに外部fetchが走る）。
    let body;
    try {
      const res = await fetch(`${origin}/.well-known/http-message-signatures-directory`, {
        headers: { accept: 'application/http-message-signatures-directory+json, application/json' },
        signal: AbortSignal.timeout(DIRECTORY_TIMEOUT_MS),
      });
      if (!res.ok) return rememberFailure(origin);
      body = await res.json();
    } catch {
      return rememberFailure(origin);
    }
    const keys = new Map();
    // 相手が置いた JWKS は「外から来た値」。壊れた鍵1本で門番が落ちないよう、
    // 1本ずつ握って飛ばす。件数にも上限を置く（数万本返して CPU を焼く手を塞ぐ）。
    for (const jwk of (body.keys || []).slice(0, MAX_KEYS)) {
      if (jwk.kty !== 'OKP' || jwk.crv !== 'Ed25519') continue;
      if (jwk.use && jwk.use !== 'sig') continue;
      try {
        const key = await importPublicJwk(jwk);
        // keyid は kid、無ければ RFC 7638 指紋（ChatGPT は両者一致を実測済み）
        keys.set(jwk.kid ?? (await jwkThumbprint(jwk)), key);
      } catch {
        continue; // 壊れた鍵は飛ばす（この1本のせいで他の鍵まで捨てない）
      }
    }
    entry = { fetchedAt: Date.now(), keys };
    setCache(origin, entry);
  }
  return entry.keys.get(keyid) ?? null;
}

function rememberFailure(origin) {
  setCache(origin, { fetchedAt: Date.now(), keys: new Map(), failed: true });
  return null;
}

// 古いものから落として、キャッシュが無制限に太らないようにする
function setCache(origin, entry) {
  directoryCache.delete(origin);
  directoryCache.set(origin, entry);
  while (directoryCache.size > MAX_CACHED_ORIGINS) {
    directoryCache.delete(directoryCache.keys().next().value);
  }
}

const jsonResponse = (obj, status = 200) =>
  new Response(JSON.stringify(obj), {
    status,
    headers: {
      'content-type': 'application/json; charset=utf-8',
      'access-control-allow-origin': '*',
    },
  });

// 記録を1件残す。署名なし（＝人間）はそもそも呼ばない。
async function keepRecord(env, ctx, record, keyid) {
  console.log(JSON.stringify(record));
  const uniq = `${keyid ?? 'unknown'}-${crypto.randomUUID().slice(0, 8)}`;
  const writing = recordAsk(env, record, uniq).catch(() => false);
  if (ctx?.waitUntil) ctx.waitUntil(writing);
  else await writing;
}

// NLWeb の窓口（POST /ask）。仕様: https://nlweb.ai/docs/specification
//
// 探し物は自分ルール(?q=)ではなく query.text で受け取る。
// 答えられなければ規格の failure を返す＝「取れずに帰った」が標準の型で残る。
// どの項目を聞かれたか分からなければ elicitation で聞き返す（推測で「取れた」にしない）。
async function handleAsk(request, url, env, ctx, result) {
  if (request.method !== 'POST') {
    return jsonResponse(
      failureResponse('INVALID_QUERY', 'POST で {"query":{"text":"..."}} を送ってください。'),
      405,
    );
  }

  let body = null;
  try {
    body = await request.json();
  } catch {
    body = null;
  }
  const parsed = parseAsk(body);
  if (parsed.error) return jsonResponse(failureResponse('INVALID_QUERY', parsed.error), 400);

  const target = askTarget(url.host, parsed.site);

  let answer = null;
  if (env?.ANSWERS) {
    answer = await env.ANSWERS.get(target.key, 'json');
    // 全項目が null＝そのページからは何も読み取れなかった。「答えがある」ふりをしない。
    if (answer && Object.values(answer.fields ?? {}).every((v) => v === null)) answer = null;
  }

  const decided = decideAsk(answer, parsed.text, target.url);

  // 署名なし＝人間。答えは返すが記録しない（住民のデータは集めない）。
  if (result.reason !== 'no-signature') {
    await keepRecord(
      env,
      ctx,
      {
        ts: new Date().toISOString(),
        looking_for: parsed.text, // 自然文の質問がそのまま入る（?q= のような自分ルールが要らない）
        answered: result.ok ? decided.answered : null, // null = どの項目か分からず聞き返した
        verified: result.ok,
        reason: result.reason,
        agent: result.ok ? (result.agent ?? null) : null,
        keyid: result.keyid ?? null,
        authority: url.host,
        path: target.path,
        via: 'nlweb',
      },
      result.keyid,
    );
  }

  return jsonResponse(decided.body);
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

    // 門番は落ちない。検証の中で何が起きても、素通しに落として先へ進む。
    // （7/31 に JWKS fetch で同じ壊れ方をしている。原則を実装で担保しておく）
    let result;
    try {
      result = await verifyRequest({ authority: url.host, headers, getKey: resolveKey });
    } catch {
      result = { ok: false, reason: 'verify-error' };
    }

    // NLWeb の窓口。ここは門番自身の口なので、署名の有無にかかわらず答える
    // （素通ししても元サイトに /ask は無い）。記録の作法は下と同じ。
    if (url.pathname === ASK_PATH) {
      return handleAsk(request, url, env, ctx, result);
    }

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
      // 名乗りは検証に成功したときだけ記録する。
      // 検証前の signature-agent は自称（他人の公開 keyid は誰でも書ける）なので、
      // そのまま残すと「ChatGPTがN回来た」を誰でも作れてしまう。
      agent: result.ok ? (result.agent ?? null) : null,
      keyid: result.keyid ?? null,
      authority: url.host,
      path: url.pathname,
      via: 'query', // ?q= で来た分（NLWeb の /ask で来た分は via: 'nlweb'）
    };
    // データとして貯める。応答を待たせないよう、書き込みはリクエストの外に逃がす。
    await keepRecord(env, ctx, record, result.keyid);

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
