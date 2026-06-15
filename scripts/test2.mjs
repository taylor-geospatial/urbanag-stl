import puppeteer from 'puppeteer';

const browser = await puppeteer.launch({
  headless: 'new',
  args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader',
    '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist', '--window-size=1680,1050'],
});
const page = await browser.newPage();
await page.setViewport({ width: 1680, height: 1050, deviceScaleFactor: 2 });
const errs = [];
page.on('pageerror', (e) => errs.push(e.message.slice(0, 160)));

await page.goto('http://localhost:8011/', { waitUntil: 'networkidle2', timeout: 60000 });
await page.waitForFunction(() => document.getElementById('loading')?.classList.contains('hidden'), { timeout: 45000 });
await new Promise((r) => setTimeout(r, 7000));

const roofN = await page.evaluate(() => window.__map ? 0 : (document.querySelectorAll('#heat-scene option').length));
const sceneOpts = await page.evaluate(() => [...document.querySelectorAll('#heat-scene option')].map((o) => o.textContent));
await page.screenshot({ path: '/tmp/s_default.png' });

// satellite verify view
await page.evaluate(() => { const c = document.getElementById('lyr-satellite'); c.checked = true; c.dispatchEvent(new Event('change')); });
await new Promise((r) => setTimeout(r, 6000));
await page.screenshot({ path: '/tmp/s_sat.png' });

// winter scene
await page.evaluate(() => { const c = document.getElementById('lyr-satellite'); c.checked = false; c.dispatchEvent(new Event('change')); const s = document.getElementById('heat-scene'); s.value = 'winter'; s.dispatchEvent(new Event('change')); });
await new Promise((r) => setTimeout(r, 2500));
await page.screenshot({ path: '/tmp/s_winter.png' });

console.log('heat scene options:', sceneOpts);
console.log('pageerrors:', errs.length ? errs : 'none');
await browser.close();
