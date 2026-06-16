import puppeteer from 'puppeteer';
const b=await puppeteer.launch({headless:'new',args:['--no-sandbox','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader','--ignore-gpu-blocklist','--window-size=1680,1050']});
const p=await b.newPage(); await p.setViewport({width:1680,height:1050,deviceScaleFactor:2});
await p.goto('https://research.taylorgeospatial.org/urbanag-stl/',{waitUntil:'networkidle2',timeout:60000});
await p.waitForFunction(()=>document.getElementById('loading')?.classList.contains('hidden'),{timeout:45000});
await new Promise(r=>setTimeout(r,8000));
let found=null;
for(let gx=720; gx<=1320 && !found; gx+=36){
  for(let gy=340; gy<=840 && !found; gy+=36){
    await p.mouse.click(gx,gy);
    const sparks=await p.evaluate(()=>document.getElementById('info').classList.contains('hidden')?-1:document.querySelectorAll('#info .spark').length);
    if(sparks>=2) found={gx,gy,sparks};
  }
}
const body=await p.evaluate(()=>document.getElementById('info-body')?.innerText||'');
await p.screenshot({path:'/tmp/click_live.png'});
console.log('found(2 sparklines):',found);
console.log('card:', body.replace(/\n+/g,' | ').slice(0,240));
await b.close();
