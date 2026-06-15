import { convex, explode, featureCollection, transformTranslate } from '@turf/turf';
import maplibregl from 'maplibre-gl';
import { Protocol } from 'pmtiles';
import SunCalc from 'suncalc';

// Vector tiles are PMTiles (cloud-native, HTTP range). DATA_BASE can point at a
// Source Cooperative bucket via the HTTPS proxy; canonical store is GeoParquet (.parquet).
const DATA_BASE = window.DATA_BASE || 'data';
maplibregl.addProtocol('pmtiles', new Protocol().tile);

/* St. Louis Cool Roofs — heat, shade & urban-ag insight map.
   MapLibre + SunCalc + Turf, no build step. */

const STL = { lng: -90.2249, lat: 38.63, zoom: 14.4, lat0: 38.63, lng0: -90.2249 };
const MIN_SHADOW_H = 6; // m — ignore tiny structures when casting shadows
const MAX_SHADOWS = 500; // cap per frame for snappiness
const SH_N = 8; // hourly shadow layers stacked for the shade-hours heatmap
const CAND_MIN_AREA = 350; // m² flat roof to flag as rooftop-garden candidate
const CAND_MAX_H = 20; // m — taller than this is awkward to garden

const RAD = 180 / Math.PI;
let buildingsReady = false;
let playing = false;
let playTimer = null;

const map = new maplibregl.Map({
  container: 'map',
  style: 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
  center: [STL.lng, STL.lat],
  zoom: 12.2,
  pitch: 55,
  bearing: -18,
  hash: true,
  antialias: true,
  maxPitch: 75,
});
map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'bottom-right');
map.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-right');

const $ = (id) => document.getElementById(id);

map.on('load', async () => {
  // intro fly-in
  map.flyTo({
    center: [STL.lng, STL.lat],
    zoom: STL.zoom,
    pitch: 55,
    bearing: -18,
    duration: 2600,
    curve: 1.5,
  });

  await Promise.all([loadHeat(), loadGardens(), loadBuildings(), loadAttribution(), loadCooling()]);
  $('loading').classList.add('hidden');

  wireUI();
  updateSun();
});

/* ---------------- data layers ---------------- */
function loadBuildings() {
  // buildings as PMTiles vector tiles; sub-layers are filter expressions on the same source
  map.addSource('buildings', { type: 'vector', url: `pmtiles://${DATA_BASE}/buildings.pmtiles` });
  // client-computed shade geometry stays in lightweight geojson sources
  map.addSource('shadows', { type: 'geojson', data: empty() });
  for (let i = 0; i < SH_N; i++) map.addSource(`sh${i}`, { type: 'geojson', data: empty() });

  map.addLayer({
    id: 'shadows',
    type: 'fill',
    source: 'shadows',
    paint: { 'fill-color': '#0b1f4d', 'fill-opacity': 0.5 }, // cool shade over warm heat
  });
  map.addLayer({
    id: 'buildings-3d',
    type: 'fill-extrusion',
    source: 'buildings',
    'source-layer': 'buildings',
    paint: {
      'fill-extrusion-height': ['get', '_h'],
      'fill-extrusion-base': 0,
      'fill-extrusion-opacity': 0.92,
      'fill-extrusion-color': [
        'interpolate',
        ['linear'],
        ['get', '_h'],
        3,
        '#2b3556',
        12,
        '#3a4f7a',
        30,
        '#5b7fb5',
        70,
        '#8fb6e6',
      ],
    },
  });
  map.addLayer({
    id: 'roof-candidates',
    type: 'fill-extrusion',
    source: 'buildings',
    'source-layer': 'buildings',
    filter: ['==', ['get', '_cand'], 1],
    layout: { visibility: 'none' },
    paint: {
      'fill-extrusion-height': ['+', ['get', '_h'], 1],
      'fill-extrusion-base': ['get', '_h'],
      'fill-extrusion-color': '#ffb454',
      'fill-extrusion-opacity': 0.9,
    },
  });
  for (let i = 0; i < SH_N; i++) {
    map.addLayer({
      id: `sh${i}`,
      type: 'fill',
      source: `sh${i}`,
      layout: { visibility: 'none' },
      paint: { 'fill-color': '#1f5bd6', 'fill-opacity': 0.14 },
    });
  }
  map.addLayer({
    id: 'priority',
    type: 'fill-extrusion',
    source: 'buildings',
    'source-layer': 'buildings',
    filter: ['==', ['get', '_pflag'], 1],
    layout: { visibility: 'none' },
    paint: {
      'fill-extrusion-height': ['+', ['get', '_h'], 1.5],
      'fill-extrusion-base': ['get', '_h'],
      'fill-extrusion-color': [
        'interpolate',
        ['linear'],
        ['coalesce', ['get', '_priority'], 0],
        0.2,
        '#ff9ec9',
        0.5,
        '#ff5ea8',
        0.8,
        '#e21b7a',
      ],
      'fill-extrusion-opacity': 0.96,
    },
  });
  map.addLayer({
    id: 'roofveg',
    type: 'fill-extrusion',
    source: 'buildings',
    'source-layer': 'buildings',
    filter: ['==', ['get', '_roofveg'], 1],
    paint: {
      'fill-extrusion-height': ['+', ['get', '_h'], 1.5],
      'fill-extrusion-base': ['get', '_h'],
      'fill-extrusion-color': '#7CFF5B',
      'fill-extrusion-opacity': 0.95,
    },
  });

  map.on('click', 'buildings-3d', onBuildingClick);
  const cursor = (c) => {
    map.getCanvas().style.cursor = c;
  };
  map.on('mouseenter', 'buildings-3d', () => cursor('pointer'));
  map.on('mouseleave', 'buildings-3d', () => cursor(''));
  map.on('moveend', scheduleShadows);
  map.on('idle', () => {
    if (!buildingsReady) {
      buildingsReady = true;
      scheduleShadows();
    }
  });
}

// in-view building features (lng/lat geometry) straight from the vector tiles
function inViewBuildings() {
  if (!map.getLayer('buildings-3d')) return [];
  return map.querySourceFeatures('buildings', {
    sourceLayer: 'buildings',
    filter: ['>=', ['get', '_h'], MIN_SHADOW_H],
  });
}

function loadGardens() {
  map.addSource('gardens', { type: 'vector', url: `pmtiles://${DATA_BASE}/gardens.pmtiles` });
  map.addLayer({
    id: 'gardens-fill',
    type: 'fill',
    source: 'gardens',
    'source-layer': 'gardens',
    paint: {
      'fill-color': [
        'match',
        ['get', 'category'],
        'greenhouse',
        '#7fe7ff',
        'community_garden',
        '#c6ff6e',
        'allotments',
        '#b6f05a',
        'orchard',
        '#8fe36a',
        'farmland',
        '#cfe88a',
        /* garden/park/other */ '#a3e635',
      ],
      'fill-opacity': 0.34,
    },
  });
  map.addLayer({
    id: 'gardens-line',
    type: 'line',
    source: 'gardens',
    'source-layer': 'gardens',
    paint: { 'line-color': '#d6ff7a', 'line-width': 1.1, 'line-opacity': 0.7 },
  });
  // labels for named green space
  map.addLayer({
    id: 'gardens-label',
    type: 'symbol',
    source: 'gardens',
    'source-layer': 'gardens',
    filter: ['all', ['has', 'name'], ['!=', ['get', 'name'], '']],
    layout: {
      'text-field': ['get', 'name'],
      'text-size': 11,
      'text-font': ['Open Sans Semibold', 'Arial Unicode MS Bold'],
      'text-max-width': 8,
    },
    paint: { 'text-color': '#dfffb0', 'text-halo-color': '#0a1020', 'text-halo-width': 1.4 },
  });
  map.on('click', 'gardens-fill', (e) => {
    const p = e.features[0].properties;
    new maplibregl.Popup({ closeButton: false })
      .setLngLat(e.lngLat)
      .setHTML(`<b>${p.name || 'green space'}</b><br><span style="color:#a3e635">${p.category}</span>`)
      .addTo(map);
  });
}

async function loadCooling() {
  // smooth (Gaussian) neighborhood cooling-potential surface, plasma-colorized PNG overlay
  let b;
  try {
    b = await (await fetch('data/cooling_bounds.json')).json();
  } catch {
    return;
  }
  map.addSource('cooling', { type: 'image', url: 'data/cooling.png', coordinates: [b.tl, b.tr, b.br, b.bl] });
  map.addLayer(
    {
      id: 'cooling',
      type: 'raster',
      source: 'cooling',
      layout: { visibility: 'none' },
      paint: { 'raster-opacity': 0.78, 'raster-resampling': 'linear' },
    },
    firstSymbolId()
  );
}

let heatScenes = [];
async function loadHeat() {
  // satellite imagery (Esri World Imagery) — sits above the dark base, below heat
  map.addSource('satellite', {
    type: 'raster',
    tileSize: 256,
    tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
    attribution: 'Imagery © Esri',
  });
  map.addLayer(
    { id: 'satellite', type: 'raster', source: 'satellite', layout: { visibility: 'none' } },
    firstSymbolId()
  );

  // seasonal LST scenes from the manifest
  let m;
  try {
    m = await (await fetch('data/heat_scenes.json')).json();
  } catch {
    markHeatMissing();
    return;
  }
  heatScenes = m.scenes || [];
  if (!heatScenes.length) return markHeatMissing();

  // default to summer if present, else first
  const def = heatScenes.find((s) => s.id === 'summer') || heatScenes[0];
  const b = def.bounds;
  map.addSource('heat', {
    type: 'image',
    url: def.png,
    coordinates: [b.tl, b.tr, b.br, b.bl],
  });
  map.addLayer(
    {
      id: 'heat',
      type: 'raster',
      source: 'heat',
      paint: { 'raster-opacity': 0.52, 'raster-resampling': 'linear' },
    },
    firstSymbolId()
  );

  const sel = $('heat-scene');
  sel.innerHTML = '';
  for (const s of heatScenes) {
    const o = document.createElement('option');
    o.value = s.id;
    o.textContent = `${s.label} · ${s.date}`;
    sel.appendChild(o);
  }
  sel.value = def.id;
  sel.onchange = () => setHeatScene(sel.value);
  setHeatLabel(def);
}
function setHeatScene(id) {
  const s = heatScenes.find((x) => x.id === id);
  if (!s || !map.getSource('heat')) return;
  const b = s.bounds;
  map.getSource('heat').updateImage({ url: s.png, coordinates: [b.tl, b.tr, b.br, b.bl] });
  setHeatLabel(s);
}
function setHeatLabel(s) {
  if (s.min != null && s.max != null) $('heat-mid').textContent = `${s.min}–${s.max}°C`;
}
async function loadAttribution() {
  let a;
  try {
    a = await (await fetch('data/attribution.json')).json();
  } catch {
    return;
  }
  if (a.greenroof_delta != null) $('ins-park').textContent = `${a.greenroof_delta}°C`;
  if (a.n_roofveg != null) $('ins-veg').textContent = a.n_roofveg;
  if (a.n_priority != null) $('ins-pri').textContent = a.n_priority;
  try {
    const c = await (await fetch('data/cooling_stats.json')).json();
    if (c.max_cooling_C != null) $('ins-cool').textContent = `up to −${c.max_cooling_C}°C`;
  } catch {}
}
function markHeatMissing() {
  $('lyr-heat').checked = false;
  $('lyr-heat').disabled = true;
  $('lyr-heat').closest('.toggle').style.opacity = 0.5;
  $('heat-mid').textContent = 'processing…';
}
function firstSymbolId() {
  for (const l of map.getStyle().layers) if (l.type === 'symbol') return l.id;
}

/* ---------------- sun + shadows ---------------- */
function currentDate() {
  const day = $('season').value; // YYYY-MM-DD
  const mins = +$('time').value;
  const d = new Date(`${day}T00:00:00-05:00`); // STL is UTC-5/-6; close enough for shade
  d.setMinutes(mins);
  return d;
}
function sunNow() {
  const d = currentDate();
  const p = SunCalc.getPosition(d, STL.lat, STL.lng);
  return { date: d, altDeg: p.altitude * RAD, azDeg: (p.azimuth * RAD + 180 + 360) % 360 };
}

let shadeHours = false;
function updateSun() {
  const s = sunNow();
  const mins = +$('time').value;
  const hh = String(Math.floor(mins / 60)).padStart(2, '0');
  const mm = String(mins % 60).padStart(2, '0');
  $('sun-time').textContent = `${hh}:${mm}`;
  $('sun-date').textContent = $('season').selectedOptions[0].text.split(' ')[0];
  $('sun-alt').textContent = `${s.altDeg.toFixed(0)}°`;
  $('sun-az').textContent = `${s.azDeg.toFixed(0)}°`;
  if (!shadeHours) scheduleShadows(); // live shadows track the slider; shade-hours is all-day
}

let shadowRAF = null;
function scheduleShadows() {
  if (shadowRAF) cancelAnimationFrame(shadowRAF);
  shadowRAF = requestAnimationFrame(() => (shadeHours ? computeShadeHours() : computeShadowsLive()));
}

const fc = (features) => ({ type: 'FeatureCollection', features });

// swept-footprint shadow polygons for in-view buildings at a given sun position
function castShadows(altDeg, azDeg, cap) {
  if (altDeg <= 1) return [];
  const shadowBearing = (azDeg + 180) % 360;
  const tan = Math.tan(altDeg / RAD);
  const feats = [];
  const seen = new Set();
  for (const f of inViewBuildings()) {
    const h = f.properties._h;
    const c = firstVertex(f.geometry);
    if (!c) continue;
    const key = `${c[0].toFixed(5)},${c[1].toFixed(5)}`; // de-dupe tile-split copies
    if (seen.has(key)) continue;
    seen.add(key);
    const L = Math.min(h / tan, 250) / 1000;
    try {
      const moved = transformTranslate(f, L, shadowBearing);
      const hull = convex(explode(featureCollection([f, moved])));
      if (hull && finiteGeom(hull.geometry)) feats.push(hull);
    } catch {}
    if (feats.length >= cap) break;
  }
  return feats;
}

function computeShadowsLive() {
  if (!buildingsReady || !map.getSource('shadows')) return;
  if (!$('lyr-shadows').checked) {
    map.getSource('shadows').setData(empty());
    return;
  }
  const s = sunNow();
  map.getSource('shadows').setData(fc(castShadows(s.altDeg, s.azDeg, MAX_SHADOWS)));
}

// stack SH_N hourly shadow sets across the selected season's daylight
function computeShadeHours() {
  if (!buildingsReady) return;
  const day = $('season').value;
  const times = [];
  for (let m = 0; m <= 24 * 60; m += 15) {
    const d = new Date(`${day}T00:00:00-05:00`);
    d.setMinutes(m);
    const p = SunCalc.getPosition(d, STL.lat, STL.lng);
    if (p.altitude * RAD > 4) {
      times.push({ alt: p.altitude * RAD, az: (p.azimuth * RAD + 180 + 360) % 360 });
    }
  }
  for (let i = 0; i < SH_N; i++) {
    const idx = times.length > 1 ? Math.round((i * (times.length - 1)) / (SH_N - 1)) : 0;
    const t = times[idx];
    map.getSource(`sh${i}`).setData(fc(t ? castShadows(t.alt, t.az, 280) : []));
    map.setLayoutProperty(`sh${i}`, 'visibility', 'visible');
  }
}
function clearShadeHours() {
  for (let i = 0; i < SH_N; i++) {
    map.getSource(`sh${i}`)?.setData(empty());
    map.setLayoutProperty(`sh${i}`, 'visibility', 'none');
  }
}

/* ---------------- building click → garden advice ---------------- */
function onBuildingClick(e) {
  const f = e.features[0];
  const p = f.properties;
  const h = +p._h;
  const area = +p._area;
  const floors = num(p.num_floors) || Math.max(1, Math.round(h / 3.2));
  const adv = gardenAdvice(f, h, area);

  const ndvi = num(p._ndvi);
  const exc = num(p._ndvi_exc);
  const lst = num(p._lst);
  const ndviRow =
    ndvi != null
      ? `<div class="stat"><span>rooftop NDVI</span><b>${ndvi.toFixed(2)}${exc != null ? ` (${exc >= 0 ? '+' : ''}${exc.toFixed(2)} vs block)` : ''}${p._roofveg ? ' 🌿' : ''}</b></div>`
      : '';
  const lstRow =
    lst != null ? `<div class="stat"><span>roof temp (summer)</span><b>${lst.toFixed(1)} °C</b></div>` : '';
  const ts = parseTs(p._ts);
  const tsBlock =
    ts && ts.length >= 3
      ? `<div class="ts-cap">summer roof temp, ${ts[0][0]}–${ts[ts.length - 1][0]}</div>${sparkline(ts)}`
      : '';
  let note = '';
  if (p._roofveg) {
    note = `<div class="advice" style="background:linear-gradient(135deg,rgba(124,255,91,.16),rgba(94,234,212,.08));border-color:rgba(124,255,91,.4)"><b>Likely existing roof greenery.</b> This roof's NDVI is an outlier <i>and</i> greener than its block — toggle <i>Satellite imagery</i> to verify.</div>`;
  } else if (p._pflag) {
    note = `<div class="advice" style="background:linear-gradient(135deg,rgba(255,94,168,.16),rgba(255,180,84,.08));border-color:rgba(255,94,168,.45)"><b>High heat-relief priority.</b> Hot, bare, buildable roof — greening it would cut the most surface heat here.</div>`;
  }
  $('info-title').textContent = p.name || 'Building';
  $('info-body').innerHTML = `
    <div class="stat"><span>height</span><b>${h.toFixed(1)} m</b></div>
    <div class="stat"><span>est. floors</span><b>${floors}</b></div>
    <div class="stat"><span>roof area</span><b>${area.toLocaleString()} m²</b></div>
    ${lstRow}
    ${ndviRow}
    <div class="stat"><span>shadow now</span><b>${adv.shadowLen} m</b></div>
    <div class="stat"><span>shaded daylight</span><b>${adv.shadePct}%</b></div>
    ${tsBlock}
    ${note}
    <div class="advice">${adv.text}</div>`;
  $('info').classList.remove('hidden');
}

function gardenAdvice(f, h, area) {
  const tanNow = Math.tan(Math.max(sunNow().altDeg, 0.5) / RAD);
  const shadowLen = Math.round(h / tanNow);

  // sample daylight: which compass side does this building's shadow fall on, and how often?
  const day = $('season').value;
  const bins = {};
  let samples = 0;
  for (let m = 5 * 60; m <= 21 * 60; m += 30) {
    const d = new Date(`${day}T00:00:00-05:00`);
    d.setMinutes(m);
    const pos = SunCalc.getPosition(d, STL.lat, STL.lng);
    if (pos.altitude <= 0.02) continue;
    samples++;
    const sunBearing = (pos.azimuth * RAD + 180 + 360) % 360;
    const shadeBearing = (sunBearing + 180) % 360; // shadow opposite sun
    const oct = octant(shadeBearing);
    bins[oct] = (bins[oct] || 0) + 1;
  }
  const best = Object.entries(bins).sort((a, b) => b[1] - a[1])[0] || ['N', 0];
  const shadePct = samples ? Math.round((best[1] / samples) * 100) : 0;

  let text;
  if (area >= CAND_MIN_AREA && h <= CAND_MAX_H) {
    text = `<b>Strong rooftop candidate.</b> Large (${area.toLocaleString()} m²), low roof — good for a greenhouse or container beds that would shade the membrane and cut roof heat gain.`;
  } else {
    text = `Plant on the <b>${best[0]}</b> side <span class="compass">🧭</span>: this building throws shade there ~<b>${shadePct}%</b> of daylight, so a bed tucked against that wall stays cool and needs less water in summer.`;
  }
  return { shadowLen, shadePct, side: best[0], text };
}

const OCT = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
function octant(deg) {
  return OCT[Math.round((deg % 360) / 45) % 8];
}

/* ---------------- UI wiring ---------------- */
function wireUI() {
  const vis = (id, on) =>
    map.getLayer(id) && map.setLayoutProperty(id, 'visibility', on ? 'visible' : 'none');
  $('lyr-heat').onchange = (e) => vis('heat', e.target.checked);
  $('lyr-buildings').onchange = (e) => vis('buildings-3d', e.target.checked);
  $('lyr-shadows').onchange = () => scheduleShadows();
  $('lyr-gardens').onchange = (e) => {
    ['gardens-fill', 'gardens-line', 'gardens-label'].forEach((l) => vis(l, e.target.checked));
  };
  $('lyr-roofs').onchange = (e) => vis('roof-candidates', e.target.checked);
  $('lyr-roofveg').onchange = (e) => vis('roofveg', e.target.checked);
  $('lyr-priority').onchange = (e) => vis('priority', e.target.checked);
  $('lyr-cooling').onchange = (e) => {
    vis('cooling', e.target.checked);
    if (map.getLayer('heat')) {
      map.setPaintProperty('heat', 'raster-opacity', e.target.checked ? 0.12 : 0.52);
    }
  };
  $('lyr-satellite').onchange = (e) => {
    vis('satellite', e.target.checked);
    // dim the heat wash when verifying against imagery so the photo reads clearly
    if (map.getLayer('heat')) {
      map.setPaintProperty('heat', 'raster-opacity', e.target.checked ? 0.3 : 0.52);
    }
  };
  $('lyr-shadehours').onchange = (e) => {
    shadeHours = e.target.checked;
    vis('shadows', !shadeHours && $('lyr-shadows').checked); // hide live shadows in heatmap mode
    if (shadeHours) {
      computeShadeHours();
    } else {
      clearShadeHours();
      computeShadowsLive();
    }
  };

  $('time').oninput = updateSun;
  $('season').onchange = () => {
    updateSun();
    if (shadeHours) scheduleShadows();
  };
  $('info-close').onclick = () => $('info').classList.add('hidden');

  $('play').onclick = () => {
    playing = !playing;
    $('play').classList.toggle('on', playing);
    $('play').textContent = playing ? '⏸ Pause' : '▶ Animate day';
    if (playing) {
      playTimer = setInterval(() => {
        let v = +$('time').value + 10;
        if (v > 1260) v = 300;
        $('time').value = v;
        updateSun();
      }, 90);
    } else clearInterval(playTimer);
  };

  $('deepdive').onclick = () => {
    // fly into the downtown core (tallest towers) and turn on the shade-hours microclimate view
    map.flyTo({
      center: [-90.1915, 38.6275],
      zoom: 16.2,
      pitch: 64,
      bearing: -22,
      duration: 2200,
      curve: 1.4,
    });
    if (!$('lyr-shadehours').checked) {
      $('lyr-shadehours').checked = true;
      $('lyr-shadehours').dispatchEvent(new Event('change'));
    }
  };
}

/* ---------------- helpers ---------------- */
function parseTs(v) {
  if (!v) return null;
  try {
    return typeof v === 'string' ? JSON.parse(v) : v;
  } catch {
    return null;
  }
}
// inline SVG sparkline of [ [year, °C], ... ]; green if cooling over time, red if warming
function sparkline(ts) {
  const W = 252;
  const H = 58;
  const pad = 8;
  const xs = ts.map((d) => d[0]);
  const ys = ts.map((d) => d[1]);
  const x0 = Math.min(...xs);
  const x1 = Math.max(...xs);
  const y0 = Math.min(...ys);
  const y1 = Math.max(...ys);
  const px = (x) => pad + ((x - x0) / (x1 - x0 || 1)) * (W - 2 * pad);
  const py = (y) => H - pad - ((y - y0) / (y1 - y0 || 1)) * (H - 2 * pad);
  const pts = ts.map((d) => `${px(d[0]).toFixed(1)},${py(d[1]).toFixed(1)}`).join(' ');
  const trend = ys[ys.length - 1] - ys[0];
  const col = trend > 0.6 ? '#ff6b5e' : trend < -0.6 ? '#7CFF5B' : '#ffb454';
  const dots = ts
    .map((d) => `<circle cx="${px(d[0]).toFixed(1)}" cy="${py(d[1]).toFixed(1)}" r="2.2" fill="${col}"/>`)
    .join('');
  return `<svg class="spark" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
    <polyline fill="none" stroke="${col}" stroke-width="2" points="${pts}"/>${dots}
    <text x="${pad}" y="11" fill="#8b97ad" font-size="9">${y1.toFixed(0)}°</text>
    <text x="${pad}" y="${H - 1}" fill="#8b97ad" font-size="9">${y0.toFixed(0)}°</text>
    </svg>`;
}
function firstVertex(g) {
  if (!g) return null;
  if (g.type === 'Polygon') return g.coordinates[0]?.[0];
  if (g.type === 'MultiPolygon') return g.coordinates[0]?.[0]?.[0];
  return null;
}
function finiteGeom(g) {
  const flat = JSON.stringify(g.coordinates);
  return !flat.includes('null') && !flat.includes('NaN');
}
function num(v) {
  const n = Number.parseFloat(v);
  return Number.isFinite(n) ? n : null;
}
function empty() {
  return { type: 'FeatureCollection', features: [] };
}
