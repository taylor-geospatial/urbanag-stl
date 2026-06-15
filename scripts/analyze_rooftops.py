"""Rooftop greenery + heat attribution for the workshop.

Per building (over the study bbox):
  _ndvi      roof NDVI  (Sentinel-2, pixel CENTERS inside the footprint only)
  _ndvi_ctx  NDVI of the surrounding ~30 m ring (the block context)
  _ndvi_exc  roof - context  (a roof greener than its block => likely a real roof garden)
  _roofveg   1 if roof is an NDVI outlier AND greener than its surroundings
  _lst       roof land-surface temperature (summer Landsat, °C)
  _priority  heat-relief priority 0-1 = hot + bare + buildable (where a NEW garden helps most)

Plus data/attribution.json:
  ndvi_lst_slope / _r   cooling per +1.0 NDVI (°C) and correlation across roofs
  park_delta_lst        how much cooler garden/park ground is than built blocks (°C)
"""
import json
import numpy as np
import rasterio
from rasterio.warp import calculate_default_transform, reproject, Resampling, transform_bounds
import pystac_client
import planetary_computer as pc
import shapely.geometry as sg
from rasterstats import zonal_stats

BBOX = [-90.27, 38.60, -90.18, 38.66]
cat = pystac_client.Client.open(
    "https://planetarycomputer.microsoft.com/api/stac/v1", modifier=pc.sign_inplace)


def read_4326(href, band=1):
    with rasterio.open(href) as src:
        l, b, r, t = transform_bounds("EPSG:4326", src.crs, *BBOX)
        win = src.window(l, b, r, t)
        arr = src.read(band, window=win).astype("float32")
        wt = src.window_transform(win)
        crs, nod = src.crs, src.nodata
    h, w = arr.shape
    dst_tf, dw, dh = calculate_default_transform(crs, "EPSG:4326", w, h,
                                                 left=wt.c, bottom=wt.f + wt.e * h,
                                                 right=wt.c + wt.a * w, top=wt.f)
    out = np.full((dh, dw), np.nan, "float32")
    reproject(arr, out, src_transform=wt, src_crs=crs, dst_transform=dst_tf,
              dst_crs="EPSG:4326", resampling=Resampling.bilinear, src_nodata=nod, dst_nodata=np.nan)
    return out, dst_tf


def clearest(collection, dr, months, q=None):
    qq = {"eo:cloud_cover": {"lt": 10}}
    if q:
        qq.update(q)
    items = [it for it in cat.search(collections=[collection], bbox=BBOX, datetime=dr, query=qq).items()
             if it.datetime.month in months]
    items.sort(key=lambda it: it.properties.get("eo:cloud_cover", 100))
    return items[0]


def norm(a):
    a = np.asarray(a, "float64")
    lo, hi = np.nanpercentile(a, 5), np.nanpercentile(a, 95)
    return np.clip((a - lo) / (hi - lo + 1e-9), 0, 1)


def main():
    g = json.load(open("data/buildings.geojson"))
    feats = g["features"]
    geoms = [f["geometry"] for f in feats]

    # ---- NDVI (Sentinel-2) ----
    s2 = clearest("sentinel-2-l2a", "2023-06-01/2024-09-15", (6, 7, 8))
    print("NDVI scene", s2.id, s2.datetime.date())
    red, tf = read_4326(s2.assets["B04"].href)
    nir, _ = read_4326(s2.assets["B08"].href)
    ndvi = (nir - red) / (nir + red + 1e-6)
    ndvi[~np.isfinite(ndvi)] = np.nan

    roof = zonal_stats(geoms, ndvi, affine=tf, stats=["mean", "count"],
                       all_touched=False, nodata=float("nan"))
    # context ring: buffer ~30 m (~0.00033 deg lon at STL) minus footprint
    rings = []
    for f in feats:
        geom = sg.shape(f["geometry"])
        try:
            ring = geom.buffer(0.00045).difference(geom.buffer(0.00008))
            rings.append(sg.mapping(ring if not ring.is_empty else geom))
        except Exception:
            rings.append(f["geometry"])
    ctx = zonal_stats(rings, ndvi, affine=tf, stats=["mean"], all_touched=True, nodata=float("nan"))

    # ---- LST (Landsat summer) ----
    ls = clearest("landsat-c2-l2", "2023-06-01/2024-09-15", (7, 8),
                  {"platform": {"in": ["landsat-8", "landsat-9"]}})
    print("LST scene", ls.id, ls.datetime.date())
    dn, tfl = read_4326(ls.assets["lwir11"].href)
    lst = dn * 0.00341802 + 149.0 - 273.15
    lst[(dn == 0) | (lst < -25) | (lst > 75)] = np.nan
    rooflst = zonal_stats(geoms, lst, affine=tfl, stats=["mean"], all_touched=True, nodata=float("nan"))

    # ---- attach per-building ----
    rn = np.array([s["mean"] if s["mean"] is not None else np.nan for s in roof], "float32")
    cn = np.array([s["mean"] if s["mean"] is not None else np.nan for s in ctx], "float32")
    cnt = np.array([s["count"] or 0 for s in roof])
    rl = np.array([s["mean"] if s["mean"] is not None else np.nan for s in rooflst], "float32")
    area = np.array([f["properties"]["_area"] for f in feats])
    h = np.array([f["properties"]["_h"] for f in feats])
    exc = rn - cn

    # outlier flag: enough roof pixels, green, AND greener than the block around it
    big = (area >= 150) & (cnt >= 1)
    base = rn[big & np.isfinite(rn)]
    thr = max(0.30, float(np.nanmean(base) + 1.2 * np.nanstd(base)))
    roofveg = big & np.isfinite(rn) & np.isfinite(exc) & (rn >= thr) & (exc >= 0.08)
    print(f"roof NDVI median={np.nanmedian(base):.3f} thr={thr:.3f}; flagged={int(roofveg.sum())}")

    # attribution: regress roof LST on roof NDVI across roofs
    m = np.isfinite(rn) & np.isfinite(rl) & (area >= 150)
    slope, inter = np.polyfit(rn[m], rl[m], 1)
    r = float(np.corrcoef(rn[m], rl[m])[0, 1])
    print(f"LST vs NDVI: slope={slope:.1f} °C per NDVI  r={r:.2f}  (n={int(m.sum())})")

    # park/garden ground cooling vs built
    gj = json.load(open("data/gardens.geojson"))
    parks = [f["geometry"] for f in gj["features"] if f["properties"]["category"] in ("park", "garden", "community_garden", "allotments", "orchard")]
    park_lst = zonal_stats(parks, lst, affine=tfl, stats=["mean"], all_touched=True, nodata=float("nan"))
    pv = np.array([s["mean"] for s in park_lst if s["mean"] is not None], "float32")
    built_mean = float(np.nanmean(rl[np.isfinite(rl)]))
    park_mean = float(np.nanmean(pv)) if len(pv) else float("nan")
    print(f"built roof mean LST={built_mean:.1f}  park ground mean LST={park_mean:.1f}  delta={park_mean-built_mean:.1f}")

    # heat-relief priority: hot + bare + buildable
    lst_p = norm(rl)
    bare = 1 - norm(rn)
    suit = np.where((area >= 200) & (h <= 25), 1.0, 0.45)
    priority = lst_p * bare * suit
    pflag = priority >= np.nanpercentile(priority[np.isfinite(priority)], 90)

    for i, f in enumerate(feats):
        p = f["properties"]
        p.pop("_ndvi", None); p.pop("_roofveg", None)
        if np.isfinite(rn[i]):
            p["_ndvi"] = round(float(rn[i]), 3)
        if np.isfinite(cn[i]):
            p["_ndvi_ctx"] = round(float(cn[i]), 3)
        if np.isfinite(exc[i]):
            p["_ndvi_exc"] = round(float(exc[i]), 3)
        if np.isfinite(rl[i]):
            p["_lst"] = round(float(rl[i]), 1)
        if np.isfinite(priority[i]):
            p["_priority"] = round(float(priority[i]), 3)
        if roofveg[i]:
            p["_roofveg"] = 1
        if pflag[i]:
            p["_pflag"] = 1

    json.dump(g, open("data/buildings.geojson", "w"), separators=(",", ":"))
    attribution = {
        "ndvi_scene": s2.id, "ndvi_date": str(s2.datetime.date()),
        "lst_scene": ls.id, "lst_date": str(ls.datetime.date()),
        "ndvi_lst_slope": round(float(slope), 1), "ndvi_lst_r": round(r, 2),
        "built_roof_mean_lst": round(built_mean, 1), "park_mean_lst": round(park_mean, 1),
        "park_delta_lst": round(park_mean - built_mean, 1),
        "n_roofveg": int(roofveg.sum()), "n_priority": int(pflag.sum()),
        # interpretable: cooling for a realistic greening step of +0.3 NDVI
        "cooling_per_03ndvi": round(float(-slope * 0.3), 1),
    }
    json.dump(attribution, open("data/attribution.json", "w"))
    print("wrote attribution.json:", attribution)


if __name__ == "__main__":
    main()
