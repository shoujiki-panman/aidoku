// 担当者の「内容確認 → 公開 → AIが取得した結果」の中身（純粋ロジック）。
//
// 画面の配線は verify-ui.mjs。ここは入力から verified/ の記録ファイルを組み立て、
// 「公開したら門番が何を返すか」を**門番の実物のコード**（verified_core.mjs /
// nlweb.mjs）で作る。画面用の別実装を作ると実物とずれるので、判定は輸入して使う。
//
// 入力チェックはここ（手元）で完結する。入力値をどこかへ送る通信は無い。
import { publishInto } from '../../gatekeeper/verified_core.mjs';
import { decideAsk } from '../../gatekeeper/nlweb.mjs';

// 画面の項目名（fix.js の FIELDS と同じ表記）→ 記録・門番の項目名
export const FIELD_MAP = {
  必要書類: 'required_documents',
  '窓口/オンライン可否': 'how_to_apply',
  期限: 'deadline',
  手数料: 'fee',
};

// プレビューで門番に聞く言い方（demand.mjs の FIELD_WORDS に確実に当たる語を使う）
export const FIELD_QUESTION = {
  required_documents: '必要書類は何ですか',
  how_to_apply: '窓口かオンラインか、どこで手続きできますか',
  deadline: '期限はいつまでですか',
  fee: '手数料はいくらですか',
};

// 入力1件のチェック。埋まっているかだけを手元で見る（LLMも通信も使わない）。
// 値の中身の正しさは機械では言えない＝確認者の名前を残すのはそのため。
export function checkEntry(entry) {
  const problems = [];
  if (!FIELD_MAP[entry.field] && !Object.values(FIELD_MAP).includes(entry.field)) {
    problems.push(`項目名が不明です: ${entry.field}`);
  }
  if (!String(entry.value ?? '').trim()) problems.push('値が空です');
  if (!String(entry.verifiedBy ?? '').trim()) problems.push('確認者が空です');
  return { ok: problems.length === 0, problems };
}

const toEn = (field) => FIELD_MAP[field] ?? field;

// verified/<区>-<手続き>.json の中身を組み立てる。
// existing（すでにある記録）を渡すと、入力した項目だけ version を +1 して置き換え、
// 触っていない項目はそのまま残す。now は Date（テストで固定できるように引数で渡す）。
export function mergeRecord({ existing, cell, entries, now }) {
  const record = existing
    ? structuredClone(existing)
    : {
        municipality: cell.muniName,
        municipality_id: cell.muniId,
        procedure: cell.procName,
        procedure_id: cell.procId,
        source: cell.url,
        fields: {},
      };
  record.fields ??= {};

  const publishedAt = now.toISOString();
  // 確認日は担当者の日付＝日本の日付で書く（toISOStringはUTCなので深夜0時台に1日ずれる。
  // 実行環境のタイムゾーンにも依存させない）
  const verifiedAt = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Tokyo' }).format(now);
  for (const entry of entries) {
    const en = toEn(entry.field);
    const prev = record.fields[en];
    record.fields[en] = {
      value: String(entry.value).trim(),
      conditions: String(entry.conditions ?? '').trim() || null,
      verified_by: String(entry.verifiedBy).trim(),
      verified_at: verifiedAt,
      published_at: publishedAt,
      version: (prev?.version ?? 0) + 1,
      status: 'published',
    };
  }
  return record;
}

export const recordFileName = (record) =>
  `${record.municipality_id}-${record.procedure_id}.json`;

// 実測の答えがまだ無いページ用の骨組み（build_answers.mjs が作る形と同じ・全項目null）。
// 「実測では読み取れていない」状態をそのまま表す。値は作らない。
export function skeletonAnswer(cell) {
  return {
    procedure: cell.procName,
    municipality: cell.muniName,
    source: cell.url,
    measured_at: cell.generatedAt || null,
    fields: { required_documents: null, how_to_apply: null, deadline: null, fee: null },
    note: 'デジタル庁OSS「源内」のAIアプリ仕様に準拠した第三者調査（AI読）による実測値です。行政機関の公式発表ではありません。',
  };
}

// 「公開したらAIが取得する結果」。measured（実測の答え）に record を重ね、
// 門番の実物の判定（decideAsk）でその項目の応答を作る。
// 返り値: { field, question, decided }（decided.body が門番の返すJSONそのもの）
export function previewAsk({ measured, record, field }) {
  const en = toEn(field);
  const answer = publishInto(structuredClone(measured), record);
  const question = FIELD_QUESTION[en] ?? String(field);
  return { field: en, question, decided: decideAsk(answer, question, answer.source) };
}
