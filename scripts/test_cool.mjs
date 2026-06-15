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
await page.goto('http://localhost:8012/', { waitUntil: 'networkidle2', timeout: 60000 });
await page.waitForFunction(() => document.getElementById('loading')?.classList.contains('hidden'), { timeout: 45000 });
await new Promise((r) => setTimeout(r, 7000));
const ins = await page.evaluate(() => ({
  cool: document.getElementById('ins-cool').textContent,
  park: document.getElementById('ins-park').textContent,
  veg: document.getElementById('ins-veg').textContent, pri: document.getElementById('ins-pri').textContent,
}));
// cooling layer on (heat dims), tilt down a bit for the choropleth
await page.evaluate(() => { const c = document.getElementById('lyr-cooling'); c.checked = true; c.dispatchEvent(new Event('change')); });
await new Promise((r) => setTimeout(r, 3500));
await page.screenshot({ path: '/tmp/cool_shot.png' });
console.log('insights:', ins);
console.log('pageerrors:', errs.length ? errs : 'none');
await browser.close();
