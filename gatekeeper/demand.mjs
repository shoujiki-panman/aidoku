// 門番が集めた「AIが何を探しに来て、取れたか／取れずに帰ったか」をデータにする。
//
// 貯め方: KV に追記していく（1リクエスト＝1件）。中身はキーのメタデータに入れる。
//   → 集計のときに list() だけで読めるので、件数ぶんの get が要らない。
// 数え方: 読み出し時に集計する（KVには足し算がないので、書き込み時に集計すると
//   同時アクセスで数え落ちる。追記だけにしておけば落ちない）。
//
// 記録するのは「署名で身元が証明されたAIエージェント」だけ。
// 署名なし＝人間のアクセスは、そもそも呼ばれない（worker側で先に素通しする）。

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

export function matchField(lookingFor) {
  if (!lookingFor) return null;
  for (const [field, words] of Object.entries(FIELD_WORDS)) {
    if (words.some((w) => lookingFor.includes(w))) return field;
  }
  return null;
}

// 「探しに来たものが、実際に取れたか」を判定する。
// ページに答えの束があっても、聞かれた項目が空なら取れていない＝取れずに帰った。
export function isAnswered(answer, lookingFor) {
  if (!answer) return false;
  const fields = answer.fields ?? {};
  const field = matchField(normalizeQuery(lookingFor));
  if (field) return fields[field] != null;
  // 何を聞かれたか分からないときは、1つでも答えがあれば取れた扱い
  return Object.values(fields).some((v) => v != null);
}

export async function recordAsk(env, record, uniq) {
  if (!env?.DEMAND) return false;
  // キーは時刻順に並ぶようにする（新しい順に読み出したいので降順にはしない＝集計は全件走査）
  const key = `${PREFIX}${record.ts}:${uniq}`;
  await env.DEMAND.put(key, '', {
    metadata: {
      ts: record.ts,
      authority: record.authority,
      path: record.path,
      looking_for: normalizeQuery(record.looking_for),
      answered: record.answered,
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
  do {
    const res = await env.DEMAND.list({ prefix: PREFIX, limit: 1000, cursor });
    for (const k of res.keys) if (k.metadata) rows.push(k.metadata);
    cursor = res.list_complete ? undefined : res.cursor;
  } while (cursor && rows.length < limit);

  const byAsk = new Map(); // 「どのページに・何を探しに来たか」ごとの集計
  const agents = new Set();
  let answered = 0;
  let unanswered = 0;

  for (const r of rows) {
    if (r.agent) agents.add(r.agent);
    if (r.answered === true) answered++;
    else if (r.answered === false) unanswered++;

    const key = `${r.authority}\t${r.path}\t${r.looking_for ?? ''}`;
    const cur = byAsk.get(key) ?? {
      authority: r.authority,
      path: r.path,
      looking_for: r.looking_for ?? null,
      count: 0,
      answered_count: 0,
      unanswered_count: 0,
      first_seen: r.ts,
      last_seen: r.ts,
    };
    cur.count++;
    if (r.answered === true) cur.answered_count++;
    if (r.answered === false) cur.unanswered_count++;
    if (r.ts < cur.first_seen) cur.first_seen = r.ts;
    if (r.ts > cur.last_seen) cur.last_seen = r.ts;
    byAsk.set(key, cur);
  }

  const all = [...byAsk.values()].sort((a, b) => b.count - a.count || b.unanswered_count - a.unanswered_count);

  return {
    generated_at: new Date().toISOString(),
    totals: {
      asks: rows.length,
      answered,
      unanswered,
      agents: agents.size,
    },
    // ここが本体。AIが探しに来たのに取れずに帰った＝そのページに足りていない情報。
    // そのまま「区役所への更新依頼リスト」になる。
    unanswered: all.filter((x) => x.unanswered_count > 0),
    all,
    note:
      '署名で身元が確認できたAIエージェントのアクセスのみを記録しています。' +
      '人（ブラウザ）のアクセスは記録していません。',
  };
}
