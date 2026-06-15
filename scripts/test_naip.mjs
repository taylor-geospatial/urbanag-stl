import puppeteer from 'puppeteer';
const b=await puppeteer.launch({headless:'new',args:['--no-sandbox','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader','--ignore-gpu-blocklist','--window-size=1680,1050']});
const p=await b.newPage(); await p.setViewport({width:1680,height:1050,deviceScaleFactor:2});
const errs=[]; p.on('pageerror',e=>errs.push(e.message.slice(0,140)));
await p.goto('https://research.taylorgeospatial.org/urbanag-stl/',{waitUntil:'networkidle2',timeout:60000});
await p.waitForFunction(()=>document.getElementById('loading')?.classList.contains('hidden'),{timeout:45000});
await new Promise(r=>setTimeout(r,7000));
// NAIP on, heat off, lower NDVI threshold; flatten + zoom a touch for verification feel
await p.evaluate(()=>{
  for (const [id,on] of [['lyr-naip',true],['lyr-heat',false]]){const c=document.getElementById(id);c.checked=on;c.dispatchEvent(new Event('change'));}
  const s=document.getElementById('ndvi-thr'); s.value='10'; s.dispatchEvent(new Event('input'));
});
await new Promise(r=>setTimeout(r,6000));
const label=await p.evaluate(()=>document.querySelector('#lyr-naip').closest('.toggle').querySelector('.lbl').textContent);
await p.screenshot({path:'/tmp/naip_live.png'});
console.log('naip label:',label,'errs:',errs.length?errs:'none');
await b.close();
