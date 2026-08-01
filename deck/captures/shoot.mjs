// 提出用キャプチャ（1600×900）を実画面から撮る。
// playwright は mulmoclaude の node_modules を借りる（mulmoclaude 自体には触らない）。
import { chromium } from '/Users/tanumashuu/Documents/Codex/2026-07-22/mu/mulmoclaude/node_modules/playwright/index.mjs';

const OUT = process.argv[2];
const GENNAI = 'http://[::1]:5174/apps/team-aidoku/aidoku/invoke';
const DASH = 'http://127.0.0.1:4191/';
const SETAGAYA = 'https://www.city.setagaya.lg.jp/kurashi/kosekijuumin/11531.html';

const browser = await chromium.launch();
const page = await browser.newPage({
  viewport: { width: 1600, height: 900 },
  deviceScaleFactor: 1, // 提出フォームの推奨(1600×900)ちょうどで出す
});

// ── 1・2枚目: 源内のAIアプリ画面で世田谷区を実行 ──
await page.goto(GENNAI, { waitUntil: 'networkidle' });
await page.fill('input#url, input[name="url"], input[type="text"]', SETAGAYA);
await page.click('button[type="submit"]');
await page.waitForSelector('text=住民がこのページを読んだAIに聞くと', { timeout: 30000 });
await page.waitForTimeout(1200);

// 1枚目: 住民のAIの答え（「分かりません」）＋なぜ答えられないのか
await page.evaluate(() => {
  const h = [...document.querySelectorAll('h1,h2,h3')]
    .find((e) => e.textContent.includes('住民がこのページを読んだAIに聞くと'));
  if (h) h.scrollIntoView({ block: 'start' });
  window.scrollBy(0, -110);
});
await page.waitForTimeout(600);
await page.screenshot({ path: `${OUT}/01_gennai_answer.png` });

// 2枚目: 直すと、住民のAIはこう答えられるようになります（＋右に23区の履歴）
await page.evaluate(() => {
  const h = [...document.querySelectorAll('h1,h2,h3')]
    .find((e) => e.textContent.includes('直すと、住民のAIはこう答えられる'));
  if (h) h.scrollIntoView({ block: 'start' });
  window.scrollBy(0, -110);
});
await page.waitForTimeout(600);
await page.screenshot({ path: `${OUT}/02_gennai_fix.png` });

// 3枚目: 公開ダッシュボード（同じ質問・違う答え）
await page.goto(DASH, { waitUntil: 'networkidle' });
await page.waitForSelector('.hero-grid', { timeout: 15000 });
await page.evaluate(() => {
  document.getElementById('hero-heading').scrollIntoView({ block: 'start' });
  window.scrollBy(0, 8);
});
await page.waitForTimeout(600);
await page.screenshot({ path: `${OUT}/03_dashboard_compare.png` });

await browser.close();
console.log('done');
