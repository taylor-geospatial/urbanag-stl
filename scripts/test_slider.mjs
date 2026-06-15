import puppeteer from 'puppeteer';
const b=await puppeteer.launch({headless:'new',args:['--no-sandbox','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader','--ignore-gpu-blocklist','--window-size=1680,1050']});
const p=await b.newPage(); await p.setViewport({width:1680,height:1050,deviceScaleFactor:2});
const errs=[]; p.on('pageerror',e=>errs.push(e.message.slice(0,140)));
await p.goto('http://localhost:8012/',{waitUntil:'networkidle2',timeout:60000});
await p.waitForFunction(()=>document.getElementById('loading')?.classList.contains('hidden'),{timeout:45000});
await new Promise(r=>setTimeout(r,7000));
// lower the NDVI threshold to 0.05
await p.evaluate(()=>{const s=document.getElementById('ndvi-thr');s.value='5';s.dispatchEvent(new Event('input'));});
await new Promise(r=>setTimeout(r,2500));
const lowN=await p.evaluate(()=>document.getElementById('ndvi-count').textContent);
const lowVal=await p.evaluate(()=>document.getElementById('ndvi-val').textContent);
await p.screenshot({path:'/tmp/slider_low.png'});
console.log('thr',lowVal,'->',lowN,'errs',errs.length?errs:'none');
await b.close();
