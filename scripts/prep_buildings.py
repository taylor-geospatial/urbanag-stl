"""Slim + enrich the Overture buildings GeoJSON for snappy browser loading.

- precompute _h (height m), _area (m2 via local equirectangular), _cand (rooftop flag)
- keep only a primary name; round coords to 6 dp
Rewrites data/buildings.geojson in place (smaller).
"""
import json
import math

SRC = "data/buildings.geojson"
LAT0 = 38.63
MPERDEG = 111320.0
COSLAT = math.cos(math.radians(LAT0))
CAND_MIN_AREA, CAND_MAX_H = 350, 20


def ring_area_m2(ring):
    # shoelace in local meters
    pts = [((x) * MPERDEG * COSLAT, (y) * MPERDEG) for x, y in ring]
    s = 0.0
    for i in range(len(pts) - 1):
        s += pts[i][0] * pts[i + 1][1] - pts[i + 1][0] * pts[i][1]
    return abs(s) / 2.0


def poly_area(geom):
    if geom["type"] == "Polygon":
        rings = geom["coordinates"]
        return ring_area_m2(rings[0]) - sum(ring_area_m2(r) for r in rings[1:])
    if geom["type"] == "MultiPolygon":
        return sum(ring_area_m2(p[0]) - sum(ring_area_m2(r) for r in p[1:]) for p in geom["coordinates"])
    return 0.0


def rnd(geom):
    def r(c): return [round(c[0], 6), round(c[1], 6)]
    if geom["type"] == "Polygon":
        geom["coordinates"] = [[r(c) for c in ring] for ring in geom["coordinates"]]
    elif geom["type"] == "MultiPolygon":
        geom["coordinates"] = [[[r(c) for c in ring] for ring in poly] for poly in geom["coordinates"]]
    return geom


def main():
    g = json.load(open(SRC))
    out = []
    for f in g["features"]:
        p = f.get("properties", {})
        h = p.get("height")
        try:
            h = float(h)
        except (TypeError, ValueError):
            nf = p.get("num_floors")
            try:
                h = float(nf) * 3.2
            except (TypeError, ValueError):
                h = 6.0
        h = max(2.0, round(h, 1))
        area = round(poly_area(f["geometry"]))
        name = ""
        names = p.get("names")
        if isinstance(names, dict):
            name = names.get("primary", "") or ""
        elif isinstance(names, str):
            try:
                name = json.loads(names).get("primary", "")
            except Exception:
                name = ""
        props = {"_h": h, "_area": area, "name": name}
        if area >= CAND_MIN_AREA and h <= CAND_MAX_H:
            props["_cand"] = 1
        out.append({"type": "Feature", "properties": props, "geometry": rnd(f["geometry"])})

    fc = {"type": "FeatureCollection", "features": out}
    json.dump(fc, open(SRC, "w"), separators=(",", ":"))
    ncand = sum(1 for f in out if f["properties"].get("_cand"))
    import os
    print(f"slimmed {len(out)} buildings -> {os.path.getsize(SRC)//1024} KB; rooftop candidates={ncand}")


if __name__ == "__main__":
    main()
