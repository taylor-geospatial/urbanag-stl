"""Current (2026) rooftop-greenery detection: Overture polygons + Sentinel-2 multi-summer NDVI.

For each recent summer, build a per-pixel MAX-NDVI composite (max is cloud-robust: clouds/
shadows have low NDVI). Per building footprint take the in-footprint mean of each year's peak,
giving a yearly NDVI time series; the persistent greenness = median across years (a real roof
garden is green every summer, not one). Flag when persistent NDVI is high AND greener than the
surrounding block. Up-to-date because Sentinel-2 keeps imaging (5-day revisit).

Stores buildings.geojson: _ndvi (persistent peak), _ndvi_ctx, _ndvi_exc, _ndvi_ts (yearly),
_roofveg, refreshed _priority/_pflag; + attribution.json.
"""
import json
import sys

import numpy as np
from rasterio.warp import reproject, Resampling
from rasterio.transform import from_bounds as tfb
import pystac_client
import planetary_computer as pc
import geopandas as gpd
import shapely.geometry as sg
from rasterstats import zonal_stats

sys.path.insert(0, "scripts")
from analyze_rooftops import read_4326

BBOX = [-90.27, 38.60, -90.18, 38.66]
YEARS = [2023, 2024, 2025, 2026]
RES_M = 10.0
cat = pystac_client.Client.open(
    "https://planetarycomputer.microsoft.com/api/stac/v1", modifier=pc.sign_inplace)


def to_grid(arr, src_tf, dst_tf, h, w):
    out = np.full((h, w), np.nan, "float32")
    reproject(arr, out, src_transform=src_tf, src_crs="EPSG:4326", dst_transform=dst_tf,
              dst_crs="EPSG:4326", resampling=Resampling.bilinear, src_nodata=np.nan, dst_nodata=np.nan)
    return out


def norm(a):
    a = np.asarray(a, "float64")
    lo, hi = np.nanpercentile(a, 5), np.nanpercentile(a, 95)
    return np.clip((a - lo) / (hi - lo + 1e-9), 0, 1)


def main():
    w, s, e, n = BBOX
    width = int((e - w) * 111320 * np.cos(np.radians(38.63)) / RES_M)
    height = int((n - s) * 111320 / RES_M)
    dst_tf = tfb(w, s, e, n, width, height)

    yearly = {}
    for y in YEARS:
        scenes = list(cat.search(collections=["sentinel-2-l2a"], bbox=BBOX,
                                 datetime=f"{y}-06-01/{y}-09-10",
                                 query={"eo:cloud_cover": {"lt": 35}}).items())
        if not scenes:
            continue
        peak = np.full((height, width), np.nan, "float32")
        for sc in scenes:
            try:
                red, tfr = read_4326(sc.assets["B04"].href)
                nir, _ = read_4326(sc.assets["B08"].href)
            except Exception:
                continue
            ndvi = (nir - red) / (nir + red + 1e-6)
            ndvi[~np.isfinite(ndvi)] = np.nan
            peak = np.fmax(peak, to_grid(ndvi, tfr, dst_tf, height, width))
        yearly[y] = peak
        print(f"  {y}: {len(scenes)} summer scenes -> peak NDVI median={np.nanmedian(peak):.3f}")

    yrs = sorted(yearly)
    stack = np.stack([yearly[y] for y in yrs])  # [years, H, W]
    persistent = np.nanmedian(stack, axis=0)    # green every summer, not one
    print(f"persistent (median-of-yearly-peak) NDVI over {yrs}")

    g = json.load(open("data/buildings.geojson"))
    feats = g["features"]
    gdf = gpd.GeoDataFrame([{} for _ in feats],
                           geometry=[sg.shape(f["geometry"]) for f in feats], crs="EPSG:4326")
    roof = zonal_stats(gdf.geometry, persistent, affine=dst_tf, stats=["mean", "count"],
                       all_touched=False, nodata=float("nan"))
    rings = gdf.geometry.buffer(0.00045).difference(gdf.geometry.buffer(0.00008))
    ctx = zonal_stats(rings, persistent, affine=dst_tf, stats=["mean"], all_touched=True, nodata=float("nan"))
    # per-year roof NDVI for the time series sparkline
    per_year = {y: zonal_stats(gdf.geometry, yearly[y], affine=dst_tf, stats=["mean"],
                               all_touched=True, nodata=float("nan")) for y in yrs}

    rn = np.array([x["mean"] if x["mean"] is not None else np.nan for x in roof], "float32")
    cnt = np.array([x["count"] or 0 for x in roof])
    cn = np.array([x["mean"] if x["mean"] is not None else np.nan for x in ctx], "float32")
    exc = rn - cn
    area = np.array([f["properties"]["_area"] for f in feats])
    lst = np.array([f["properties"].get("_lst", np.nan) for f in feats], "float32")

    big = (area >= 200) & (cnt >= 1)
    thr = 0.18
    roofveg = big & np.isfinite(rn) & np.isfinite(exc) & (rn >= thr) & (exc >= 0.06)
    suit = np.where((area >= 200) & (np.array([f["properties"]["_h"] for f in feats]) <= 25), 1.0, 0.45)
    priority = norm(lst) * (1 - norm(rn)) * suit
    pthr = np.nanpercentile(priority[np.isfinite(priority)], 95)
    bare = lst[np.isfinite(lst) & (rn < 0.12)]
    green = lst[np.isfinite(lst) & (rn > 0.30)]
    delta = float(np.nanmean(green) - np.nanmean(bare)) if (len(green) >= 5 and len(bare) >= 5) else None

    nveg = npri = 0
    for i, f in enumerate(feats):
        p = f["properties"]
        for k in ("_ndvi", "_ndvi_ctx", "_ndvi_exc", "_ndvi_ts", "_roofveg", "_priority", "_pflag"):
            p.pop(k, None)
        if np.isfinite(rn[i]):
            p["_ndvi"] = round(float(rn[i]), 3)
        if np.isfinite(cn[i]):
            p["_ndvi_ctx"] = round(float(cn[i]), 3)
        if np.isfinite(exc[i]):
            p["_ndvi_exc"] = round(float(exc[i]), 3)
        ts = [[y, round(float(per_year[y][i]["mean"]), 3)] for y in yrs
              if per_year[y][i]["mean"] is not None and np.isfinite(per_year[y][i]["mean"])]
        if len(ts) >= 2:
            p["_ndvi_ts"] = json.dumps(ts, separators=(",", ":"))
        if np.isfinite(priority[i]):
            p["_priority"] = round(float(priority[i]), 3)
            if priority[i] >= pthr:
                p["_pflag"] = 1
                npri += 1
        if roofveg[i]:
            p["_roofveg"] = 1
            nveg += 1
    json.dump(g, open("data/buildings.geojson", "w"), separators=(",", ":"))

    a = json.load(open("data/attribution.json")) if __import__("os").path.exists("data/attribution.json") else {}
    a.update({"ndvi_source": f"Sentinel-2 summers {yrs[0]}–{yrs[-1]}", "ndvi_years": yrs,
              "n_roofveg": nveg, "n_priority": npri})
    if delta is not None:
        a["greenroof_delta"] = round(delta, 1)
    json.dump(a, open("data/attribution.json", "w"))
    print(f"flagged {nveg} persistent green roofs (NDVI≥{thr} & greener than block), {npri} priority")


if __name__ == "__main__":
    main()
