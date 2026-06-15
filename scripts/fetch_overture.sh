#!/bin/bash
set -e
cd ~/github/stl-heat-garden
uv venv .venv -p 3.11 >/dev/null 2>&1 || true
source .venv/bin/activate
uv pip install -q overturemaps 2>&1 | tail -1
echo "downloading Overture buildings..."
overturemaps download --bbox=-90.27,38.60,-90.18,38.66 -f geojson --type=building -o data/buildings.geojson
echo "done: $(ls -la data/buildings.geojson | awk '{print $5}') bytes"
python - <<'PY'
import json
g=json.load(open("data/buildings.geojson"))
n=len(g["features"]); wh=sum(1 for f in g["features"] if f["properties"].get("height"))
print(f"buildings={n}  with_height={wh}")
PY
