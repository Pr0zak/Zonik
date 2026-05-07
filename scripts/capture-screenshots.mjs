// Capture screenshots of key Zonik web pages for the README.
// Usage: node scripts/capture-screenshots.mjs [base-url]
// Default base-url: http://10.0.0.205:3000
//
// Uses Playwright (npx playwright). Saves PNGs to docs/screenshots/.

import { chromium } from 'playwright';
import { mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, '..');
const OUT = resolve(ROOT, 'docs/screenshots');
const BASE = process.argv[2] || 'http://10.0.0.205:3000';

const PAGES = [
    { route: '/',          file: 'dashboard.png',  waitFor: 'h1, h2', settle: 1500 },
    { route: '/library',   file: 'library.png',    waitFor: 'table, [data-track], img', settle: 2000 },
    { route: '/discover',  file: 'discover.png',   waitFor: 'main', settle: 2500 },
    { route: '/downloads', file: 'downloads.png',  waitFor: 'main', settle: 1500 },
    { route: '/map',       file: 'map.png',        waitFor: 'svg, canvas', settle: 3500 },
    { route: '/stats',     file: 'stats.png',      waitFor: 'canvas, svg', settle: 3000 },
];

await mkdir(OUT, { recursive: true });

const browser = await chromium.launch();
const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2,
    colorScheme: 'dark',
});
const page = await ctx.newPage();

for (const p of PAGES) {
    const url = BASE + p.route;
    process.stdout.write(`  ${p.route.padEnd(12)}`);
    try {
        await page.goto(url, { waitUntil: 'networkidle', timeout: 30000 });
        try { await page.waitForSelector(p.waitFor, { timeout: 5000 }); } catch {}
        await page.waitForTimeout(p.settle);
        await page.screenshot({ path: resolve(OUT, p.file), fullPage: false });
        console.log(`✓ ${p.file}`);
    } catch (e) {
        console.log(`✗ ${e.message.split('\n')[0]}`);
    }
}

await browser.close();
console.log(`\nSaved ${PAGES.length} screenshots to ${OUT}`);
