import puppeteer from 'puppeteer';
const b=await puppeteer.launch({headless:'new',args:['--no-sandbox','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader','--ignore-gpu-blocklist','--window-size=1680,1050']});
const p=await b.newPage(); await p.setViewport({width:1680,height:1050,deviceScaleFactor:2});
await p.goto('https://research.taylorgeospatial.org/urbanag-stl/',{waitUntil:'networkidle2',timeout:60000});
await p.waitForFunction(()=>document.getElementById('loading')?.classList.contains('hidden'),{timeout:45000});
await new Promise(r=>setTimeout(r,8000));
await p.evaluate(()=>window._map.setPitch(0));
await new Promise(r=>setTimeout(r,2500));
const px=await p.evaluate(()=>{
  const m=window._map; const fs=m.queryRenderedFeatures({layers:['roofveg']});
  const hi=fs.filter(f=>f.properties._ndvi_ts && +f.properties._ndvi>0.25);
  const f=(hi[0]||fs[0]); if(!f) return null;
  const g=f.geometry; const cs=g.type==='Polygon'?g.coordinates[0]:g.coordinates[0][0];
  let x=0,y=0;for(const c of cs){x+=c[0];y+=c[1];}x/=cs.length;y/=cs.length;
  const pt=m.project([x,y]); return [Math.round(pt.x),Math.round(pt.y)];
});
if(px){ await p.mouse.click(px[0],px[1]); await new Promise(r=>setTimeout(r,1000)); }
const sparks=await p.evaluate(()=>document.querySelectorAll('#info .spark').length);
await p.screenshot({path:'/tmp/card_final.png'});
console.log('px',px,'sparks',sparks);
await b.close();
