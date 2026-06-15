"""Re-detect rooftop greenery from NAIP 1 m aerial (4-band, true roof-scale NDVI).

10 m Sentinel mixed roofs with adjacent trees; NAIP (~0.6-1 m, R/G/B/NIR) resolves the
roof itself. Recomputes _ndvi / _ndvi_ctx / _ndvi_exc / _roofveg, and refreshes the
NDVI-derived priority + attribution using the existing per-building Landsat _lst.
"""
import json
from collections import Counter

import numpy as np
import rasterio
from rasterio.merge import merge
from rasterio.warp import transform_bounds
import pystac_client
import planetary_computer as pc
import geopandas as gpd
import shapely.geometry as sg
from rasterstats import zonal_stats

BBOX = [-90.27, 38.60, -90.18, 38.66]
cat = pystac_client.Client.open(
    "https://planetarycomputer.microsoft.com/api/stac/v1", modifier=pc.sign_inplace)


def norm(a):
    a = np.asarray(a, "float64")
    lo, hi = np.nanpercentile(a, 5), np.nanpercentile(a, 95)
    return np.clip((a - lo) / (hi - lo + 1e-9), 0, 1)


def main():
    items = [it for it in cat.search(collections=["naip"], bbox=BBOX).items()
             if it.id.startswith("mo_")]  # study area is Missouri (single UTM zone -> mosaicable)
    yr = Counter(x.datetime.year for x in items).most_common(1)[0][0]
    items = [x for x in items if x.datetime.year == yr]
    meta = items[0]
    print(f"NAIP {yr}: mosaicking {len(items)} MO tiles")
    srcs = [rasterio.open(x.assets["image"].href) for x in items]
    crs = srcs[0].crs
    l, b, r, t = transform_bounds("EPSG:4326", crs, *BBOX)
    mosaic, wt = merge(srcs, bounds=(l, b, r, t), indexes=[1, 4], nodata=0)
    for s in srcs:
        s.close()
    red = mosaic[0].astype("float32")
    nir = mosaic[1].astype("float32")
    ndvi = (nir - red) / (nir + red + 1e-6)
    ndvi[(red == 0) & (nir == 0)] = np.nan
    ndvi[~np.isfinite(ndvi)] = np.nan
    print(f"NAIP NDVI mosaic {ndvi.shape} in {crs}")

    g = json.load(open("data/buildings.geojson"))
    feats = g["features"]
    gdf = gpd.GeoDataFrame(
        [{} for _ in feats],
        geometry=[sg.shape(f["geometry"]) for f in feats], crs="EPSG:4326").to_crs(crs)
    roof = zonal_stats(gdf.geometry, ndvi, affine=wt, stats=["mean", "count"],
                       all_touched=False, nodata=float("nan"))
    rings = gdf.geometry.buffer(15).difference(gdf.geometry.buffer(2))
    ctx = zonal_stats(rings, ndvi, affine=wt, stats=["mean"], all_touched=True, nodata=float("nan"))

    rn = np.array([s["mean"] if s["mean"] is not None else np.nan for s in roof], "float32")
    cnt = np.array([s["count"] or 0 for s in roof])
    cn = np.array([s["mean"] if s["mean"] is not None else np.nan for s in ctx], "float32")
    exc = rn - cn
    area = np.array([f["properties"]["_area"] for f in feats])
    lst = np.array([f["properties"].get("_lst", np.nan) for f in feats], "float32")

    # outlier: ≥20 m² of roof pixels resolved, green, AND greener than the block ring
    big = (area >= 80) & (cnt >= 20)
    base = rn[big & np.isfinite(rn)]
    thr = max(0.30, float(np.nanmean(base) + 1.2 * np.nanstd(base)))
    roofveg = big & np.isfinite(rn) & np.isfinite(exc) & (rn >= thr) & (exc >= 0.10)
    print(f"NAIP roof NDVI median={np.nanmedian(base):.3f} thr={thr:.3f}; flagged={int(roofveg.sum())}")

    # refresh priority + attribution against existing Landsat _lst
    h = np.array([f["properties"]["_h"] for f in feats])
    suit = np.where((area >= 200) & (h <= 25), 1.0, 0.45)
    priority = norm(lst) * (1 - norm(rn)) * suit
    pthr = np.nanpercentile(priority[np.isfinite(priority)], 95)
    m = np.isfinite(rn) & np.isfinite(lst) & (area >= 80)
    slope, _ = np.polyfit(rn[m], lst[m], 1)
    rcorr = float(np.corrcoef(rn[m], lst[m])[0, 1])
    bare = lst[np.isfinite(lst) & (rn < 0.10)]
    green = lst[np.isfinite(lst) & (rn > 0.25)]
    delta = (float(np.nanmean(green) - np.nanmean(bare))
             if (len(green) >= 5 and len(bare) >= 5) else None)

    nveg = npri = 0
    for i, f in enumerate(feats):
        p = f["properties"]
        for k in ("_ndvi", "_ndvi_ctx", "_ndvi_exc", "_roofveg", "_priority", "_pflag"):
            p.pop(k, None)
        if np.isfinite(rn[i]):
            p["_ndvi"] = round(float(rn[i]), 3)
        if np.isfinite(cn[i]):
            p["_ndvi_ctx"] = round(float(cn[i]), 3)
        if np.isfinite(exc[i]):
            p["_ndvi_exc"] = round(float(exc[i]), 3)
        if np.isfinite(priority[i]):
            p["_priority"] = round(float(priority[i]), 3)
            if priority[i] >= pthr:
                p["_pflag"] = 1
                npri += 1
        if roofveg[i]:
            p["_roofveg"] = 1
            nveg += 1
    json.dump(g, open("data/buildings.geojson", "w"), separators=(",", ":"))

    a = json.load(open("data/attribution.json"))
    a.update({
        "ndvi_source": "NAIP 1m", "ndvi_scene": meta.id, "ndvi_date": str(meta.datetime.date()),
        "ndvi_lst_slope": round(float(slope), 1), "ndvi_lst_r": round(rcorr, 2),
        "cooling_per_03ndvi": round(float(-slope * 0.3), 1),
        "n_roofveg": nveg, "n_priority": npri,
    })
    if delta is not None:
        a["greenroof_delta"] = round(delta, 1)
    json.dump(a, open("data/attribution.json", "w"))
    print(f"flagged {nveg} green roofs, {npri} priority; slope={slope:.1f} delta={delta:.1f}")


if __name__ == "__main__":
    main()
