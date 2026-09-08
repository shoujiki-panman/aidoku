// 受付 — このサイトでAIが「実行」できる操作の第1弾（誤り・更新の指摘）。
//
// 後半の構想（plans/ai-reception.md）の中心は「このサイトでAIが何をできるか」の定義。
// その定義（必要な入力・受け付ける条件・完了の判定）を、このファイル1か所に置く。
//
//   何ができるか   … 採点対象ページの実測値への誤り・更新の指摘（= GitHub Issue が立つ）
//   必要な入力     … site（対象ページURL）と detail（指摘の内容）。field / evidence は任意
//   受け付ける条件 … 署名（Web Bot Auth）の検証に成功したエージェントのみ
//   完了の判定     … Issue の番号とURLが返る
//   止まった場所   … signature / validation / not-configured / github-<status> を明示して返す
//
// 実行は自作せず、既存の公式API（GitHub Issues）へ接続する。LLMは呼ばない。
// 匿名の書き込み口にはならない（decisions/api-layer-from-michiyomi.md と衝突しない）。
// 指摘の採否は人が判断する。AIの指摘を自動で実測値に反映しない。
import { KNOWN_FIELDS, descendingStamp } from './demand.mjs';
import { urlKey } from './verified_core.mjs';

export const RECEPTION_REPO = 'shoujiki-panman/aidoku';

// 回数の上限。「署名検証済み」は身元の証明ではない（自分のドメインに鍵を置けば
// 誰でも名乗れる＝自己申告）。書き込みの受付をそれだけに委ねると、使い捨てドメインで
// Issue を無制限に量産できてしまう。だから件数で守る（レビューで26連続作成を実証済み）。
export const RATE_LIMIT = {
  perAgent: 3, // 1つの名乗りあたり / 24時間
  global: 10, // 受付全体 / 24時間（ドメインは使い捨てられるので全体の上限が本命）
  windowMs: 24 * 60 * 60 * 1000,
};

// 入力の長さ上限（本文肥大化＝荒らしへの寄与を絶つ）
const MAX_SITE = 300;
const MAX_DETAIL = 2000;
const MAX_EVIDENCE = 300;

// 1行に潰す（制御文字・改行を除去）。Issue本文の「- 対象ページ:」等の行を
// 入力値の改行で突き破らせない。
const oneLine = (s, max) =>
  String(s ?? '').replace(/[\u0000-\u001f\u007f]+/g, ' ').trim().slice(0, max);

// 利用者の文章は4スペース字下げのコードブロックとして入れる。
// GitHub のコードブロック内では @メンションは通知されず、見出し・リンクも効かない。
// フェンス（```）と違って、中身に何を書かれても「囲いを閉じて脱出」ができない。
const asCodeBlock = (s) =>
  String(s ?? '')
    .replace(/[\u0000-\u0009\u000b-\u001f\u007f]+/g, ' ') // 改行(\u000a)だけ残す
    .split('\n')
    .map((line) => `    ${line}`)
    .join('\n');

// MCP に載せるツール定義。description が「AIが読む導入手順」そのものなので、
// 条件と完了判定をここに書き切る。
export const REPORT_TOOL = {
  name: 'report_correction',
  title: 'AI読の実測値への誤り・更新の指摘を出す',
  description:
    'AI読が採点した自治体ページについて、実測値の誤りや元ページの更新を指摘します。' +
    '受け付けると GitHub Issue が作られ、その番号とURLが返ります（これが受付成立の判定です）。' +
    '署名（Web Bot Auth）の検証に成功したエージェントだけが実行できます。' +
    `受付の上限は1エージェントあたり24時間に${RATE_LIMIT.perAgent}件・全体で${RATE_LIMIT.global}件です。` +
    '指摘の採否は人が判断します。緊急の連絡には使えません。',
  inputSchema: {
    type: 'object',
    properties: {
      site: { type: 'string', description: '指摘対象のページURL（AI読が採点した自治体ページ）' },
      detail: { type: 'string', description: '指摘の内容。何が誤っているか／何が更新されたかを具体的に' },
      field: { type: 'string', enum: KNOWN_FIELDS, description: '対象の項目（分かる場合）' },
      evidence: { type: 'string', description: '根拠のURL（公式ページ等。任意）' },
    },
    required: ['site', 'detail'],
  },
};

const isHttpUrl = (s) => {
  try {
    return ['http:', 'https:'].includes(new URL(s).protocol);
  } catch {
    return false;
  }
};

// 入力チェック。足りないものは全部並べて返す（1つずつ突き返さない）。
export function validateReport(args) {
  const missing = [];
  if (!urlKey(args?.site) || String(args.site).length > MAX_SITE) {
    missing.push(`site（URLとして読めて${MAX_SITE}文字以内）`);
  }
  const detail = String(args?.detail ?? '').trim();
  if (detail.length < 10 || detail.length > MAX_DETAIL) {
    missing.push(`detail（指摘の内容。10〜${MAX_DETAIL}文字）`);
  }
  if (args?.field != null && !KNOWN_FIELDS.includes(args.field)) {
    missing.push(`field（使えるのは ${KNOWN_FIELDS.join(' / ')}）`);
  }
  if (args?.evidence != null && (!isHttpUrl(args.evidence) || String(args.evidence).length > MAX_EVIDENCE)) {
    missing.push(`evidence（http(s)のURLで${MAX_EVIDENCE}文字以内。無ければ省略）`);
  }
  return { ok: missing.length === 0, missing };
}

// Issue の本文。利用者由来の値は本文を人間が読む前提なので、そのまま埋めない。
// 1行項目は改行を潰し、文章（detail）はコードブロックに封入する
// （@メンションが通知されず、偽の見出し・リンクも効かない）。
function issueBody({ args, agent }) {
  return [
    '（この Issue は、署名検証済みのAIエージェントからの受付で作成されました。',
    '　指摘の採否は人が判断します。AIの指摘は自動では実測値に反映されません。',
    '　以下の名乗り・URL・指摘は受付時の入力そのもので、内容の真偽は未確認です。）',
    '',
    `- 名乗り（署名検証済み）: \`${oneLine(agent, 120).replace(/`/g, "'")}\``,
    `- 対象ページ: ${oneLine(args.site, MAX_SITE)}`,
    `- 対象の項目: ${args.field ?? '（指定なし）'}`,
    `- 根拠: ${args.evidence ? oneLine(args.evidence, MAX_EVIDENCE) : '（なし）'}`,
    '',
    '## 指摘の内容（入力のまま・整形して封入）',
    '',
    asCodeBlock(String(args.detail).trim()),
  ].join('\n');
}

// 直近24時間で受付が成立した件数を数える（この名乗りの分と全体）。
// 記録キーは新しい順に並ぶ（descendingStamp）ので、窓を過ぎたら打ち切ってよい。
async function countAccepted(env, agent, now) {
  const { keys } = await env.DEMAND.list({ prefix: 'rcpt:' });
  let mine = 0;
  let total = 0;
  for (const k of keys ?? []) {
    const m = k.metadata;
    if (!m?.accepted) continue;
    const t = Date.parse(m.ts);
    if (!Number.isFinite(t) || now - t > RATE_LIMIT.windowMs) break;
    total += 1;
    if (m.agent === agent) mine += 1;
  }
  return { mine, total };
}

// 受付の実行。戻り値がそのままAIへの答えになる。
//   accepted: true  … 成立。issue_number / issue_url が完了の証拠
//   accepted: false … 不成立。stopped_at がどこで止まったか
export async function executeReport({ args, agent, env }) {
  if (!agent) {
    return {
      accepted: false,
      stopped_at: 'signature',
      reason: '署名（Web Bot Auth）の検証に成功したエージェントだけが受付を実行できます。人の方はGitHubから直接どうぞ。',
    };
  }
  const v = validateReport(args);
  if (!v.ok) {
    return { accepted: false, stopped_at: 'validation', reason: '入力が足りません。', missing: v.missing };
  }
  if (!env?.GITHUB_TOKEN || !env?.DEMAND) {
    // 鍵か記録の置き場が無ければ受け付けない（fail-closed。DEMAND_TOKEN と同じ考え方。
    // 記録が無いと回数の上限も数えられないので、KVが無い受付は開かない）
    return { accepted: false, stopped_at: 'not-configured', reason: '受付はまだ開いていません（受付先が未設定）。' };
  }

  // 回数の上限。数えられないときは受け付けない（書き込みは安全側に倒す）
  let counts;
  try {
    counts = await countAccepted(env, agent, Date.now());
  } catch {
    return { accepted: false, stopped_at: 'rate-unknown', reason: '受付回数を確認できませんでした。時間をおいてやり直してください。' };
  }
  if (counts.total >= RATE_LIMIT.global) {
    return { accepted: false, stopped_at: 'rate-limit-global', reason: `受付全体の上限（24時間に${RATE_LIMIT.global}件）に達しています。` };
  }
  if (counts.mine >= RATE_LIMIT.perAgent) {
    return { accepted: false, stopped_at: 'rate-limit-agent', reason: `このエージェントの上限（24時間に${RATE_LIMIT.perAgent}件）に達しています。` };
  }

  let res;
  try {
    res = await fetch(`https://api.github.com/repos/${RECEPTION_REPO}/issues`, {
      method: 'POST',
      headers: {
        authorization: `Bearer ${env.GITHUB_TOKEN}`,
        accept: 'application/vnd.github+json',
        'content-type': 'application/json',
        'user-agent': 'aidoku-gatekeeper',
      },
      body: JSON.stringify({
        title: `[受付] ${args.field ?? 'ページ'}の誤り・更新の指摘: ${urlKey(args.site)}`,
        body: issueBody({ args, agent }),
      }),
    });
  } catch {
    return { accepted: false, stopped_at: 'github-unreachable', reason: '受付先（GitHub）に届きませんでした。' };
  }
  if (!res.ok) {
    // どこで止まったかを隠さない。4xx/5xx はそのまま番号で返す
    return { accepted: false, stopped_at: `github-${res.status}`, reason: `受付先（GitHub）が ${res.status} を返しました。` };
  }
  const issue = await res.json();
  return { accepted: true, issue_number: issue.number ?? null, issue_url: issue.html_url ?? null };
}

// 受付の試行を記録する（成立も不成立も）。指摘の本文は入れない（記録は状態だけ）。
// 記録するのは署名まわりの試行であって、人間のアクセスはそもそもここに来ない。
export async function recordReception(env, ctx, rec) {
  console.log(JSON.stringify({ via: 'reception', ...rec }));
  if (!env?.DEMAND) return;
  const key = `rcpt:${descendingStamp(rec.ts)}:${crypto.randomUUID().slice(0, 8)}`;
  const writing = env.DEMAND
    .put(key, '', {
      metadata: {
        ts: rec.ts,
        agent: rec.agent ?? null,
        site: rec.site ?? null,
        field: rec.field ?? null,
        accepted: rec.accepted,
        stopped_at: rec.stopped_at ?? null,
        issue: rec.issue_number ?? null,
      },
      expirationTtl: 90 * 24 * 60 * 60, // 記録は90日で消す（demand と同じ）
    })
    .catch(() => false);
  if (ctx?.waitUntil) ctx.waitUntil(writing);
  else await writing;
}
