"""Seasonal Landsat LST scenes + Sentinel-2 rooftop-NDVI outlier detection (STL).

Outputs (all over the study bbox):
  data/heat_<season>.png + data/heat_scenes.json   — 4 LST scenes, fixed 0-45 C ramp
  buildings.geojson gains _ndvi (mean rooftop NDVI) and _roofveg (1 = high-NDVI outlier)

Planetary Computer STAC (search free; assets signed). Landsat C2L2 ST_B10 for LST,
Sentinel-2 L2A B04/B08 for NDVI.
"""
import json
import numpy as np
import rasterio
from rasterio.warp import calculate_default_transform, reproject, Resampling, transform_bounds
import pystac_client
import planetary_computer as pc
import matplotlib

BBOX = [-90.27, 38.60, -90.18, 38.66]
LST_FIXED = (0.0, 45.0)   # fixed color range across scenes so seasons are comparable
CMAP = matplotlib.colors.LinearSegmentedColormap.from_list(
    "heat", ["#2b3a8f", "#2e8bc0", "#7fd3a8", "#f2e25c", "#f0922b", "#e23b2e"])

cat = pystac_client.Client.open(
    "https://planetarycomputer.microsoft.com/api/stac/v1", modifier=pc.sign_inplace)


def read_window_4326(href, band=1):
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
              dst_crs="EPSG:4326", resampling=Resampling.bilinear,
              src_nodata=nod, dst_nodata=np.nan)
    return out, dst_tf, nod


def corners(tf, dw, dh):
    west, north = tf.c, tf.f
    east, south = west + tf.a * dw, north + tf.e * dh
    return {"tl": [west, north], "tr": [east, north], "br": [east, south], "bl": [west, south]}


def best_item(collection, ranges, months, extra_query=None):
    q = {"eo:cloud_cover": {"lt": 8}}
    if extra_query:
        q.update(extra_query)
    items = []
    for dr in ranges:
        items += list(cat.search(collections=[collection], bbox=BBOX, datetime=dr, query=q).items())
    items = [it for it in items if it.datetime.month in months]
    items.sort(key=lambda it: it.properties.get("eo:cloud_cover", 100))
    return items[0] if items else None


# ---------------- seasonal LST scenes ----------------
def do_lst():
    seasons = [
        ("winter", "Winter", (12, 1, 2)),
        ("spring", "Spring", (4, 5)),
        ("summer", "Summer", (7, 8)),
        ("fall", "Fall", (9, 10)),
    ]
    ranges = ["2023-01-01/2024-12-31"]
    scenes = []
    for sid, label, months in seasons:
        it = best_item("landsat-c2-l2", ranges, months,
                       {"platform": {"in": ["landsat-8", "landsat-9"]}})
        if not it:
            print(f"  [skip] no clear {label} scene"); continue
        dn, tf, nod = read_window_4326(it.assets["lwir11"].href)
        lst = dn * 0.00341802 + 149.0 - 273.15
        lst[(dn == (nod or 0)) | (lst < -25) | (lst > 75)] = np.nan
        norm = np.clip((lst - LST_FIXED[0]) / (LST_FIXED[1] - LST_FIXED[0]), 0, 1)
        rgba = (CMAP(norm) * 255).astype("uint8")
        rgba[..., 3] = np.where(np.isfinite(lst), 205, 0).astype("uint8")
        from PIL import Image
        Image.fromarray(rgba, "RGBA").save(f"data/heat_{sid}.png")
        dh, dw = lst.shape
        v = lst[np.isfinite(lst)]
        scenes.append({"id": sid, "label": label, "png": f"data/heat_{sid}.png",
                       "date": str(it.datetime.date()),
                       "bounds": corners(tf, dw, dh),
                       "min": round(float(np.nanpercentile(v, 2)), 1),
                       "max": round(float(np.nanpercentile(v, 98)), 1)})
        print(f"  LST {label}: {it.datetime.date()}  {scenes[-1]['min']}–{scenes[-1]['max']}°C")
    json.dump({"fixed": LST_FIXED, "scenes": scenes}, open("data/heat_scenes.json", "w"))


# ---------------- rooftop NDVI outliers ----------------
def do_ndvi():
    it = best_item("sentinel-2-l2a", ["2023-06-01/2024-09-15"], (6, 7, 8))
    if not it:
        print("  [skip] no clear Sentinel-2 scene"); return
    print(f"  NDVI scene: {it.id} {it.datetime.date()} cloud={it.properties.get('eo:cloud_cover')}%")
    red, tf, _ = read_window_4326(it.assets["B04"].href)
    nir, _, _ = read_window_4326(it.assets["B08"].href)
    ndvi = (nir - red) / (nir + red + 1e-6)
    ndvi[~np.isfinite(ndvi)] = np.nan

    from rasterstats import zonal_stats
    g = json.load(open("data/buildings.geojson"))
    feats = g["features"]
    stats = zonal_stats(feats, ndvi, affine=tf, stats=["mean"], nodata=float("nan"),
                        all_touched=True, geojson_out=False)
    vals = np.array([s["mean"] if s["mean"] is not None else np.nan for s in stats], "float32")
    big = np.array([f["properties"]["_area"] >= 120 for f in feats])
    sample = vals[big & np.isfinite(vals)]
    thr = max(0.28, float(np.nanmean(sample) + 1.5 * np.nanstd(sample)))
    print(f"  building NDVI: median={np.nanmedian(sample):.3f}  outlier threshold={thr:.3f}")
    nflag = 0
    for f, v in zip(feats, vals):
        if np.isfinite(v):
            f["properties"]["_ndvi"] = round(float(v), 3)
            if v >= thr and f["properties"]["_area"] >= 120:
                f["properties"]["_roofveg"] = 1
                nflag += 1
    json.dump(g, open("data/buildings.geojson", "w"), separators=(",", ":"))
    print(f"  flagged {nflag} buildings as rooftop-greenery outliers")


if __name__ == "__main__":
    print("== seasonal LST =="); do_lst()
    print("== rooftop NDVI =="); do_ndvi()
    print("done.")
