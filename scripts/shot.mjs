import puppeteer from 'puppeteer';

const url = process.argv[2] || 'http://localhost:8011/';
const out = process.argv[3] || '/tmp/stl_shot.png';

const browser = await puppeteer.launch({
  headless: 'new',
  args: [
    '--no-sandbox', '--disable-setuid-sandbox',
    '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader',
    '--ignore-gpu-blocklist', '--enable-webgl', '--window-size=1680,1050',
  ],
});
const page = await browser.newPage();
await page.setViewport({ width: 1680, height: 1050, deviceScaleFactor: 2 });
const errs = [];
page.on('console', (m) => { if (m.type() === 'error') errs.push(m.text().slice(0, 200)); });
page.on('pageerror', (e) => errs.push('PAGEERR ' + e.message.slice(0, 200)));

await page.goto(url, { waitUntil: 'networkidle2', timeout: 60000 });
try {
  await page.waitForFunction(
    () => document.getElementById('loading')?.classList.contains('hidden'),
    { timeout: 45000 });
} catch { console.log('loading-hidden wait timed out'); }
await new Promise((r) => setTimeout(r, 8000)); // flyTo + basemap tiles + shadow pass
await page.screenshot({ path: out });
console.log('saved', out);
console.log('console errors:', errs.length ? errs.slice(0, 12) : 'none');
await browser.close();
