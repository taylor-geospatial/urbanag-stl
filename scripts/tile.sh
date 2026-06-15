#!/bin/bash
# Build the cloud-native vector store from the GeoJSON intermediates.
#   FlatGeobuf (.fgb) = canonical store (host on Source Cooperative)
#   PMTiles  (.pmtiles) = what the map renders (HTTP range, no GeoJSON shipped)
# Requires ogr2ogr (GDAL) + tippecanoe (both from conda-forge).
set -e
cd "$(dirname "$0")/.."
OGR=${OGR:-/projects/bgtj/isaaccorley/envs/tiles/bin/ogr2ogr}
TIPPE=${TIPPE:-/projects/bgtj/isaaccorley/envs/tiles/bin/tippecanoe}

# stringify the per-building LST time series into a scalar column for FlatGeobuf
python3 - <<'PY'
import json
g = json.load(open("data/buildings.geojson"))
for f in g["features"]:
    ts = f["properties"].pop("_lst_ts", None)
    if ts:
        f["properties"]["_ts"] = json.dumps(ts, separators=(",", ":"))
json.dump(g, open("/tmp/buildings_fgb.geojson", "w"))
PY

# FlatGeobuf (canonical, spatially indexed)
"$OGR" -f FlatGeobuf -nlt PROMOTE_TO_MULTI -nln buildings public/data/buildings.fgb /tmp/buildings_fgb.geojson
"$OGR" -f FlatGeobuf -nlt PROMOTE_TO_MULTI -nln gardens  public/data/gardens.fgb  data/gardens.geojson

# PMTiles (render tiles)
"$TIPPE" -o public/data/buildings.pmtiles -l buildings -Z12 -z16 \
  --drop-densest-as-needed --extend-zooms-if-still-dropping --no-tile-size-limit --force /tmp/buildings_fgb.geojson
"$TIPPE" -o public/data/gardens.pmtiles -l gardens -Z9 -z16 \
  --drop-densest-as-needed --extend-zooms-if-still-dropping --force data/gardens.geojson

rm -f /tmp/buildings_fgb.geojson
echo "built: public/data/{buildings,gardens}.{fgb,pmtiles}"
