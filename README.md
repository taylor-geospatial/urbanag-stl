# Cool Roofs St. Louis — `urbanag-stl`

**Live:** https://research.taylorgeospatial.org/urbanag-stl/

A **Taylor Geospatial** project. An interactive MapLibre map of **St. Louis** for urban-heat +
urban-agriculture decisions: surface temperature, building shade, and where rooftop gardens
already exist (or should go). Brand type is Taylor Geospatial's **gintronic** / **degular-text**
(Adobe Fonts kit) over the espresso/cream/orange palette.

Built as a companion analysis to [ropitz/urban_ag_stl](https://github.com/ropitz/urban_ag_stl)
(which scores vacant ground parcels); this app adds the heat / rooftop / shadow dimension.

## What it shows

- **Seasonal surface heat** — real Landsat-8/9 land-surface-temperature scenes
  (Winter → Summer, scrub the selector). Summer rooftops hit ~122 °F; parks stay cool.
- **3D buildings** — Overture footprints extruded by height.
- **Live shadows** — SunCalc + a date/time slider cast building shadows in real time;
  click a building for the **best-shaded side to plant** (cool, low-water bed placement).
- **Existing roof greenery — Sentinel-2 multi-summer NDVI** (current through 2026). For each
  Overture footprint we build a per-summer **max-NDVI** composite (max is cloud-robust), take the
  **median across summers 2023–2026** as *persistent* greenness, and flag a roof when that's high
  **and** greener than its surrounding block. An **interactive NDVI-threshold slider** tunes recall
  live; a click shows the roof's **NDVI-by-summer sparkline** (persistent-high = real garden,
  one-off spike = noise). Per-building 10 m pixels still mix on small roofs — persistence + the
  slider + the **aerial basemap toggle** are the verification path.
- **Heat attribution** — roof land-surface temperature falls with roof NDVI; green roofs run
  **~3–4 °F cooler** than bare roofs (Sentinel-2). Shown in the *Heat ↔ greenery* panel (all °F).
- **Heat-relief priority** — hot + bare + buildable roofs ranked as the best places for a **new**
  garden to cut surface heat (where greening pays off most).
- **Shade-hours heatmap** — stacks each daylight hour's shadows so all-day-shaded ground reads
  darkest (cool microclimate / shade-tolerant planting).
- **Aerial basemap toggle** — current high-res **Esri World Imagery** (tile-streamed) to
  visually verify the flagged rooftops against up-to-date imagery.
- **Gardens & greenhouses** — OSM `leisure=garden`, greenhouses, allotments, parks, orchards.
- **Flat-roof candidates** — large low roofs that are good greenhouse/garden sites.

## Stack

- **MapLibre GL** map, **SunCalc** sun geometry, **Turf** shadow geometry.
- **bun** builds the JS bundle (`src/app.js` → `public/app.js`); **biome** lints/formats.
- Data prep in Python (`uv` venv): Overture buildings, Overpass gardens,
  Microsoft Planetary Computer for Landsat LST + Sentinel-2 NDVI.
- **Cloud-native vector data, no GeoJSON shipped.** Canonical store is **GeoParquet 1.1**
  (`*.parquet`, ZSTD, Hilbert-sorted with small row groups + a `bbox` covering column, so a
  reader prunes to just the row groups covering the viewport — host on Source Cooperative,
  query/stream with DuckDB or parquet-wasm). Buildings 2.4 MB vs 11.7 MB FlatGeobuf / 7.2 MB
  PMTiles. The map *renders* from **PMTiles** (`*.pmtiles`, HTTP range) — vector tiles already
  stream only the visible area as you pan. Rooftop sub-layers (greenery, priority, candidates)
  are filter expressions on the one buildings source; shadows are cast from
  `querySourceFeatures` of the in-view tiles. `window.DATA_BASE` repoints tiles at a remote
  bucket via the HTTPS proxy.

## Run

```bash
bun install
bun run build          # bundle src/app.js -> public/app.js
bun run serve          # http://localhost:8011   (or: python3 -m http.server -d public 8011)
```

Lint / format:

```bash
bun run lint           # biome check
bun run format         # biome format --write
```

## Regenerate data (optional)

```bash
uv venv .venv -p 3.11 && source .venv/bin/activate
uv pip install overturemaps rasterio pystac-client planetary-computer pillow matplotlib numpy rasterstats
bash scripts/fetch_overture.sh        # buildings.geojson
python scripts/fetch_osm.py           # gardens.geojson
python scripts/prep_buildings.py      # slim + height/area/candidate flags
python scripts/fetch_scenes_ndvi.py   # seasonal LST pngs (Winter→Fall), fixed ramp (≈41–122 °F)
python scripts/analyze_rooftops.py    # roof NDVI (within-polygon + context), LST attribution,
                                      # green-roof flags, heat-relief priority, attribution.json
python scripts/lst_timeseries.py      # per-building summer roof-LST 2019–2024 (click sparkline)
bash   scripts/tile.sh                # GeoJSON intermediates -> GeoParquet + PMTiles (public/data)
```

## Deploy

Pushing to `main` triggers `.github/workflows/deploy.yml`: GitHub Actions installs with bun,
runs `bun run build`, and publishes `public/` to GitHub Pages. `public/data/` holds the
PMTiles (rendered) + GeoParquet (canonical) + seasonal LST PNGs; PMTiles are HTTP-range
requested so the map only pulls the visible tiles. To serve the tiles from Source Cooperative
instead, set `window.DATA_BASE` to the bucket URL (via the HTTPS proxy).

## Caveats

- NDVI rooftop flags use 10 m Sentinel-2 pixels — roofs smaller than a pixel mix with
  surroundings, so some flags are buildings next to trees, not true roof gardens. The
  **Satellite** toggle is the human verification step.
- Study area is a downtown→Central West End bbox (`-90.27,38.60,-90.18,38.66`); widen the
  bbox in the fetch scripts to cover more of the city.
- Shadows are a swept-footprint approximation (good for siting intuition, not a solar survey).
