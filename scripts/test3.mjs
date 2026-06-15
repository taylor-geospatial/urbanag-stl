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

const ins = await page.evaluate(() => ({
  cool: document.getElementById('ins-cool').textContent,
  park: document.getElementById('ins-park').textContent,
  veg: document.getElementById('ins-veg').textContent,
  pri: document.getElementById('ins-pri').textContent,
}));
await page.screenshot({ path: '/tmp/v3_default.png' });

// priority layer
await page.evaluate(() => { const c = document.getElementById('lyr-priority'); c.checked = true; c.dispatchEvent(new Event('change')); });
await new Promise((r) => setTimeout(r, 1500));
await page.screenshot({ path: '/tmp/v3_priority.png' });

// shade-hours heatmap (turn priority off first)
await page.evaluate(() => {
  let c = document.getElementById('lyr-priority'); c.checked = false; c.dispatchEvent(new Event('change'));
  c = document.getElementById('lyr-heat'); c.checked = false; c.dispatchEvent(new Event('change')); // hide heat to see shade
  c = document.getElementById('lyr-shadehours'); c.checked = true; c.dispatchEvent(new Event('change'));
});
await new Promise((r) => setTimeout(r, 4000));
await page.screenshot({ path: '/tmp/v3_shade.png' });

console.log('insights:', ins);
console.log('pageerrors:', errs.length ? errs : 'none');
await browser.close();
