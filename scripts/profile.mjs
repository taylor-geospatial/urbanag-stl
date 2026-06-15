import puppeteer from 'puppeteer';

const browser = await puppeteer.launch({
  headless: 'new',
  args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader',
    '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'],
});
const page = await browser.newPage();
await page.setViewport({ width: 1400, height: 900, deviceScaleFactor: 1 });

const t0 = Date.now();
await page.goto('http://localhost:8011/', { waitUntil: 'domcontentloaded', timeout: 60000 });
await page.waitForFunction(() => document.getElementById('loading')?.classList.contains('hidden'), { timeout: 60000 });
const tLoaded = Date.now() - t0;

const res = await page.evaluate(() =>
  performance.getEntriesByType('resource')
    .filter((r) => /data\/|app\.js|maplibre|carto|arcgis/.test(r.name))
    .map((r) => ({
      name: r.name.split('/').slice(-1)[0].split('?')[0],
      kb: Math.round((r.transferSize || r.encodedBodySize || 0) / 1024),
      ms: Math.round(r.duration),
    }))
    .sort((a, b) => b.kb - a.kb)
    .slice(0, 12));

const nav = await page.evaluate(() => {
  const n = performance.getEntriesByType('navigation')[0] || {};
  return { domContentLoaded: Math.round(n.domContentLoadedEventEnd), responseEnd: Math.round(n.responseEnd) };
});

console.log(`\nTIME to data-loaded (loading overlay hidden): ${tLoaded} ms`);
console.log('top resources (kb / ms):');
for (const r of res) console.log(`  ${String(r.kb).padStart(6)} KB  ${String(r.ms).padStart(5)} ms  ${r.name}`);
await browser.close();
