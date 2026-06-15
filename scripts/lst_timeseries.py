"""Per-building summer roof-LST time series (multi-year) for the before/after view.

For each year, grab the clearest summer (Jun–Aug) Landsat scene over the study bbox,
zonal-sample each building's roof LST, and store buildings.geojson `_lst_ts` = [[year, °C], ...].
A roof that greened between years should show a downward step.
"""
import json
import sys

import numpy as np
from rasterstats import zonal_stats

sys.path.insert(0, "scripts")
from analyze_rooftops import read_4326, clearest  # reuse loaders

YEARS = [2019, 2020, 2021, 2022, 2023, 2024]


def main():
    g = json.load(open("data/buildings.geojson"))
    geoms = [f["geometry"] for f in g["features"]]
    series = {i: [] for i in range(len(geoms))}

    for y in YEARS:
        try:
            it = clearest("landsat-c2-l2", f"{y}-06-01/{y}-08-31", (6, 7, 8),
                          {"platform": {"in": ["landsat-8", "landsat-9"]}})
        except Exception as e:
            print(f"  {y}: no scene ({e})"); continue
        dn, tf = read_4326(it.assets["lwir11"].href)
        lst = dn * 0.00341802 + 149.0 - 273.15
        lst[(dn == 0) | (lst < -25) | (lst > 80)] = np.nan
        stats = zonal_stats(geoms, lst, affine=tf, stats=["mean"], all_touched=True, nodata=float("nan"))
        n = 0
        for i, s in enumerate(stats):
            if s["mean"] is not None and np.isfinite(s["mean"]):
                series[i].append([y, round(float(s["mean"]), 1)])
                n += 1
        print(f"  {y}: {it.id} {it.datetime.date()} cloud={it.properties.get('eo:cloud_cover')}%  roofs={n}")

    nattach = 0
    for i, f in enumerate(g["features"]):
        if len(series[i]) >= 3:
            f["properties"]["_lst_ts"] = series[i]
            nattach += 1
    json.dump(g, open("data/buildings.geojson", "w"), separators=(",", ":"))
    print(f"attached time series to {nattach} buildings")


if __name__ == "__main__":
    main()
