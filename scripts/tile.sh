#!/bin/bash
# Build the cloud-native vector store from the GeoJSON intermediates.
#   GeoParquet (.parquet) = canonical store — ZSTD, Hilbert-sorted, bbox covering column
#                           (host on Source Cooperative; query/stream with DuckDB/parquet-wasm)
#   PMTiles   (.pmtiles)  = what the map renders today (HTTP range, no GeoJSON shipped)
set -e
cd "$(dirname "$0")/.."
TIPPE=${TIPPE:-/projects/bgtj/isaaccorley/envs/tiles/bin/tippecanoe}

# GeoParquet (canonical)
python scripts/convert_parquet.py

# PMTiles (render) — needs _ts as a scalar column too
python3 - <<'PY'
import json
g = json.load(open("data/buildings.geojson"))
for f in g["features"]:
    ts = f["properties"].pop("_lst_ts", None)
    if ts:
        f["properties"]["_ts"] = json.dumps(ts, separators=(",", ":"))
json.dump(g, open("/tmp/buildings_tile.geojson", "w"))
PY
"$TIPPE" -o public/data/buildings.pmtiles -l buildings -Z12 -z16 \
  --drop-densest-as-needed --extend-zooms-if-still-dropping --no-tile-size-limit --force /tmp/buildings_tile.geojson
"$TIPPE" -o public/data/gardens.pmtiles -l gardens -Z9 -z16 \
  --drop-densest-as-needed --extend-zooms-if-still-dropping --force data/gardens.geojson
rm -f /tmp/buildings_tile.geojson
# metadata + raster overlays travel alongside the tiles. The cooling surface ships as WebP —
# lazy-loaded only when toggled on, so it stays off the initial page load. WebP keeps the
# nodata alpha and is ~8x smaller than PNG. (Up-to-date hi-res aerial = Esri World Imagery
# raster basemap, streamed live by the client — no static aerial overlay is built or shipped.)
cp -f data/attribution.json data/cooling_stats.json data/cooling_bounds.json data/heat_scenes.json \
   data/heat_*.png public/data/ 2>/dev/null || true
python3 - <<'PY'
from PIL import Image
import os
src = "data/cooling.png"
if os.path.exists(src):
    Image.open(src).save("public/data/cooling.webp", "WEBP", quality=90, method=6)
    print("  cooling.png -> public/data/cooling.webp")
PY
echo "built: public/data/{buildings,gardens}.{parquet,pmtiles} + cooling.webp + metadata"
