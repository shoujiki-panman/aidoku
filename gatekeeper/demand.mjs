// 署名つきアクセスと、窓口が持つ対応情報の有無を集計する。最終回答の評価ではない。
//
// 貯め方: KV に追記していく（1リクエスト＝1件）。中身はキーのメタデータに入れる。
//   → 集計のときに list() だけで読めるので、件数ぶんの get が要らない。
// 数え方: 読み出し時に集計する（KVには足し算がないので、書き込み時に集計すると
//   同時アクセスで数え落ちる。追記だけにしておけば落ちない）。
//
// 記録するのは「署名を付けて来たAIエージェント」だけ。
// 署名なしは記録しない（人かAIかは判別しない）。
// 検証に失敗したものも記録はする（門番は拒否しない設計。「偽の名乗りが来た」も観測値）。
// ただし **どのAIが来たかの集計には、検証に成功した名乗りだけ**を入れる。
// 他人の公開 keyid は誰でも書けるので、検証前の名乗りは自称にすぎない。

const PREFIX = 'ask:';
const LIST_LIMIT = 1000;

// 探し物の表記ゆれを軽くならす（全角空白・連続空白・前後空白）
export function normalizeQuery(q) {
  if (!q) return null;
  return q.replace(/　/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 120) || null;
}

// 探し物の言葉から、答えのどの項目を聞かれているかを見当づける
const FIELD_WORDS = {
  required_documents: ['必要書類', '必要なもの', '持ち物', '持っていくもの', '書類'],
  fee: ['手数料', '費用', '料金', 'いくら', '無料'],
  deadline: ['期限', 'いつまで', '日以内', '締切'],
  how_to_apply: ['オンライン', '窓口', '郵送', '来庁', 'どこで'],
};

// 答えとして扱う項目名はこの4つだけ（確認済み情報の項目名検証にも使う）
export const KNOWN_FIELDS = Object.keys(FIELD_WORDS);

export function matchField(lookingFor) {
  if (!lookingFor) return null;
  for (const [field, words] of Object.entries(FIELD_WORDS)) {
    if (words.some((w) => lookingFor.includes(w))) return field;
  }
  return null;
}

// 実測（fields）と担当者確認済み（verified_fields）を1枚に重ねた読み取り用ビュー。
// 確認済みが優先。元の fields は書き換えない（実測は実測のまま残す）。
// verified_fields に載るのは公開中（published）の項目だけ（verified_sync.mjs が選ぶ）。
export function effectiveFields(answer) {
  const merged = { ...(answer?.fields ?? {}) };
  for (const [field, v] of Object.entries(answer?.verified_fields ?? {})) {
    if (v && v.value != null) merged[field] = v.value;
  }
  return merged;
}

// そのページについて、実測か確認済みか、どちらかの答えを1つでも持っているか。
export function hasAnyAnswer(answer) {
  if (!answer) return false;
  return Object.values(effectiveFields(answer)).some((v) => v != null);
}

// 質問に対応する項目を窓口が持っているか。未知の質問はnull。
// falseでも、素通し先や別の情報源からAIが回答できた可能性は残る。
export function isAnswered(answer, lookingFor) {
  const field = matchField(normalizeQuery(lookingFor));
  // HTTPアクセスだけでは質問も回答の成否も分からない。
  if (!field) return null;
  return effectiveFields(answer)[field] != null;
}

// 時刻を「新しいほど小さい数」に変換する（14桁固定。2603年まで桁あふれしない）
export function descendingStamp(ts) {
  const t = Date.parse(ts);
  return String(Number.isFinite(t) ? 2e13 - t : 2e13).padStart(14, '0');
}

export async function recordAsk(env, record, uniq) {
  if (!env?.DEMAND) return false;
  // キーは「新しいものが先頭に来る」順にする。
  // KV の list はキーの辞書順で返るので、時刻をそのまま入れると古い順に並ぶ。
  // 件数が上限に当たったとき、古い記録だけを見て新しい来訪が一切見えなくなるので、
  // 時刻を反転させて入れる（落ちるのは常に古いほう）。
  const key = `${PREFIX}${descendingStamp(record.ts)}:${uniq}`;
  await env.DEMAND.put(key, '', {
    metadata: {
      ts: record.ts,
      authority: record.authority,
      path: record.path,
      looking_for: normalizeQuery(record.looking_for),
      answered: record.verified === true && normalizeQuery(record.looking_for) ? record.answered : null,
      via: record.via ?? null,
      verified: record.verified,
      agent: record.agent,
    },
    // 90日で自然に消える（貯めっぱなしにしない）
    expirationTtl: 60 * 60 * 24 * 90,
  });
  return true;
}

export async function aggregate(env, { limit = LIST_LIMIT } = {}) {
  if (!env?.DEMAND) return null;

  const rows = [];
  let cursor;
  let truncated = false; // 全部は読めていない、を隠さないための印
  do {
    const res = await env.DEMAND.list({ prefix: PREFIX, limit: 1000, cursor });
    for (const k of res.keys) if (k.metadata) rows.push(k.metadata);
    cursor = res.list_complete ? undefined : res.cursor;
    if (cursor && rows.length >= limit) {
      truncated = true;
      break;
    }
  } while (cursor);

  const byAsk = new Map(); // 「どのページに・何を探しに来たか」ごとの集計
  const byAgent = new Map(); // どのAIが来て、どれだけ持ち帰れたか
  let answered = 0;
  let unanswered = 0;
  let unverified = 0; // 署名の検証に失敗した来訪（名乗りは自称なので数に入れない）
  let undetermined = 0; // 質問なし・特定不能など、対応情報の有無を判定できない分

  for (const raw of rows) {
    // 旧記録も補正する。質問なしの false は回答失敗の証拠ではない。
    const r = { ...raw, answered: raw.verified === true && normalizeQuery(raw.looking_for) ? raw.answered : null };
    if (r.answered === true) answered++;
    else if (r.answered === false) unanswered++;
    else if (r.verified === true) undetermined++;
    if (r.verified !== true) unverified++;

    // どのAIが来たか。**検証に成功した名乗りだけ**を数える。
    // 検証に失敗した名乗りは自称にすぎない（他人の公開 keyid を書けば誰でも名乗れる）ので、
    // ここに入れると「ChatGPTがN回来た」を誰でも作れてしまう。
    if (r.verified === true && r.agent) {
      const a = byAgent.get(r.agent) ?? { agent: r.agent, asks: 0, answered: 0, unanswered: 0 };
      a.asks++;
      if (r.answered === true) a.answered++;
      if (r.answered === false) a.unanswered++;
      byAgent.set(r.agent, a);
    }

    const key = `${r.authority}\t${r.path}\t${r.looking_for ?? ''}`;
    const cur = byAsk.get(key) ?? {
      authority: r.authority,
      path: r.path,
      looking_for: r.looking_for ?? null,
      count: 0,
      answered_count: 0,
      unanswered_count: 0,
      by_agent: {}, // どのAIが何回来て、取れたか（盤面のマスになる）
      first_seen: r.ts,
      last_seen: r.ts,
    };
    cur.count++;
    if (r.answered === true) cur.answered_count++;
    if (r.answered === false) cur.unanswered_count++;
    if (r.verified === true && r.agent) {
      const c = cur.by_agent[r.agent] ?? { asks: 0, answered: 0, unanswered: 0 };
      c.asks++;
      if (r.answered === true) c.answered++;
      if (r.answered === false) c.unanswered++;
      cur.by_agent[r.agent] = c;
    }
    if (r.ts < cur.first_seen) cur.first_seen = r.ts;
    if (r.ts > cur.last_seen) cur.last_seen = r.ts;
    byAsk.set(key, cur);
  }

  const all = [...byAsk.values()].sort((a, b) => b.count - a.count || b.unanswered_count - a.unanswered_count);

  const stamps = rows.map((r) => r.ts).filter(Boolean).sort();

  return {
    generated_at: new Date().toISOString(),
    totals: {
      asks: rows.length,
      answered,
      unanswered,
      undetermined, // 質問なしのHTTPアクセスも含む。聞き返し件数とは限らない
      unverified, // 署名の検証に失敗した来訪（「偽の名乗りが来た」という別の観測値）
      agents: byAgent.size,
    },
    // 全部を読めたのか、途中で打ち切ったのか。数字を見る人が判断できるように必ず出す。
    // 打ち切るときに落ちるのは古いほう（キーを時刻の降順にしてある）。
    coverage: {
      truncated,
      limit,
      from: stamps[0] ?? null,
      to: stamps[stamps.length - 1] ?? null,
    },
    // どのAIが来て、どれだけ手ぶらで帰ったか。**署名の検証に成功した名乗りだけ**。
    by_agent: [...byAgent.values()].sort((a, b) => b.asks - a.asks),
    // 窓口の対応情報がない質問。元ページを確認する候補であり、欠落の確定ではない。
    unanswered: all.filter((x) => x.unanswered_count > 0),
    all,
    note:
      '記録しているのは署名を付けて来たAIエージェントのアクセスだけです。' +
      '署名なしのアクセスは記録していません（人かAIかは判別していません）。' +
      'answered/unanswered は窓口が質問に対応する情報を持つかの判定で、AIの最終回答の成否ではありません。' +
      '質問のないアクセスは undetermined（判定対象外）です。' +
      '署名の検証に失敗したものも件数には含みます（totals.unverified）が、' +
      'どのAIが来たか（by_agent）は検証に成功した名乗りだけを数えています。' +
      'デジタル庁OSS「源内」のAIアプリ仕様に準拠した第三者調査（AI読）による実測値です。' +
      '行政機関の公式発表ではありません。',
  };
}

// 保存済み集計の訂正。元のアクセス件数・時刻は残し、質問のない判定だけを外す。
export function normalizeDemandSnapshot(input) {
  const data = structuredClone(input);
  const removed = new Map();
  for (const row of data.all ?? []) {
    if (normalizeQuery(row.looking_for)) continue;
    const yes = row.answered_count ?? 0;
    const no = row.unanswered_count ?? 0;
    data.totals.answered -= yes;
    data.totals.unanswered -= no;
    data.totals.undetermined = (data.totals.undetermined ?? 0) + yes + no;
    row.answered_count = 0;
    row.unanswered_count = 0;
    for (const [agent, counts] of Object.entries(row.by_agent ?? {})) {
      const lost = removed.get(agent) ?? { answered: 0, unanswered: 0 };
      lost.answered += counts.answered ?? 0;
      lost.unanswered += counts.unanswered ?? 0;
      removed.set(agent, lost);
      counts.answered = 0;
      counts.unanswered = 0;
    }
  }
  for (const agent of data.by_agent ?? []) {
    const lost = removed.get(agent.agent);
    if (lost) {
      agent.answered -= lost.answered;
      agent.unanswered -= lost.unanswered;
    }
  }
  data.unanswered = (data.all ?? []).filter((row) => row.unanswered_count > 0);
  return data;
}
