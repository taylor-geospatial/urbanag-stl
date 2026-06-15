# STL Cool Roofs — `urbanag-stl`

**Live:** https://research.taylorgeospatial.org/urbanag-stl/

An interactive MapLibre map of **St. Louis** for urban-heat + urban-agriculture decisions:
surface temperature, building shade, and where rooftop gardens already exist (or should go).

Built as a companion analysis to [ropitz/urban_ag_stl](https://github.com/ropitz/urban_ag_stl)
(which scores vacant ground parcels); this app adds the heat / rooftop / shadow dimension.

## What it shows

- **Seasonal surface heat** — real Landsat-8/9 land-surface-temperature scenes
  (Winter → Summer, scrub the selector). Summer rooftops hit ~50 °C; parks stay cool.
- **3D buildings** — Overture footprints extruded by height.
- **Live shadows** — SunCalc + a date/time slider cast building shadows in real time;
  click a building for the **best-shaded side to plant** (cool, low-water bed placement).
- **Existing roof greenery (NDVI outliers)** — per-building Sentinel-2 NDVI using only pixel
  centers **inside** the footprint, flagged only when the roof is also **greener than its
  surrounding block** (roof − context ring). Kills "building next to a tree" false positives.
- **Heat attribution** — roof LST regressed on roof NDVI (≈ **−11.7 °C per NDVI unit**, r −0.57);
  green roofs (NDVI > 0.4) run **~3.3 °C cooler** than bare roofs. Shown in the *Heat ↔ greenery* panel.
- **Heat-relief priority** — hot + bare + buildable roofs ranked as the best places for a **new**
  garden to cut surface heat (where greening pays off most).
- **Shade-hours heatmap** — stacks each daylight hour's shadows so all-day-shaded ground reads
  darkest (cool microclimate / shade-tolerant planting).
- **Satellite imagery toggle** — Esri World Imagery to visually verify the flagged rooftops.
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
python scripts/fetch_scenes_ndvi.py   # seasonal LST pngs (Winter→Fall), fixed 5–50°C ramp
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
