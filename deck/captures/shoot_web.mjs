// 提出用の静止画（1600×900）を、公開画面の実物から撮る。
//   cd web && python3 -m http.server 4199
//   node shoot_web.mjs <出力先ディレクトリ>
//
// deviceScaleFactor: 1 で、ちょうど 1600×900 で出す（提出フォームの推奨）。
// ★scrollIntoView は使わない。headless で真っ白なフレームになったことがある。
//   位置は getBoundingClientRect で測って window.scrollTo で送る。
import { chromium } from '/Users/tanumashuu/Documents/Codex/2026-07-22/mu/mulmoclaude/node_modules/playwright/index.mjs';

const OUT = process.argv[2];
const BASE = 'http://127.0.0.1:4199';

const browser = await chromium.launch();
const page = await browser.newPage({
  viewport: { width: 1600, height: 900 },
  deviceScaleFactor: 1,
});

const topOf = (sel) => page.evaluate(
  (s) => document.querySelector(s).getBoundingClientRect().top + window.scrollY, sel);
const scrollTo = async (y) => {
  await page.evaluate((v) => window.scrollTo(0, v), y);
  await page.waitForTimeout(500);
};

// ── cap_map.png: トップ画面。ヘッダーから23区の地図まで ──
await page.goto(`${BASE}/`, { waitUntil: 'networkidle' });
await page.waitForSelector('#wardmap svg path', { timeout: 15000 });
await page.waitForTimeout(1500);
await page.screenshot({ path: `${OUT}/cap_map.png` });

// ── poster.png: 区を押した結果。転入届を開いて「次にやること」まで見せる ──
await page.click('#wardmap path[data-name="世田谷区"]');
await page.waitForTimeout(1500);
await page.click('#lookup-result details:first-of-type summary');
await page.waitForTimeout(1200);
await scrollTo((await topOf('#lookup-result')) - 70);
await page.screenshot({ path: `${OUT}/poster.png` });

// ── cap_journey.png: AIが歩いた道のり。判断（点の付け方）を開いた状態 ──
await page.goto(`${BASE}/journey.html`, { waitUntil: 'networkidle' });
await page.waitForSelector('#show-choices', { timeout: 15000 });
await page.click('#show-choices');
await page.waitForTimeout(1000);
await scrollTo((await topOf('#map-heading')) - 78);
await page.screenshot({ path: `${OUT}/cap_journey.png` });

await browser.close();
console.log('shot');
