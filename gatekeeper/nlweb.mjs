// NLWeb（POST /ask）の最小実装。
// 仕様: https://nlweb.ai/docs/specification
//
// なぜ自分ルール(?q=)をやめてこれに寄せるか:
//   実際のAIエージェントは ?q= のような各サイト独自のクエリを付けてこない。
//   NLWeb は「サイトを自然言語で聞ける窓口にする」公開プロトコルで、
//   POST /ask の body に query.text として質問がそのまま入ってくる。
//   Shopify / Snowflake / O'Reilly / Tripadvisor 等が採用、Cloudflare Workers への
//   載せ方も公開されている（＝門番と同じ場所）。探し物の受け取り方を発明しない。
//
// そして返答の型に **failure**（答えが出せなかった）が最初から用意されている。
// 我々が数えたい「AIが来て、取れずに帰った」は自作の概念ではなく、この規格の型そのもの。
//
// 探し物の項目が特定できないときは **elicitation**（聞き返し）を返す。
// 黙って「取れた」に倒さないための、規格側の正解。
import { matchField, normalizeQuery } from './demand.mjs';

export const ASK_PATH = '/ask';
export const NLWEB_VERSION = '0.55';

// 実測している4項目の日本語ラベル（聞き返しの選択肢に使う）
const FIELD_LABELS = {
  required_documents: '必要書類（持ち物）',
  fee: '手数料',
  deadline: '期限',
  how_to_apply: '窓口かオンラインか',
};

const meta = (responseType, extra = {}) => ({
  response_type: responseType,
  version: NLWEB_VERSION,
  ...extra,
});

export function answerResponse(results, extra = {}) {
  return { _meta: meta('answer', extra), results };
}

export function failureResponse(code, message, extra = {}) {
  return { _meta: meta('failure', extra), error: { code, message } };
}

export function elicitationResponse(text, questions, extra = {}) {
  return { _meta: meta('elicitation', extra), elicitation: { text, questions } };
}

// リクエストの読み取り。仕様の query / context / prefer / meta のうち、
// この門番が使うのは query.text（必須）と query.site（任意）だけ。
// 残りは受け取っても壊れないように無視する（仕様上どれも optional）。
export function parseAsk(body) {
  if (!body || typeof body !== 'object') return { error: 'body が JSON ではありません' };
  const q = body.query;
  if (!q || typeof q !== 'object') return { error: 'query がありません' };
  const text = typeof q.text === 'string' ? q.text.trim() : '';
  if (!text) return { error: 'query.text がありません' };
  return { text, site: typeof q.site === 'string' ? q.site : null };
}

// query.site（ページのパスかURL）から、ANSWERS のキー・記録用のパス・出典URLを作る。
// 指定が無いときは host そのものを既定のキーとして引く（1門番=1ページの場合）。
export function askTarget(host, site) {
  if (!site) return { key: host, path: '/', url: `https://${host}/` };
  let u;
  try {
    u = new URL(site, `https://${host}`);
  } catch {
    const path = site.startsWith('/') ? site : `/${site}`;
    return { key: `${host}${path}`, path, url: `https://${host}${path}` };
  }
  return { key: `${u.host}${u.pathname}`, path: u.pathname, url: u.href };
}

// 実測データ1件を、schema.org の型に載せて返す。
// name / provider / url は schema.org の語彙。
// **fields は schema.org の語彙ではなく、AI読の実測値そのもの**（作らない・盛らない）。
export function toResult(answer, sourceUrl) {
  return {
    '@context': 'https://schema.org',
    '@type': 'GovernmentService',
    name: answer.procedure ?? null,
    provider: answer.municipality
      ? { '@type': 'GovernmentOrganization', name: answer.municipality }
      : null,
    url: answer.source ?? sourceUrl ?? null,
    fields: answer.fields ?? {},
    measured_at: answer.measured_at ?? null,
    note: answer.note ?? null,
  };
}

// 探し物と実測データを突き合わせて、返す型を決める。
//
//   answer      … 聞かれた項目に実測値がある
//   failure     … 聞かれた項目が、そのページに書かれていない（＝取れずに帰った。主役のデータ）
//   elicitation … 4項目のどれを聞かれたのか分からない（黙って「取れた」に倒さない）
//
// 戻り値の answered は記録用: true / false / null（判定できなかった）。
export function decideAsk(answer, text, sourceUrl) {
  const field = matchField(normalizeQuery(text));

  if (!answer) {
    return {
      answered: false,
      field,
      body: failureResponse(
        'NO_RESULTS',
        'このページの実測データをまだ持っていません（AI読が未調査です）。',
      ),
    };
  }

  const fields = answer.fields ?? {};

  // どの項目を聞かれたか分からない → 聞き返す（推測で「取れた」にしない）
  if (!field) {
    return {
      answered: null,
      field: null,
      body: elicitationResponse(
        `${answer.municipality ?? ''}の${answer.procedure ?? '手続き'}について、どれを知りたいですか？`,
        [
          {
            id: 'field',
            text: '知りたい項目',
            type: 'single_select',
            options: Object.entries(FIELD_LABELS)
              // 実測で値があるものだけを選択肢に出す（空の項目を勧めない）
              .filter(([k]) => fields[k] != null)
              .map(([, label]) => label),
          },
        ],
      ),
    };
  }

  // 聞かれた項目が、そのページに書かれていない ＝ 取れずに帰った
  if (fields[field] == null) {
    return {
      answered: false,
      field,
      body: failureResponse(
        'NO_RESULTS',
        `${FIELD_LABELS[field]}は、このページには書かれていませんでした。`,
        { missing_field: field },
      ),
    };
  }

  return {
    answered: true,
    field,
    body: answerResponse([toResult(answer, sourceUrl)], { matched_field: field }),
  };
}
