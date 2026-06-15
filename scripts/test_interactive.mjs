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
await new Promise((r) => setTimeout(r, 6000));

// set morning (07:40) for long shadows
await page.evaluate(() => {
  const t = document.getElementById('time');
  t.value = '460'; t.dispatchEvent(new Event('input'));
});
await new Promise((r) => setTimeout(r, 3500));
await page.screenshot({ path: '/tmp/stl_morning.png' });

// click a building near downtown center to trigger garden advice
await page.mouse.click(900, 560);
await new Promise((r) => setTimeout(r, 1200));
const infoShown = await page.evaluate(() => !document.getElementById('info').classList.contains('hidden'));
const advice = await page.evaluate(() => document.querySelector('#info .advice')?.textContent || '(none)');
await page.screenshot({ path: '/tmp/stl_click.png' });

console.log('info card shown:', infoShown);
console.log('advice:', advice.slice(0, 200));
console.log('pageerrors:', errs.length ? errs : 'none');
await browser.close();
