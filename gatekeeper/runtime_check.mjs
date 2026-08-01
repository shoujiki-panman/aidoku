// 本番ランタイム(workerd)の上で、門番の署名検証が本当に動くかを確かめるための足場。
//
// なぜ要るか: test_local.mjs / test_worker.mjs は Node の上で、ネットワークを
// スタブして動かしている。実際に門番が乗るのは Cloudflare の workerd で、
// WebCrypto の Ed25519 対応も fetch の挙動も Node と同じとは限らない。
// 「Nodeで通ったから Workers でも通るはず」で乗らないための実測用。
//
// この足場は worker.mjs には一切触らない。素の worker.mjs をそのまま呼ぶ。
//
//   /_check/crypto   … workerd の中で 鍵生成→署名→検証→改ざん検出 を一周
//   /_check/chatgpt  … workerd の中から ChatGPT の実鍵を取得してインポート
//   /_check/register … テスト用エージェントの公開鍵を預ける（署名する側の登録）
//   /_check/seed     … 23区の実測を ANSWERS(KV) に入れる
//   /.well-known/http-message-signatures-directory … 預かった鍵を JWKS として配る
//   それ以外          … 素の worker.mjs へ委譲（＝門番本体が実リクエストを受ける）
import gatekeeper from './worker.mjs';
import {
  generateKeyPair,
  signRequest,
  verifyRequest,
  importPublicJwk,
  jwkThumbprint,
} from './httpsig.mjs';

// 預かったテスト用エージェントの公開鍵（JWKS として配り直す）
let registered = [];

const WELL_KNOWN = '/.well-known/http-message-signatures-directory';

// 自分自身のオリジン宛の fetch だけを、ネットワークに出さず中で折り返す。
//
// なぜ要るか（実測で分かったこと）:
//  1. wrangler dev の https は自己署名証明書で、workerd から自分自身へは繋げない
//     （/_check/resolve で "internal error"。本物の https=chatgpt.com は 200 で取れる）
//  2. 本番は「門番の後ろに自治体サイト」だが、ここでは門番が自分の前に立っているので、
//     素通し(fetch(request))がそのまま自分に戻って無限ループになる
//
// 差し替えるのは経路だけ。署名の検証・鍵のインポート・KVの読み書きは素の worker.mjs が行う。
let selfHost = null;
const realFetch = globalThis.fetch.bind(globalThis);
globalThis.fetch = async (input, init) => {
  const href = typeof input === 'string' ? input : input.url;
  let u;
  try {
    u = new URL(href);
  } catch {
    return realFetch(input, init);
  }
  if (selfHost && u.host === selfHost) {
    if (u.pathname === WELL_KNOWN) return directoryResponse(u.origin);
    // 門番の後ろに居る「元の自治体サイト」の代わり
    return new Response('<!DOCTYPE html><title>元の自治体サイト（スタブ）</title>', {
      headers: { 'content-type': 'text/html; charset=utf-8' },
    });
  }
  return realFetch(input, init);
};

function directoryResponse(origin) {
  return new Response(JSON.stringify({ keys: registered, signature_agent: origin, purpose: 'ai' }), {
    headers: { 'content-type': 'application/http-message-signatures-directory+json' },
  });
}

const json = (obj, status = 200) =>
  new Response(JSON.stringify(obj, null, 2), {
    status,
    headers: { 'content-type': 'application/json; charset=utf-8' },
  });

// workerd の中で 署名→検証 を一周させる。改ざんが落ちることまで見る。
async function cryptoRoundTrip() {
  const steps = [];
  const { publicKey, privateKey } = await generateKeyPair();
  const jwk = await crypto.subtle.exportKey('jwk', publicKey);
  const keyid = await jwkThumbprint(jwk);
  steps.push({ step: 'generateKey(Ed25519)', ok: true, keyid });

  const now = Math.floor(Date.now() / 1000);
  const authority = 'www.city.setagaya.lg.jp';
  const agent = 'https://agent.example';
  const headers = await signRequest({
    authority,
    agent,
    privateKey,
    keyid,
    created: now,
    expires: now + 300,
  });
  steps.push({ step: 'sign', ok: true });

  const getKey = async (kid) => (kid === keyid ? publicKey : null);
  const good = await verifyRequest({ authority, headers, getKey });
  steps.push({ step: 'verify(正しい署名)', ok: good.ok === true, reason: good.reason });

  // 宛先を世田谷→港に付け替える＝別の自治体宛の署名を使い回す攻撃
  const tampered = await verifyRequest({ authority: 'www.city.minato.tokyo.jp', headers, getKey });
  steps.push({
    step: 'verify(宛先を改ざん)',
    ok: tampered.ok === false && tampered.reason === 'bad-signature',
    reason: tampered.reason,
  });

  return { ok: steps.every((s) => s.ok), steps };
}

// workerd の中から本物の鍵を取りに行き、この実装でインポートできるかを見る
async function chatgptKeys() {
  const url = 'https://chatgpt.com/.well-known/http-message-signatures-directory';
  const res = await fetch(url, {
    headers: { accept: 'application/http-message-signatures-directory+json, application/json' },
  });
  if (!res.ok) return { ok: false, status: res.status };
  const body = await res.json();
  const keys = [];
  for (const jwk of body.keys ?? []) {
    if (jwk.kty !== 'OKP' || jwk.crv !== 'Ed25519') continue;
    await importPublicJwk(jwk); // 落ちたらここで例外
    const thumb = await jwkThumbprint(jwk);
    keys.push({ kid: jwk.kid, thumbprint: thumb, matches: jwk.kid === thumb, imported: true });
  }
  return { ok: keys.length > 0 && keys.every((k) => k.imported && k.matches), status: res.status, keys };
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    selfHost = url.host; // 自分宛の fetch を見分けるため（上の差し替えで使う）

    if (url.pathname === '/_check/crypto') {
      return json(await cryptoRoundTrip());
    }

    if (url.pathname === '/_check/chatgpt') {
      try {
        return json(await chatgptKeys());
      } catch (e) {
        return json({ ok: false, error: String(e && e.message) }, 500);
      }
    }

    // 門番と同じ取りに行き方をして、失敗するなら「なぜ」を握り潰さずに見る。
    // worker.mjs 側は try/catch で null にしてしまうので、原因はここで確かめる。
    if (url.pathname === '/_check/resolve') {
      const target = url.searchParams.get('origin') ?? url.origin;
      try {
        const res = await fetch(`${target}/.well-known/http-message-signatures-directory`, {
          headers: { accept: 'application/http-message-signatures-directory+json, application/json' },
        });
        const text = await res.text();
        return json({ ok: res.ok, status: res.status, body: text.slice(0, 300) });
      } catch (e) {
        return json({ ok: false, threw: true, name: e?.name, error: String(e?.message), cause: String(e?.cause ?? '') });
      }
    }

    // 署名する側（テスト用エージェント）の公開鍵を預かる
    if (url.pathname === '/_check/register' && request.method === 'POST') {
      const jwk = await request.json();
      registered = [jwk];
      return json({ ok: true, kid: jwk.kid });
    }

    // 預かった鍵を Web Bot Auth の作法で配る（門番はここを取りに来る）
    if (url.pathname === WELL_KNOWN) return directoryResponse(url.origin);

    // 実測の答えを ANSWERS(KV) に入れる。中身は本文から渡す（ここで文章は作らない）
    if (url.pathname === '/_check/seed' && request.method === 'POST') {
      const { key, value } = await request.json();
      await env.ANSWERS.put(key, JSON.stringify(value));
      return json({ ok: true, key });
    }

    // ここから先は素の門番。実リクエストがそのまま worker.mjs に入る。
    return gatekeeper.fetch(request, env, ctx);
  },
};
