// 公開データの目次（data/index.json）を、実体と突き合わせる。
// 目次は「AIが最初に読む1枚」なので、ここがズレると全部の入口が嘘になる。
// 数字は export_data_index.py がファイルから読んで書く。ここではそれを検算する。
import { readFileSync, existsSync, statSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const dataDir = join(here, 'data');
const idx = JSON.parse(readFileSync(join(dataDir, 'index.json'), 'utf8'));

let pass = 0, fail = 0;
const ok = (name, cond, detail) => {
  if (cond) { pass++; return; }
  fail++;
  console.log(`FAIL ${name}${detail ? ` — ${detail}` : ''}`);
};

// --- 自己記述 ---
ok('自分自身を指している', idx.self_description?.path === 'index.json');
ok('base_url がある', /^https:\/\/.+\/data\/$/.test(idx.base_url || ''), idx.base_url);
ok('公式発表ではないと明示', idx.publisher?.official === false);
ok('ライセンスがある', idx.license?.id === 'CC-BY-4.0');
ok('自治体の実文は対象外と明示', /agent_value/.test(idx.license?.does_not_cover || ''));
ok('スキルへ案内している', idx.skill?.path?.endsWith('SKILL.md'));
ok('スキルが実在する', existsSync(join(here, 'data', idx.skill.path)));

// --- 目次に載っているファイルが、実在して中身も一致するか ---
ok('データが1件以上', idx.datasets?.length >= 8, `${idx.datasets?.length}件`);
for (const d of idx.datasets) {
  const p = join(dataDir, d.path);
  ok(`${d.path} が実在する`, existsSync(p));
  if (!existsSync(p)) continue;
  const raw = readFileSync(p);
  // 手書きの数字が紛れ込んでいないか。1バイトでも違えば落ちる
  ok(`${d.path} の bytes が実体と一致`, d.bytes === statSync(p).size, `${d.bytes} vs ${statSync(p).size}`);
  ok(`${d.path} の sha256 が実体と一致`, d.sha256 === createHash('sha256').update(raw).digest('hex'));
  ok(`${d.path} に説明がある`, (d.description || '').length >= 10);
  if (d.records && d.records.path === 'row') {
    // CSV は1行1観測。見出し行を除いた行数で数える
    const text = raw.toString('utf8');
    const rows = text.split('\n').filter((l) => l.trim()).length - 1;
    ok(`${d.path} の行数が実体と一致`, rows === d.records.count, `${d.records.count} vs ${rows}`);
    ok(`${d.path} に列の説明がある`, Object.keys(d.columns || {}).length >= 5);
    const head = text.split('\n')[0].replace(/\r$/, '').split(',');
    ok(`${d.path} の見出しと列の説明が一致`,
      head.every((h) => h in (d.columns || {})), head.join('|'));
  } else if (d.records) {
    const doc = JSON.parse(raw.toString('utf8'));
    const got = doc[d.records.path];
    ok(`${d.path} の件数が実体と一致`, Array.isArray(got) && got.length === d.records.count,
      `${d.records.count} vs ${Array.isArray(got) ? got.length : typeof got}`);
  }
}

// --- 被覆。ここを盛ると「全国を測った」に見えてしまう ---
const cov = idx.coverage;
const procs = JSON.parse(readFileSync(join(dataDir, 'procedures.json'), 'utf8')).procedures;
const measured = procs.reduce((n, p) =>
  n + JSON.parse(readFileSync(join(dataDir, p.file), 'utf8')).municipalities.length, 0);
ok('測ったセル数が実体と一致', cov.measured_cells === measured, `${cov.measured_cells} vs ${measured}`);
ok('全国のセル数が積と一致', cov.japan.cells === cov.japan.municipalities * cov.procedures.length);
ok('被覆率が計算と一致',
  Math.abs(cov.japan.measured_ratio - measured / cov.japan.cells) < 1e-4, String(cov.japan.measured_ratio));
ok('全国を測ったと誤解させない', cov.japan.measured_ratio < 0.02, String(cov.japan.measured_ratio));
ok('未測定は0点ではないと書いてある', /まだ調べていない/.test(cov.note || ''));

// --- 来歴。記録が無いなら無いと言えているか ---
const pv = idx.provenance;
ok('測定条件のキーを列挙している', pv.condition_keys?.includes('model_version'));
for (const p of procs) {
  ok(`${p.id} の来歴がある`, !!pv.by_procedure?.[p.id]);
  ok(`${p.id} の回数が23`, pv.by_procedure?.[p.id]?.runs === 23, String(pv.by_procedure?.[p.id]?.runs));
}
// Python の None がそのまま公開JSONへ漏れていないか
const flat = JSON.stringify(idx);
ok('None が漏れていない', !/None/.test(flat));
ok('undefined が漏れていない', !/undefined/.test(flat));
if (pv.unrecorded?.length) {
  ok('未記録なら理由を書いている', /断定できない|区別できない/.test(pv.note || ''), pv.note);
}

// --- 較正。ここを黙ると時系列が誤読される ---
const cal = idx.calibration;
for (const p of procs) ok(`${p.id} の較正状況がある`, !!cal.by_procedure?.[p.id]);
const missing = procs.filter((p) => cal.by_procedure[p.id].rows === 0).map((p) => p.id);
ok('較正の欠けを正しく申告', JSON.stringify(cal.missing.sort()) === JSON.stringify(missing.sort()),
  `${cal.missing} vs ${missing}`);
if (missing.length) ok('欠けているなら注意書きがある', /区別できない/.test(cal.note || ''));

console.log(`${pass} PASS / ${fail} FAIL`);
process.exit(fail ? 1 : 0);
