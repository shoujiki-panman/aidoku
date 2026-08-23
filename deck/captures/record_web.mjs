// 提出用のデモ操作動画（60秒以内・無音・1600×900）を、公開画面の実操作から録画する。
//   cd web && python3 -m http.server 4199
//   node record_web.mjs <出力先ディレクトリ>   → <出力先>/*.webm
//   ffmpeg -i <出力先>/*.webm -an -c:v libx264 -pix_fmt yuv420p \
//          -preset slow -crf 22 -movflags +faststart -y demo.mp4
//
// ★scrollIntoView は使わない（headless で真っ白なフレームになったことがある）。
//   位置は getBoundingClientRect で測って window.scrollTo({behavior:'smooth'}) で送る。
//
// 流れ: 23区の地図 → 世田谷区を押す → 転入届を開いて「次にやること」
//       → AIの道のり（どこで力尽きたか・点の付け方）→ 調査データ一覧 → 自分のAIに持たせる
import { chromium } from '/Users/tanumashuu/Documents/Codex/2026-07-22/mu/mulmoclaude/node_modules/playwright/index.mjs';

const OUT = process.argv[2];
const BASE = 'http://127.0.0.1:4199';

const browser = await chromium.launch();
const ctx = await browser.newContext({
  viewport: { width: 1600, height: 900 },
  recordVideo: { dir: OUT, size: { width: 1600, height: 900 } },
});
const page = await ctx.newPage();

async function glideTo(sel, offset = 90, pause = 2500) {
  await page.evaluate(([s, o]) => {
    const el = document.querySelector(s);
    if (el) window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - o, behavior: 'smooth' });
  }, [sel, offset]);
  await page.waitForTimeout(pause);
}

// 1) 23区の地図（色が濃い区ほど読み取れた項目が多い）
await page.goto(`${BASE}/`, { waitUntil: 'networkidle' });
await page.waitForSelector('#wardmap svg path', { timeout: 15000 });
await page.waitForTimeout(4500);

// 2) 世田谷区を押す → その区の3手続きが出る（画面は結果へ送られる）
await page.click('#wardmap path[data-name="世田谷区"]');
await page.waitForTimeout(5000);

// 3) 転入届を開く → 読めなかった項目と「あなたが次にやること」
await page.click('#lookup-result details:first-of-type summary');
await page.waitForTimeout(7000);

// 4) AIの道のり — どこで力尽きたか
await page.goto(`${BASE}/journey.html`, { waitUntil: 'networkidle' });
await page.waitForSelector('#show-choices', { timeout: 15000 });
await page.waitForTimeout(2000);
await glideTo('#map-heading', 90, 4500);
await glideTo('.stage__node[data-kind="stop"]', 140, 5500);

// 5) その一歩をAIがどう選んだか（点の付け方）
await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' }));
await page.waitForTimeout(1200);
await page.click('#show-choices');
await page.waitForTimeout(800);
await glideTo('#choices', 120, 6500);

// 6) いつ何を測ったか（調査データ一覧）
await page.goto(`${BASE}/archive.html`, { waitUntil: 'networkidle' });
await page.waitForTimeout(4500);

// 7) 実測を自分のAIに持たせる
await page.goto(`${BASE}/skill.html`, { waitUntil: 'networkidle' });
await page.waitForTimeout(4500);

await ctx.close(); // ← 動画はここで書き出される
await browser.close();
console.log('recorded');
