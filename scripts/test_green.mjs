import puppeteer from 'puppeteer';
const b=await puppeteer.launch({headless:'new',args:['--no-sandbox','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader','--ignore-gpu-blocklist','--window-size=1680,1050']});
const p=await b.newPage(); await p.setViewport({width:1680,height:1050,deviceScaleFactor:2});
const errs=[]; p.on('pageerror',e=>errs.push(e.message.slice(0,160)));
await p.goto('http://localhost:8013/',{waitUntil:'networkidle2',timeout:60000});
await p.waitForFunction(()=>document.getElementById('loading')?.classList.contains('hidden'),{timeout:45000});
await new Promise(r=>setTimeout(r,7000));
await p.evaluate(()=>{const s=document.getElementById('ndvi-thr');s.value='0';s.dispatchEvent(new Event('input'));});
await p.evaluate(()=>window._map.setPitch(0)); await new Promise(r=>setTimeout(r,2500));
const info=await p.evaluate(()=>{
  const m=window._map; const fs=m.queryRenderedFeatures({layers:['roofveg']});
  if(!fs.length) return {n:0};
  const f=fs[0]; const g=f.geometry;
  const cs=g.type==='Polygon'?g.coordinates[0]:g.coordinates[0][0];
  let x=0,y=0; for(const c of cs){x+=c[0];y+=c[1];} x/=cs.length;y/=cs.length;
  const pt=m.project([x,y]);
  return {n:fs.length, hasNdviTs:'_ndvi_ts' in f.properties, tsType:typeof f.properties._ndvi_ts, tsVal:String(f.properties._ndvi_ts).slice(0,70), px:[Math.round(pt.x),Math.round(pt.y)]};
});
let sparks=-1, body='';
if(info.px){ await p.mouse.click(info.px[0],info.px[1]);
  sparks=await p.evaluate(()=>document.getElementById('info').classList.contains('hidden')?-1:document.querySelectorAll('#info .spark').length);
  body=await p.evaluate(()=>document.getElementById('info-body')?.innerText||''); }
console.log('roofveg in view:',info.n,'| hasNdviTs:',info.hasNdviTs,'| tsType:',info.tsType,'| tsVal:',info.tsVal);
console.log('sparks:',sparks,'| errs:',errs.length?errs:'none');
console.log('card:', body.replace(/\n+/g,' | ').slice(0,200));
await b.close();
