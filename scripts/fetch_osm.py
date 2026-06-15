"""Fetch STL gardens / greenhouses / parks / allotments from OSM Overpass -> GeoJSON.

Stdlib only. Closed ways + multipolygon relations become Polygons; we keep a
`category` property so the webapp can color/filter them.
"""
import json
import time
import urllib.request

# citywide St. Louis bbox (S, W, N, E for Overpass)
BBOX = "38.53,-90.32,38.77,-90.18"
OVERPASS = "https://overpass-api.de/api/interpreter"

# tag -> category label shown in the app
TAGS = [
    ('leisure=garden', 'garden'),
    ('landuse=community_garden', 'community_garden'),
    ('landuse=allotments', 'allotments'),
    ('building=greenhouse', 'greenhouse'),
    ('landuse=greenhouse_horticulture', 'greenhouse'),
    ('landuse=orchard', 'orchard'),
    ('leisure=park', 'park'),
    ('landuse=farmland', 'farmland'),
    ('landuse=farmyard', 'farmland'),
]


def build_query():
    parts = []
    for sel, _ in TAGS:
        k, v = sel.split('=')
        parts.append(f'way["{k}"="{v}"]({BBOX});')
        parts.append(f'relation["{k}"="{v}"]({BBOX});')
    body = "".join(parts)
    return f"[out:json][timeout:180];({body});out geom;"


def cat_for(tags):
    for sel, label in TAGS:
        k, v = sel.split('=')
        if tags.get(k) == v:
            return label
    return 'other'


def ring(coords):
    r = [[c["lon"], c["lat"]] for c in coords]
    if r and r[0] != r[-1]:
        r.append(r[0])
    return r


def main():
    q = build_query()
    data = urllib.parse.urlencode({"data": q}).encode()
    for attempt in range(3):
        try:
            req = urllib.request.Request(OVERPASS, data=data,
                                         headers={"User-Agent": "stl-heat-garden/1.0"})
            with urllib.request.urlopen(req, timeout=200) as r:
                osm = json.loads(r.read())
            break
        except Exception as e:
            print(f"attempt {attempt+1} failed: {e}; retrying...")
            time.sleep(5)
    else:
        raise SystemExit("overpass failed")

    feats = []
    for el in osm.get("elements", []):
        tags = el.get("tags", {})
        cat = cat_for(tags)
        name = tags.get("name", "")
        props = {"category": cat, "name": name,
                 "osm_id": el.get("id"), "osm_type": el.get("type")}
        if el["type"] == "way" and "geometry" in el:
            r = ring(el["geometry"])
            if len(r) >= 4:
                feats.append({"type": "Feature", "properties": props,
                              "geometry": {"type": "Polygon", "coordinates": [r]}})
        elif el["type"] == "relation":
            polys = []
            for m in el.get("members", []):
                if m.get("role") == "outer" and "geometry" in m:
                    r = ring(m["geometry"])
                    if len(r) >= 4:
                        polys.append([r])
            if polys:
                feats.append({"type": "Feature", "properties": props,
                              "geometry": {"type": "MultiPolygon", "coordinates": polys}})

    out = {"type": "FeatureCollection", "features": feats}
    json.dump(out, open("data/gardens.geojson", "w"))
    from collections import Counter
    c = Counter(f["properties"]["category"] for f in feats)
    print(f"wrote {len(feats)} features -> data/gardens.geojson")
    print("by category:", dict(c))


if __name__ == "__main__":
    main()
