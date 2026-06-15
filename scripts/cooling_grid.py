"""Neighborhood cooling-potential grid: where greening cuts the most surface heat.

Bin the study area into ~150 m cells; per cell take mean NDVI (Sentinel) and mean LST
(Landsat); regress cell LST on cell NDVI across the neighborhood. Then for each cell,
predicted cooling if its greenness rose to a realistic target (NDVI 0.4) is
  cooling_C = -slope * max(0, target - cell_ndvi)
i.e. hot + currently-bare blocks have the most to gain. Output data/cooling.geojson.
"""
import json
import sys

import numpy as np
import shapely.geometry as sg
from rasterstats import zonal_stats

sys.path.insert(0, "scripts")
from analyze_rooftops import clearest, read_4326

BBOX = [-90.27, 38.60, -90.18, 38.66]
CELL = 0.0016  # ~150 m
TARGET = 0.40  # NDVI you could plausibly reach by greening a block


def main():
    s2 = clearest("sentinel-2-l2a", "2023-06-01/2024-09-15", (6, 7, 8))
    red, tf = read_4326(s2.assets["B04"].href)
    nir, _ = read_4326(s2.assets["B08"].href)
    ndvi = (nir - red) / (nir + red + 1e-6)
    ndvi[~np.isfinite(ndvi)] = np.nan

    ls = clearest("landsat-c2-l2", "2023-06-01/2024-09-15", (7, 8),
                  {"platform": {"in": ["landsat-8", "landsat-9"]}})
    dn, tfl = read_4326(ls.assets["lwir11"].href)
    lst = dn * 0.00341802 + 149.0 - 273.15
    lst[(dn == 0) | (lst < -25) | (lst > 80)] = np.nan

    cells, polys = [], []
    w, s, e, n = BBOX
    x = w
    while x < e:
        y = s
        while y < n:
            polys.append(sg.box(x, y, x + CELL, y + CELL))
            y += CELL
        x += CELL
    geoms = [sg.mapping(p) for p in polys]
    cn = np.array([z["mean"] if z["mean"] is not None else np.nan
                   for z in zonal_stats(geoms, ndvi, affine=tf, stats=["mean"], nodata=float("nan"))], "float32")
    cl = np.array([z["mean"] if z["mean"] is not None else np.nan
                   for z in zonal_stats(geoms, lst, affine=tfl, stats=["mean"], nodata=float("nan"))], "float32")

    m = np.isfinite(cn) & np.isfinite(cl)
    slope, _ = np.polyfit(cn[m], cl[m], 1)
    r = float(np.corrcoef(cn[m], cl[m])[0, 1])
    print(f"neighborhood LST~NDVI slope={slope:.1f} °C/NDVI  r={r:.2f}  cells={int(m.sum())}")

    feats = []
    for p, ndv, ls_ in zip(polys, cn, cl):
        if not (np.isfinite(ndv) and np.isfinite(ls_)):
            continue
        cooling = float(max(0.0, float(-slope) * max(0.0, TARGET - float(ndv))))
        feats.append({"type": "Feature",
                      "properties": {"ndvi": round(float(ndv), 3), "lst": round(float(ls_), 1),
                                     "cooling_C": round(cooling, 1)},
                      "geometry": sg.mapping(p)})
    json.dump({"type": "FeatureCollection", "features": feats}, open("data/cooling.geojson", "w"))
    json.dump({"neighborhood_slope": round(float(slope), 1), "neighborhood_r": round(r, 2),
               "target_ndvi": TARGET, "max_cooling_C": round(max(f["properties"]["cooling_C"] for f in feats), 1)},
              open("data/cooling_stats.json", "w"))
    print(f"wrote {len(feats)} cells; max cooling potential "
          f"{max(f['properties']['cooling_C'] for f in feats):.1f} °C")


if __name__ == "__main__":
    main()
