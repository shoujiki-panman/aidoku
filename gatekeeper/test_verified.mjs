// 確認済み情報（verified/）のテスト。
// 実行: node gatekeeper/test_verified.mjs
//
// 確かめたいことは1つ。
// 「担当者が情報を確認・修正すると、利用者のAIの案内が変わる」の一周が本当に回るか。
//   - 公開（published）した確認済みの値が、門番の答えに出典・条件・確認者・版ごと載るか
//   - 元ページが公開後に変わったら、確認案件（needs_review）に戻って門番から消えるか
//   - 再公開したら門番に戻り、**翌朝の見張り（ラッチされた changed）で取り消されないか**
//   - 実測（fields）はこの間、1文字も変わらないか
import worker from './worker.mjs';
import { generateKeyPair, jwkThumbprint, signRequest } from './httpsig.mjs';
import { effectiveFields, hasAnyAnswer } from './demand.mjs';
import { reviewAgainstWatch, publishInto, parseTime, urlKey, unknownFields } from './verified_sync.mjs';

const AGENT_ORIGIN = 'https://agent.example';
const HOST = 'www.city.setagaya.lg.jp';
const SITE = `https://${HOST}`;
const PAGE = '/kurashi/kosekijuumin/11531.html';

// --- 実測データ（世田谷区。実測では4項目とも読み取れなかった）---
const measured = () => ({
  procedure: '転入届',
  municipality: '世田谷区',
  source: `${SITE}${PAGE}`,
  measured_at: '2026-07-22',
  fields: { required_documents: null, how_to_apply: null, deadline: null, fee: null },
  note: 'テスト用',
});

// --- 担当者の確認記録（テストの中だけの仮の値。verified/ には置かない）---
const record = () => ({
  municipality: '世田谷区',
  municipality_id: 'setagaya',
  procedure: '転入届',
  procedure_id: 'tennyu',
  source: `${SITE}${PAGE}`,
  fields: {
    fee: {
      value: '無料',
      conditions: '窓口で届け出る場合',
      verified_by: '世田谷区 戸籍住民課',
      verified_at: '2026-09-09',
      published_at: '2026-09-09T12:00:00+09:00',
      version: 1,
      status: 'published',
    },
  },
});

const watch = (over = {}) => [
  { url: `${SITE}${PAGE}`, changed: false, gone: false, checked_at: '2026-09-10T00:00:00+0000', ...over },
];

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

// 公開 → verified_fields に出典・条件・確認者・版ごと載る
{
  const a = publishInto(measured(), record());
  const v = a.verified_fields?.fee;
  check('公開した確認済みが verified_fields に載る', v?.value === '無料', JSON.stringify(a.verified_fields));
  check(
    '  └ 出典・条件・確認者・版が付いている',
    v?.source === `${SITE}${PAGE}` && v?.conditions === '窓口で届け出る場合' &&
      v?.verified_by === '世田谷区 戸籍住民課' && v?.version === 1,
    JSON.stringify(v),
  );
  check(
    '  └ 内部管理の鍵（status / published_at）は外に出ない',
    v && !('status' in v) && !('published_at' in v),
    JSON.stringify(v),
  );
  check('  └ 実測 fields は触られない', a.fields.fee === null, JSON.stringify(a.fields));
  check('  └ 重ねた景色では答えがある扱い', effectiveFields(a).fee === '無料' && hasAnyAnswer(a));
}

// 見張りが「公開後に変わった」→ 確認案件に戻る
{
  const r = record();
  const { demoted } = reviewAgainstWatch(r, watch({ changed: true }));
  check('公開後の変化 → needs_review に戻る', demoted.length === 1 && r.fields.fee.status === 'needs_review', JSON.stringify(r.fields.fee));
  check('  └ 理由と検出時刻が残る', r.fields.fee.review_reason === '元ページが変わった' && !!r.fields.fee.review_detected_at);

  const a = publishInto(measured(), r);
  check('  └ 戻った項目は門番の答えから消える', !('verified_fields' in a), JSON.stringify(a.verified_fields ?? null));
}

// 公開より前の変化では戻らない（公開前の変化は確認に織り込み済み）
{
  const r = record();
  const { demoted } = reviewAgainstWatch(r, watch({ changed: true, checked_at: '2026-09-08T00:00:00+0000' }));
  check('公開前の変化では戻らない', demoted.length === 0 && r.fields.fee.status === 'published');
}

// ページが消えたら、時刻に関係なく戻る
{
  const r = record();
  reviewAgainstWatch(r, watch({ gone: true, checked_at: '2026-09-08T00:00:00+0000' }));
  check('元ページが消えた → 戻る', r.fields.fee.status === 'needs_review' && r.fields.fee.review_reason === '元ページが消えた');
}

// published_at の無い記録は、変化があれば戻す（時刻を主張できない確認は守らない）
{
  const r = record();
  delete r.fields.fee.published_at;
  reviewAgainstWatch(r, watch({ changed: true, checked_at: '2026-09-08T00:00:00+0000' }));
  check('published_at 無し＋変化 → 戻る', r.fields.fee.status === 'needs_review');
}

// ★再公開の生存。見張りの changed はラッチ式（測り直しまで毎朝 changed:true が
// 新しい checked_at で出続ける）。再公開が翌朝の同期で取り消されないこと。
{
  const r = record();
  reviewAgainstWatch(r, watch({ changed: true })); // 9/10 に検出 → needs_review
  r.fields.fee.status = 'published'; // 担当者が見直して再公開
  r.fields.fee.version = 2;
  r.fields.fee.verified_at = '2026-09-11';
  r.fields.fee.published_at = '2026-09-11T09:00:00+09:00';

  // 翌朝の見張り: 同じラッチが「新しい checked_at」で出る（ここが以前のテストの穴）
  const { demoted } = reviewAgainstWatch(r, watch({ changed: true, checked_at: '2026-09-12T00:46:00+0000' }));
  const a = publishInto(measured(), r);
  check('再公開 → 翌朝のラッチされた changed では戻らない', demoted.length === 0 && r.fields.fee.status === 'published', JSON.stringify(r.fields.fee));
  check('  └ 版が上がって門番の答えに戻る', a.verified_fields?.fee?.version === 2, JSON.stringify(a.verified_fields));

  // 測り直しで基準が更新され changed:false → 検出の印が消える（ラッチが解けた）
  const { cleared } = reviewAgainstWatch(r, watch({ changed: false, checked_at: '2026-09-13T00:46:00+0000' }));
  check('測り直しで unchanged → 検出の印が消える', cleared.includes('fee') && !r.fields.fee.review_detected_at, JSON.stringify(r.fields.fee));

  // その後の変化は新しい変化として、再び戻る
  const again = reviewAgainstWatch(r, watch({ changed: true, checked_at: '2026-09-14T00:46:00+0000' }));
  check('印が消えた後の新しい変化 → 再び戻る', again.demoted.includes('fee') && r.fields.fee.status === 'needs_review');
}

// ★照合はどちらも host+path。出典URLの書きぶれ（http・クエリ付き）でも見張りと照合できる
{
  const r = record();
  r.source = `http://${HOST}${PAGE}?openpc=1`;
  const { watched, demoted } = reviewAgainstWatch(r, watch({ gone: true }));
  check('出典URLの書きぶれでも見張りに当たる', watched && demoted.includes('fee'), JSON.stringify({ watched, demoted }));
  check('  └ urlKey が host+path に畳む', urlKey(r.source) === `${HOST}${PAGE}`);
}

// 見張りに相手がいない → watched: false（呼び出し側が公開を止めて報告する）
{
  const r = record();
  const { watched } = reviewAgainstWatch(r, [{ url: 'https://example.com/other.html', changed: true, gone: false, checked_at: '2026-09-10T00:00:00+0000' }]);
  check('見張りに相手がいない → watched: false', watched === false);
}

// ★語彙に無い項目名は公開されない（タイポ・独自項目が黙って門番に載らない）
{
  const r = record();
  r.fields.opening_hours = { ...r.fields.fee, value: '9時〜17時' };
  check('語彙外の項目名を検出できる', unknownFields(r).join(',') === 'opening_hours');
  const a = publishInto(measured(), r);
  check('  └ 語彙外は verified_fields に載らない', !('opening_hours' in (a.verified_fields ?? {})) && a.verified_fields?.fee?.value === '無料', JSON.stringify(a.verified_fields));
}

// 見張りの "+0000" 形式の時刻が読める
check('見張りの時刻形式（+0000）が読める', Number.isFinite(parseTime('2026-09-08T00:46:47+0000')));

// --- ここから門番ごと通す（署名つきエージェントが /ask で聞く）---
realLog('テスト（門番ごと）:');

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

console.log = (line) => {
  try {
    JSON.parse(line); // 記録はこのテストでは見ない。捨てるだけ
  } catch {
    realLog(line);
  }
};

const answers = new Map();
const env = { ANSWERS: { get: async (key) => answers.get(key) ?? null } };

const now = Math.floor(Date.now() / 1000);
const signed = await signRequest({
  authority: HOST,
  agent: AGENT_ORIGIN,
  privateKey,
  keyid,
  created: now,
  expires: now + 300,
});

async function ask(text) {
  const res = await worker.fetch(
    new Request(`${SITE}/ask`, {
      method: 'POST',
      headers: { ...signed, 'content-type': 'application/json' },
      body: JSON.stringify({ query: { text, site: PAGE } }),
    }),
    env,
  );
  return res.json();
}

// 公開前: 実測が全null → 取れずに帰る
answers.set(`${HOST}${PAGE}`, measured());
{
  const body = await ask('転入届の手数料はいくらですか');
  check('公開前 → failure（取れずに帰った）', body._meta?.response_type === 'failure', JSON.stringify(body).slice(0, 160));
}

// 公開後: 確認済みの値が、出典・条件・確認者・版ごと答えに載る
answers.set(`${HOST}${PAGE}`, publishInto(measured(), record()));
{
  const body = await ask('転入届の手数料はいくらですか');
  const r = body.results?.[0];
  check('公開後 → answer が返る', body._meta?.response_type === 'answer', JSON.stringify(body).slice(0, 160));
  check(
    '  └ 確認済みが実測と別の束で載る（実測は null のまま）',
    r?.fields?.fee === null && r?.verified_fields?.fee?.value === '無料',
    JSON.stringify(r).slice(0, 240),
  );
  check(
    '  └ 出典・条件・確認者・版が答えに残っている',
    r?.verified_fields?.fee?.verified_by === '世田谷区 戸籍住民課' && r?.verified_fields?.fee?.version === 1,
    JSON.stringify(r?.verified_fields),
  );
}

// どの項目か分からない聞き方 → 値のある項目だけを選択肢に聞き返す
{
  const body = await ask('世田谷区の転入について教えて');
  const options = body.elicitation?.questions?.[0]?.options ?? [];
  check('曖昧な聞き方 → elicitation で聞き返す', body._meta?.response_type === 'elicitation', JSON.stringify(body).slice(0, 160));
  check('  └ 選択肢は値のある項目（手数料）だけ', options.length === 1 && options[0] === '手数料', JSON.stringify(options));
}

// 4項目のどれにも値が無いのに答えの束だけある状態 → 選択肢ゼロの聞き返しを出さない
{
  const broken = measured();
  broken.verified_fields = { opening_hours: { value: '9時〜17時', version: 1 } }; // 語彙外（手で answers を汚した想定）
  answers.set(`${HOST}${PAGE}`, broken);
  const body = await ask('世田谷区の転入について教えて');
  check('選択肢を作れないときは elicitation ではなく failure', body._meta?.response_type === 'failure', JSON.stringify(body).slice(0, 160));
}

// 差し戻し後: また取れずに帰る（古い確認済みを出し続けない）
{
  const r = record();
  reviewAgainstWatch(r, watch({ changed: true }));
  answers.set(`${HOST}${PAGE}`, publishInto(measured(), r));
  const body = await ask('転入届の手数料はいくらですか');
  check('差し戻し後 → failure に戻る', body._meta?.response_type === 'failure', JSON.stringify(body).slice(0, 160));
}

console.log = realLog;
realLog(`\n${pass} 件通過 / ${fail} 件失敗`);
if (fail > 0) process.exit(1);
