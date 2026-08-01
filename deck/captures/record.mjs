// 提出用のデモ操作動画（60秒以内・無音）を、実画面の操作から録画する。
// playwright は mulmoclaude の node_modules を借りる（このリポジトリに依存を足さない）。
//
//   node record.mjs <出力先ディレクトリ>
//   → <出力先>/demo.webm が出る。mp4 化は README の ffmpeg コマンド。
//
// 流れ: 源内のAIアプリ一覧 → AI読を開く → 世田谷区を診断（答えは「分かりません」）
//       → 理由 → 直し方 → 港区を診断（4項目とも答えられる）
import { chromium } from '/Users/tanumashuu/Documents/Codex/2026-07-22/mu/mulmoclaude/node_modules/playwright/index.mjs';

const OUT = process.argv[2];
const BASE = 'http://[::1]:5174';
const SETAGAYA = 'https://www.city.setagaya.lg.jp/kurashi/kosekijuumin/11531.html';
const MINATO = 'https://www.city.minato.tokyo.jp/shibamadosa/kurashi/todokede/hikkoshi/tennyu.html';

const browser = await chromium.launch();
const ctx = await browser.newContext({
  viewport: { width: 1600, height: 900 },
  recordVideo: { dir: OUT, size: { width: 1600, height: 900 } },
});
const page = await ctx.newPage();

// ゆっくり読める速さでスクロールする（見出しを画面の上に持ってくる）
async function scrollToHeading(text, pause = 3000) {
  await page.evaluate((t) => {
    const h = [...document.querySelectorAll('h1,h2,h3')].find((e) => e.textContent.includes(t));
    if (h) window.scrollTo({ top: h.getBoundingClientRect().top + window.scrollY - 150, behavior: 'smooth' });
  }, text);
  await page.waitForTimeout(pause);
}

async function diagnose(url, { typeDelay = 28 } = {}) {
  const box = page.locator('input[type="text"]').first();
  await box.click();
  await box.fill('');
  await box.type(url, { delay: typeDelay });
  await page.waitForTimeout(600);
  await page.click('button[type="submit"]');
  await page.waitForSelector('text=住民がこのページを読んだAIに聞くと', { timeout: 30000 });
  await page.waitForTimeout(900);
}

// 1) AIアプリ一覧に「AI読」が並んでいるところ
await page.goto(`${BASE}/apps`, { waitUntil: 'networkidle' });
await page.waitForTimeout(3200);

// 2) AI読を開く（入力フォームは源内がAPIの定義から自動生成している）
await page.goto(`${BASE}/apps/team-aidoku/aidoku/invoke`, { waitUntil: 'networkidle' });
await page.waitForTimeout(2800);

// 3) 世田谷区を診断 → 住民のAIの答えは全部「分かりません」
await diagnose(SETAGAYA);
await scrollToHeading('住民がこのページを読んだAIに聞くと', 7000);

// 4) なぜ答えられないのか（判定AIの記録をそのまま見せる）
await scrollToHeading('なぜ答えられないのか', 7000);

// 5) 直すと、住民のAIはこう答えられるようになります
await scrollToHeading('直すと、住民のAIはこう答えられる', 7000);

// 6) 港区で同じことをすると、4項目とも答えられる
await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' }));
await page.waitForTimeout(1200);
await diagnose(MINATO, { typeDelay: 16 });
await scrollToHeading('住民がこのページを読んだAIに聞くと', 8000);

await ctx.close(); // ← 動画はここで書き出される
await browser.close();
console.log('recorded');
